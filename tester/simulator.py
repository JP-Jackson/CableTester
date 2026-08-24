"""A simulated DB9 cable + loopback plug, for testing without hardware."""

from __future__ import annotations

import random
import time

import serial


class FakeCable:
    """Describes how a simulated cable behaves.

    ``drives`` maps an output line to the input lines it energises through the
    loopback plug. ``data`` enables the 2/3 path. ``corrupt_above`` injects byte
    errors above a given baud rate, imitating an aging cable.
    """

    def __init__(
        self,
        drives=None,
        data=True,
        corrupt_above=None,
        corrupt_rate=0.01,
        drop_above=None,
        stuck_lines=(),
        parity_fails_above=None,
        realtime=False,
    ):
        self.drives = drives if drives is not None else {"DTR": ["DCD", "DSR"], "RTS": ["CTS"]}
        self.data = data
        self.corrupt_above = corrupt_above
        self.corrupt_rate = corrupt_rate
        self.drop_above = drop_above
        self.stuck_lines = set(stuck_lines)
        self.parity_fails_above = parity_fails_above
        self.realtime = realtime


class FakeSerial:
    """Minimal pyserial-compatible stand-in driven by a FakeCable."""

    def __init__(self, cable: FakeCable, **kwargs):
        self.cable = cable
        self.port = kwargs.get("port")
        self.baudrate = kwargs.get("baudrate", 9600)
        self.parity = kwargs.get("parity", serial.PARITY_NONE)
        self.timeout = kwargs.get("timeout", 0.2)
        self.write_timeout = kwargs.get("write_timeout", 5.0)
        self.is_open = True
        self._dtr = False
        self._rts = False
        self._rx = bytearray()
        self._arrivals = []          # per-byte arrival time when pacing is on
        self._rng = random.Random(1234)
        self._latched = set()

    # -- modem control lines -------------------------------------------------
    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = bool(value)

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self._rts = bool(value)

    def _input(self, name):
        if name in self.cable.stuck_lines:
            # A stuck line latches asserted the first time it is driven.
            for out, targets in self.cable.drives.items():
                if name in targets and getattr(self, f"_{out.lower()}"):
                    self._latched.add(name)
            return name in self._latched
        for out, targets in self.cable.drives.items():
            if name in targets and getattr(self, f"_{out.lower()}"):
                return True
        return False

    cts = property(lambda self: self._input("CTS"))
    dsr = property(lambda self: self._input("DSR"))
    cd = property(lambda self: self._input("DCD"))
    ri = property(lambda self: self._input("RI"))

    # -- data path -----------------------------------------------------------
    def _byte_time(self):
        bits = 11 if self.parity != serial.PARITY_NONE else 10
        return bits / float(self.baudrate)

    def _arrived(self):
        """How many queued bytes have 'come down the wire' by now."""
        if not self.cable.realtime:
            return len(self._rx)
        now = time.monotonic()
        count = 0
        for stamp in self._arrivals:
            if stamp > now:
                break
            count += 1
        return count

    def write(self, data):
        if not self.cable.data:
            return len(data)
        cable = self.cable
        corrupt = cable.corrupt_above is not None and self.baudrate > cable.corrupt_above
        parity_bad = (
            cable.parity_fails_above is not None
            and self.baudrate > cable.parity_fails_above
            and self.parity != serial.PARITY_NONE
        )
        drop = cable.drop_above is not None and self.baudrate > cable.drop_above
        clock = max(self._arrivals[-1] if self._arrivals else 0.0, time.monotonic())
        for byte in data:
            clock += self._byte_time()
            if drop and self._rng.random() < cable.corrupt_rate:
                continue
            if (corrupt or parity_bad) and self._rng.random() < cable.corrupt_rate:
                byte ^= 1 << self._rng.randrange(8)
            self._rx.append(byte)
            if cable.realtime:
                self._arrivals.append(clock)
        return len(data)

    def read(self, size=1):
        available = self._arrived()
        if not available and self.cable.realtime and self._arrivals and self.timeout:
            # Block like a real UART would rather than spinning.
            time.sleep(min(self.timeout, max(0.0, self._arrivals[0] - time.monotonic())))
            available = self._arrived()
        take = min(size, available)
        chunk = bytes(self._rx[:take])
        del self._rx[:take]
        del self._arrivals[:take]
        return chunk

    @property
    def in_waiting(self):
        return self._arrived()

    def flush(self):
        pass

    def reset_input_buffer(self):
        self._rx.clear()
        self._arrivals.clear()

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False


def factory_for(cable: FakeCable):
    """Return a serial_factory callable bound to one simulated cable."""

    def _factory(**kwargs):
        return FakeSerial(cable, **kwargs)

    return _factory


# ---------------------------------------------------------------------------
# Named simulated cables, exposed as virtual ports by `--simulate`.
# ---------------------------------------------------------------------------

FULL_HANDSHAKE = {"DTR": ["DCD", "DSR"], "RTS": ["CTS"]}

SIM_CABLES = {
    "SIM-GOOD": (
        "Simulated: known-good full-handshake cable",
        FakeCable(FULL_HANDSHAKE, realtime=True),
    ),
    "SIM-MARGINAL": (
        "Simulated: aging cable, errors above 19200",
        FakeCable(FULL_HANDSHAKE, corrupt_above=19200, corrupt_rate=0.02, realtime=True),
    ),
    "SIM-3WIRE": (
        "Simulated: 3-wire cable (2, 3, 5 only)",
        FakeCable({"DTR": [], "RTS": []}, realtime=True),
    ),
    "SIM-OPEN": (
        "Simulated: broken cable, pin 8 open",
        FakeCable({"DTR": ["DCD", "DSR"], "RTS": []}, realtime=True),
    ),
    # Nothing loops back at all: no handshake path and no data path. This is
    # what the instrument sees when the loopback plug was never fitted, or when
    # a connector is not seated, and it exists so the continuity monitor's
    # refusal to watch a dead cable can be exercised without hardware.
    "SIM-NOPLUG": (
        "Simulated: loopback plug not fitted",
        FakeCable({"DTR": [], "RTS": []}, data=False, realtime=True),
    ),
}


def install(serial_tests) -> None:
    """Register every simulated cable as a virtual port on the serial layer."""
    for device, (description, cable) in SIM_CABLES.items():
        serial_tests.register_simulated(
            device,
            {
                "device": device,
                "description": description,
                "manufacturer": "cabletester",
                "product": "simulator",
                "serial_number": "",
                "vid": None,
                "pid": None,
                "vid_pid": "",
                "hwid": "SIMULATED",
                "simulated": True,
            },
            factory_for(cable),
        )
