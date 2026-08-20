"""A simulated DB9 cable + loopback plug, for testing without hardware."""

from __future__ import annotations

import random
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
    ):
        self.drives = drives if drives is not None else {"DTR": ["DCD", "DSR"], "RTS": ["CTS"]}
        self.data = data
        self.corrupt_above = corrupt_above
        self.corrupt_rate = corrupt_rate
        self.drop_above = drop_above
        self.stuck_lines = set(stuck_lines)
        self.parity_fails_above = parity_fails_above


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
        for byte in data:
            if drop and self._rng.random() < cable.corrupt_rate:
                continue
            if (corrupt or parity_bad) and self._rng.random() < cable.corrupt_rate:
                byte ^= 1 << self._rng.randrange(8)
            self._rx.append(byte)
        return len(data)

    def read(self, size=1):
        chunk = bytes(self._rx[:size])
        del self._rx[: len(chunk)]
        return chunk

    @property
    def in_waiting(self):
        return len(self._rx)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self._rx.clear()

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False


def factory_for(cable: FakeCable):
    """Return a serial_factory callable bound to one simulated cable."""

    def _factory(**kwargs):
        return FakeSerial(cable, **kwargs)

    return _factory
