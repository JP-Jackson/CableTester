"""Continuous continuity watch, for finding intermittent faults.

This is the test that goes at the reason the project exists. Cables that fail
in the field pass every continuity check on a bench, which means they are
wired correctly and fail anyway. A conductor broken inside its insulation, or
a cold joint at a connector, makes perfect contact lying still and opens for a
few hundred milliseconds when the cable is flexed. No static test can see that,
however thorough, because the fault is not present while the test runs.

So this one holds the lines under continuous watch WHILE A TECHNICIAN MOVES
THE CABLE, and records every dropout with a timestamp. The instruction to move
the cable is the test; the software only counts.

**The limit, which must be on screen and not only here.** Both protocols are
sampled by polling, so a dropout shorter than the sample interval is invisible.
On serial the real floor is not this code at all: a USB-serial adapter reports
modem line changes on an interrupt endpoint it polls every 1 to 10 ms, so the
adapter sets the resolution and nothing here can beat it. A technician flexing
a cable usually produces far longer breaks than that, which is why this is
useful, but **"no dropouts found" must never be allowed to read as "this cable
is sound"**. That distinction is the difference between a useful instrument and
a dangerous one.

**And the trap that distinction hides.** A monitor that reports change from a
baseline says nothing at all about a conductor that was ALREADY open when the
baseline was taken. Watching a dead line produces a clean run, and a clean run
reads as a good cable. So the baseline is checked before the watch begins: if
there is nothing alive to watch the monitor refuses to start, and anything
already open at rest is carried through to the verdict rather than silently
becoming the reference. See ``_baseline_finding``.
"""

from __future__ import annotations

import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

try:  # POSIX only; absent on Windows, where the slow path is used instead.
    import fcntl
    import termios
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    termios = None

from . import ethernet_tests, serial_tests

#: Pause between samples. Deliberately tiny: the limit that matters is how fast
#: the kernel will answer, not a number chosen here, and a flex-induced break
#: can be a few milliseconds. Small enough to sample hard, non-zero so the loop
#: cannot spin a core flat and starve the very USB stack it is reading.
SERIAL_POLL_S = 0.0005
ETH_POLL_S = 0.02

#: How often to tell the UI the monitor is alive and how fast it is going. A
#: clean run produces no events at all, and a screen with nothing moving on it
#: reads as an instrument that has hung. BOTH monitors emit this. The ethernet
#: one not emitting it was indistinguishable, on screen, from a dead instrument.
TICK_S = 0.4

#: Settle before taking the baseline, so the lines are steady before anything
#: is called a change.
BASELINE_SETTLE_S = 0.35

#: Floor on what any of this can see, whatever the loop achieves. A USB-serial
#: adapter reports modem line changes on an interrupt endpoint it polls every 1
#: to 10 ms, so the adapter sets the resolution and no amount of sampling here
#: beats it. The measured rate is reported alongside, and the WORSE of the two
#: is what the verdict quotes: claiming the loop's resolution would be claiming
#: to see something the hardware never delivered.
SERIAL_ADAPTER_FLOOR_MS = 10.0
ETH_RESOLUTION_MS = 50.0

#: The lines a loopback plug should hold steady once DTR and RTS are asserted.
WATCHED = ["cts", "dsr", "cd"]
LINE_LABEL = {"cts": "CTS", "dsr": "DSR", "cd": "DCD", "ri": "RI"}

#: The data path, watched alongside the handshake lines.
#:
#: Without this a 3-wire cable has nothing to monitor at all: pins 2, 3 and 5
#: are the only conductors it has, and none of them is a modem line. The
#: monitor would hold three dead handshake lines under watch, see nothing
#: change, and report a clean run on a cable it never touched.
DATA_LINE = "Data"

#: Baud for the data probe. Low on purpose: this is a continuity test, not a
#: speed test, and a slow rate is the one most tolerant of a marginal cable.
#: A conductor that is intact carries 9600 baud through anything.
DATA_PROBE_BAUD = 9600

#: One probe byte every this often. Far slower than the modem-line poll,
#: because a round trip through a USB-serial adapter costs milliseconds and
#: probing harder would buy resolution the adapter cannot deliver anyway.
DATA_PROBE_S = 0.02

#: How long the probe must go unanswered before the data path is called open.
#:
#: This is much larger than the modem-line floor and deliberately so. A USB
#: adapter coalesces and buffers, and a scheduler hiccup on the Pi can stall a
#: round trip for tens of milliseconds. Anything under this figure is latency,
#: not a fault, and calling it a fault would put the instrument's worst failure
#: mode on screen: a confident finding about a cable that is fine.
DATA_OPEN_MS = 150.0

#: How long to wait for the first probe byte to come back, before deciding the
#: data path is not connected at all.
DATA_BASELINE_WAIT_S = 0.3

#: Which DB9 pin each line arrives on. A technician repairs a pin, not a
#: signal name, so every finding names the conductor they have to go and look
#: at rather than leaving them to translate it. The data path is two pins
#: because a failure of either looks identical through a loopback.
LINE_PINS = {"CTS": [8], "DSR": [6], "DCD": [1], "RI": [9], DATA_LINE: [2, 3]}

#: Single-pin view of the same table, for the lines that have exactly one.
LINE_PIN = {name: pins[0] for name, pins in LINE_PINS.items() if len(pins) == 1}

_TIOCM_BIT = {}
if termios is not None:
    _TIOCM_BIT = {"cts": termios.TIOCM_CTS, "dsr": termios.TIOCM_DSR,
                  "cd": termios.TIOCM_CAR, "ri": termios.TIOCM_RNG}
_TIOCM_ZERO = struct.pack("I", 0)


class NothingToWatch(serial_tests.CableTesterError):
    """Raised when the baseline has no live conductor in it.

    Its own class rather than a bare error because it is not a failure of the
    instrument and not a verdict on the cable. It means the test cannot begin,
    and the fix is in the technician's hands.
    """

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def _sampler(ser):
    """Return a function giving every watched line from ONE syscall.

    pyserial reads each line with its own ``TIOCMGET`` ioctl, so asking for
    three lines costs three syscalls for data that arrives in one, and samples
    them at three different instants. That skew is not academic: a brief break
    that opens and closes between two of the reads is seen on one line and
    missed on the other, and the timestamps disagree about when it happened.

    One ioctl fixes both. The fallback is for the simulator and for Windows,
    where the slower, skewed path is the only one available.
    """
    fd = None
    if fcntl is not None and termios is not None:
        try:
            fd = ser.fileno()
        except Exception:
            fd = None

    if fd is None:
        return lambda: {name: bool(getattr(ser, name)) for name in WATCHED}

    def read_all():
        bits = struct.unpack("I", fcntl.ioctl(fd, termios.TIOCMGET, _TIOCM_ZERO))[0]
        return {name: bool(bits & _TIOCM_BIT[name]) for name in WATCHED}

    return read_all


def _now_ms(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


# --------------------------------------------------------------------------
# The data path
# --------------------------------------------------------------------------

class _DataProbe:
    """Keeps one byte in flight through pins 2 and 3, and times the silence.

    Not a throughput measurement. It asks one question continuously: is the
    data pair still joined? A byte goes out on a cadence and the echo resets a
    clock; when that clock passes ``DATA_OPEN_MS`` the pair is open, and it
    closes again the moment a byte returns.

    Every port operation is wrapped, because this has to survive a port that
    cannot do data at all. The test fakes are modem-line-only by design, and a
    monitor that crashed on them would be a monitor nobody could test.
    """

    #: A byte with transitions in both directions, so a conductor stuck at a
    #: level cannot echo it back by accident.
    MARKER = b"\x5a"

    def __init__(self, ser):
        self.ser = ser
        self.supported = False
        self.echoing = False
        self.last_echo = 0.0
        self.open_since: Optional[float] = None
        self._next = 0.0

    def _drain(self) -> int:
        """Read whatever has arrived. Returns how many bytes came back."""
        try:
            waiting = self.ser.in_waiting
        except Exception:
            return 0
        if not waiting:
            return 0
        try:
            return len(self.ser.read(waiting))
        except Exception:
            return 0

    def _send(self) -> bool:
        try:
            self.ser.write(self.MARKER)
            return True
        except Exception:
            return False

    def start(self, started: float) -> bool:
        """Probe once at baseline. Returns True if the data pair answered.

        ``supported`` is set separately: a port that cannot write at all is not
        a cable with an open data pair, it is a port this probe does not apply
        to, and conflating the two would report a fault on the test fakes.
        """
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        if not self._send():
            return False
        self.supported = True
        deadline = time.monotonic() + DATA_BASELINE_WAIT_S
        while time.monotonic() < deadline:
            if self._drain():
                self.echoing = True
                self.last_echo = time.monotonic()
                self._next = self.last_echo + DATA_PROBE_S
                return True
            time.sleep(0.002)
        return False

    def poll(self, started: float) -> Optional[dict]:
        """Advance the probe. Returns a completed event, or None.

        Called from the modem-line loop, so it must be cheap and must never
        block: it does its own cadence and returns immediately when not due.
        """
        if not (self.supported and self.echoing):
            return None
        now = time.monotonic()
        if self._drain():
            self.last_echo = now
            if self.open_since is not None:
                began = self.open_since
                self.open_since = None
                return {
                    "line": DATA_LINE,
                    "at_ms": round(began, 1),
                    "duration_ms": round(_now_ms(started) - began, 1),
                }
            return None
        if now >= self._next:
            self._next = now + DATA_PROBE_S
            self._send()
        silent_ms = (now - self.last_echo) * 1000.0
        if silent_ms >= DATA_OPEN_MS and self.open_since is None:
            # Backdate to when the silence began, not to when it was noticed.
            # Quoting the moment of detection would inflate every duration by
            # the whole threshold and make short breaks look long.
            self.open_since = _now_ms(started) - silent_ms
        return None

    def unfinished(self, started: float) -> Optional[dict]:
        if self.open_since is None:
            return None
        return {"line": DATA_LINE, "at_ms": round(self.open_since, 1),
                "duration_ms": None, "still_open": True}

    @property
    def is_open(self) -> bool:
        return self.open_since is not None


# --------------------------------------------------------------------------
# The serial monitor
# --------------------------------------------------------------------------

def _baseline_finding(baseline: Dict[str, bool], probe: _DataProbe
                      ) -> Tuple[List[str], List[str], List[str]]:
    """Split the cable's resting state into alive, faulty, and simply not fitted.

    The baseline stays what it always was: whatever this cable does at rest,
    not what a correct cable would do. What changes is that a line resting in
    the open state is now REPORTED as such rather than quietly becoming the
    reference, because a monitor watching a dead conductor sees nothing change
    and a run that sees nothing change reads as a good cable.

    The third list is the distinction that keeps this honest, and it is the
    same one the pin check draws in ``serial_tests._expected_absent``: a cable
    with NO handshake conductors is a 3-wire cable, a valid type, and its
    missing lines are not a fault. A cable with SOME of them is a
    full-handshake cable with a broken conductor in it. All three absent is a
    cable type; two of three absent is a fault. Grading a 3-wire cable as
    faulty here would contradict the pin check, which passes it.
    """
    alive = [LINE_LABEL[k] for k in WATCHED if baseline.get(k)]
    dead = [LINE_LABEL[k] for k in WATCHED if not baseline.get(k)]
    not_fitted: List[str] = []
    if probe.supported:
        (alive if probe.echoing else dead).append(DATA_LINE)
    if probe.echoing and len(dead) == len(WATCHED):
        # Every handshake line absent and the data pair carrying: 3-wire.
        not_fitted, dead = dead, []
    return alive, dead, not_fitted


def _nothing_to_watch(dead: List[str]) -> NothingToWatch:
    named = ", ".join(dead)
    return NothingToWatch(
        "Nothing is connected to watch.",
        f"Every conductor reads open at rest ({named}), so there is nothing "
        f"here that could be seen to change. The usual cause is the loopback "
        f"plug not being fitted, or an end not seated. Fit the plug to the far "
        f"end of the cable, check both connectors are home, then start again.",
    )


def run_serial_monitor(
    device: str,
    emit: Callable[[str, dict], None] = serial_tests._noop,
    cancel: Optional[threading.Event] = None,
    serial_factory=None,
) -> dict:
    """Hold DTR and RTS asserted and watch every conductor until cancelled.

    Runs until the technician stops it. There is no duration: the test is over
    when they have finished working the cable, and only they know when that is.
    """
    started = time.monotonic()
    events: List[dict] = []
    ser = None
    baseline: Dict[str, bool] = {}
    samples = 0
    alive: List[str] = []
    dead: List[str] = []
    not_fitted: List[str] = []
    probe = None

    try:
        ser = serial_tests.open_serial(
            device, baudrate=DATA_PROBE_BAUD, timeout=0, serial_factory=serial_factory
        )
        ser.dtr = True
        ser.rts = True
        time.sleep(BASELINE_SETTLE_S)

        sample = _sampler(ser)

        # The baseline is whatever this cable does when still, not what a
        # correct cable would do. A 3-wire cable holds its handshake lines low
        # and that is not a fault; a change from its own resting state is.
        baseline = sample()
        probe = _DataProbe(ser)
        probe.start(started)
        alive, dead, not_fitted = _baseline_finding(baseline, probe)

        # Refusing is the whole point. Watching a cable with no live conductor
        # in it produces a clean run, and a clean run reads as a good cable.
        if not alive:
            raise _nothing_to_watch(dead)

        emit("mon_baseline", {
            "lines": {LINE_LABEL[k]: v for k, v in baseline.items()},
            "resolution_ms": SERIAL_ADAPTER_FLOOR_MS,
            "watching": alive,
            "dead_at_start": dead,
            "not_fitted": not_fitted,
        })

        current = dict(baseline)
        open_since = {}
        next_tick = time.monotonic() + TICK_S

        while cancel is None or not cancel.is_set():
            now = sample()
            samples += 1
            for name in WATCHED:
                value = now[name]
                if value == current[name]:
                    continue
                current[name] = value
                at = _now_ms(started)
                if value != baseline[name]:
                    open_since[name] = at
                else:
                    # Back to rest: a dropout with a measurable length.
                    began = open_since.pop(name, at)
                    event = {
                        "line": LINE_LABEL[name],
                        "at_ms": round(began, 1),
                        "duration_ms": round(at - began, 1),
                    }
                    events.append(event)
                    emit("mon_event", event)

            data_event = probe.poll(started)
            if data_event is not None:
                events.append(data_event)
                emit("mon_event", data_event)

            clock = time.monotonic()
            if clock >= next_tick:
                next_tick = clock + TICK_S
                elapsed = clock - started
                open_now = sorted(LINE_LABEL[k] for k in open_since)
                if probe.is_open:
                    open_now.append(DATA_LINE)
                emit("mon_tick", {
                    "at_ms": round(elapsed * 1000.0, 1),
                    "samples": samples,
                    "rate_hz": round(samples / elapsed, 1) if elapsed > 0 else 0,
                    "dropouts": len(events),
                    "open_now": open_now,
                })
            time.sleep(SERIAL_POLL_S)

        # A line still away from rest when the tech stops is a dropout that has
        # not ended. Recording it open-ended is more honest than dropping it.
        for name, began in open_since.items():
            event = {"line": LINE_LABEL[name], "at_ms": round(began, 1),
                     "duration_ms": None, "still_open": True}
            events.append(event)
            emit("mon_event", event)
        trailing = probe.unfinished(started)
        if trailing is not None:
            events.append(trailing)
            emit("mon_event", trailing)

    except serial_tests.CableTesterError:
        raise
    finally:
        # The port is always closed, including on the cancel path and on the
        # refusal path above. This monitor is the longest-running thing the
        # instrument does and the most likely to be interrupted.
        serial_tests._close_quietly(ser)

    return _summarise(
        "serial", device, started, events, samples, SERIAL_ADAPTER_FLOOR_MS,
        {LINE_LABEL[k]: v for k, v in baseline.items()},
        watching=alive, dead_at_start=dead, not_fitted=not_fitted,
        extra={"data_resolution_ms": DATA_OPEN_MS if probe and probe.supported else None},
    )


# --------------------------------------------------------------------------
# The ethernet monitor
# --------------------------------------------------------------------------

#: Both ends are watched, not just the near one. A break in the pair carrying
#: one direction produces a one-way link: the end with no signal coming in
#: drops carrier while the other end can still hold it. Watching a single
#: interface sees that fault only half the time, and which half is luck.
ETH_LINES = {"a": "Link A", "b": "Link B"}
ETH_SPEED_LINE = "Speed"


def run_eth_monitor(
    iface_a: str,
    iface_b: str,
    emit: Callable[[str, dict], None] = serial_tests._noop,
    cancel: Optional[threading.Event] = None,
) -> dict:
    """Watch the link between two ports until cancelled.

    Autonegotiation is left alone: this watches whatever speed the cable
    settled on, because a cable that drops its gigabit link when flexed is the
    finding, and forcing a lower rung would hide it.

    **Speed is watched, not only carrier.** A pair that opens under flex does
    not usually drop the link. 1000BASE-T needs all four pairs and 100BASE-TX
    needs two, so losing the blue or brown pair renegotiates the link down to
    100Mb with carrier held up throughout. Watching carrier alone sees a
    perfectly steady link and reports the cable clean, which is precisely the
    fault this instrument exists to catch.
    """
    started = time.monotonic()
    events: List[dict] = []
    samples = 0

    for iface in (iface_a, iface_b):
        ethernet_tests._validate(iface)
        if ethernet_tests.carries_default_route(iface):
            raise ethernet_tests.EthernetTestError(
                f"'{iface}' carries this box's default route.")

    base_a = ethernet_tests.link_state(iface_a)
    base_b = ethernet_tests.link_state(iface_b)

    # Same refusal as the serial side, for the same reason: with the link
    # already down there is nothing that can be seen to drop, so the run would
    # end clean on a cable that never carried a packet.
    if not base_a["link"] or not base_b["link"]:
        down = [name for name, st in ((iface_a, base_a), (iface_b, base_b))
                if not st["link"]]
        raise NothingToWatch(
            "There is no link to watch.",
            f"No carrier on {' and '.join(down)}, so nothing here could be seen "
            f"to drop. Run the cable between both panel ports, check each plug "
            f"clicks home, and give the ports a few seconds to negotiate. Then "
            f"start again.",
        )

    base_speed = base_a["speed"] or base_b["speed"]
    emit("mon_baseline", {
        "lines": {ETH_LINES["a"]: base_a["link"], ETH_LINES["b"]: base_b["link"],
                  ETH_SPEED_LINE: f"{base_speed}Mb/s" if base_speed else "unknown"},
        "resolution_ms": ETH_RESOLUTION_MS,
        "watching": [ETH_LINES["a"], ETH_LINES["b"]] + ([ETH_SPEED_LINE] if base_speed else []),
        "dead_at_start": [],
        "ends": {"a": iface_a, "b": iface_b},
        "baseline_speed": base_speed,
    })

    up = {"a": True, "b": True}
    down_at: Dict[str, float] = {}
    slow_since: Optional[float] = None
    next_tick = time.monotonic() + TICK_S

    def close_event(line: str, began: float) -> dict:
        event = {"line": line, "at_ms": round(began, 1),
                 "duration_ms": round(_now_ms(started) - began, 1)}
        events.append(event)
        emit("mon_event", event)
        return event

    while cancel is None or not cancel.is_set():
        samples += 1
        now = {"a": ethernet_tests.link_state(iface_a),
               "b": ethernet_tests.link_state(iface_b)}

        for end in ("a", "b"):
            linked = now[end]["link"]
            if linked == up[end]:
                continue
            up[end] = linked
            if not linked:
                down_at[end] = _now_ms(started)
            else:
                close_event(ETH_LINES[end], down_at.pop(end, _now_ms(started)))

        # Only meaningful while both ends hold carrier. A speed read on a dead
        # link is the configured value echoed back, not a measurement.
        if base_speed and up["a"] and up["b"]:
            speed = now["a"]["speed"] or now["b"]["speed"]
            if speed and speed < base_speed:
                if slow_since is None:
                    slow_since = _now_ms(started)
            elif slow_since is not None:
                event = close_event(ETH_SPEED_LINE, slow_since)
                event["from"] = base_speed
                event["to"] = speed
                slow_since = None

        clock = time.monotonic()
        if clock >= next_tick:
            next_tick = clock + TICK_S
            elapsed = clock - started
            open_now = [ETH_LINES[end] for end in ("a", "b") if not up[end]]
            if slow_since is not None:
                open_now.append(ETH_SPEED_LINE)
            emit("mon_tick", {
                "at_ms": round(elapsed * 1000.0, 1),
                "samples": samples,
                "rate_hz": round(samples / elapsed, 1) if elapsed > 0 else 0,
                "dropouts": len(events),
                "open_now": open_now,
                "speed": now["a"]["speed"] or now["b"]["speed"],
            })
        time.sleep(ETH_POLL_S)

    for end, began in down_at.items():
        event = {"line": ETH_LINES[end], "at_ms": round(began, 1),
                 "duration_ms": None, "still_open": True}
        events.append(event)
        emit("mon_event", event)
    if slow_since is not None:
        last = ethernet_tests.link_state(iface_a)
        event = {"line": ETH_SPEED_LINE, "at_ms": round(slow_since, 1),
                 "duration_ms": None, "still_open": True,
                 "from": base_speed, "to": last["speed"]}
        events.append(event)
        emit("mon_event", event)

    return _summarise(
        "ethernet", f"{iface_a} to {iface_b}", started, events, samples,
        ETH_RESOLUTION_MS,
        {ETH_LINES["a"]: base_a["link"], ETH_LINES["b"]: base_b["link"]},
        watching=[ETH_LINES["a"], ETH_LINES["b"]], dead_at_start=[],
        extra={"ends": {"a": iface_a, "b": iface_b}, "baseline_speed": base_speed},
    )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _summarise(kind, subject, started, events, samples, floor_ms, baseline,
               watching=None, dead_at_start=None, not_fitted=None, extra=None) -> dict:
    elapsed = time.monotonic() - started
    rate = (samples / elapsed) if elapsed > 0 else 0.0
    # The honest resolution is the WORSE of what the loop managed and what the
    # hardware can deliver. Quoting the loop's figure would claim to see
    # something the adapter never reported.
    loop_ms = (1000.0 / rate) if rate > 0 else float("inf")
    resolution_ms = max(floor_ms, loop_ms)
    dead_at_start = dead_at_start or []
    not_fitted = not_fitted or []
    result = {
        "type": "continuity",
        "protocol": kind,
        "subject": subject,
        "elapsed_s": round(elapsed, 1),
        "samples": samples,
        "events": events,
        "dropouts": len(events),
        "baseline": baseline,
        "watching": watching or [],
        "dead_at_start": dead_at_start,
        # Conductors this cable simply does not have, as opposed to conductors
        # it has and has broken. A 3-wire cable is the whole reason these are
        # two different lists and not one.
        "not_fitted": not_fitted,
        "resolution_ms": round(resolution_ms, 1),
        "sample_rate_hz": round(rate, 1),
        "loop_resolution_ms": round(loop_ms, 2) if rate > 0 else None,
        "verdict": verdict_text(events, elapsed, resolution_ms, dead_at_start,
                                not_fitted),
        "affected_pins": affected_pins(events, dead_at_start),
        "by_line": _by_line(events),
        # A conductor that was already open when the watch began is a fault the
        # run found, even though it produced no event. Reporting it as a pass
        # because nothing CHANGED is how a broken cable leaves the bench.
        "passed": len(events) == 0 and not dead_at_start,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    result.update(extra or {})
    return result


def _by_line(events: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in events:
        out[e["line"]] = out.get(e["line"], 0) + 1
    return out


def _name_with_pins(line: str) -> str:
    """Name a conductor the way a technician has to go and look at it.

    Pins are appended only where they exist. The ethernet lines have none, and
    an earlier version reached for the same table regardless and produced
    findings reading "Link (pin ?)", which looks like the instrument having
    lost track of what it was measuring.
    """
    pins = LINE_PINS.get(line)
    if not pins:
        return line
    label = "pin" if len(pins) == 1 else "pins"
    return f"{line} ({label} {' and '.join(str(p) for p in pins)})"


def verdict_text(events: List[dict], elapsed: float, resolution_ms: float,
                 dead_at_start: Optional[List[str]] = None,
                 not_fitted: Optional[List[str]] = None) -> str:
    """Name the conductor, then say what to do about it.

    "Condemn it" was the wrong ending: a technician's next move is to repair
    the cable or bin it, and which one depends on whether it is worth their
    time. The instrument reports the fault and the choice stays theirs.
    """
    dead_at_start = dead_at_start or []
    not_fitted = not_fitted or []
    counts: Dict[str, int] = {}
    for e in events:
        counts[e["line"]] = counts.get(e["line"], 0) + 1

    parts: List[str] = []

    if dead_at_start:
        named = ", ".join(_name_with_pins(line) for line in dead_at_start)
        parts.append(
            f"Open before the cable was even moved: {named}. "
            f"{'That conductor was' if len(dead_at_start) == 1 else 'Those conductors were'} "
            f"already broken at rest, so nothing about "
            f"{'it' if len(dead_at_start) == 1 else 'them'} was under test here."
        )

    # A speed drop is not a broken conductor and must not be worded as one. It
    # is a pair opening under a link that never went down, which is a different
    # finding with a different repair, so it gets its own sentence rather than
    # being counted alongside the conductors.
    conductors = {line: n for line, n in counts.items() if line != ETH_SPEED_LINE}
    speed_drops = [e for e in events if e["line"] == ETH_SPEED_LINE]

    if conductors:
        named = ", ".join(
            f"{_name_with_pins(line)} {n} time{'s' if n != 1 else ''}"
            for line, n in sorted(conductors.items(), key=lambda kv: -kv[1])
        )
        parts.append(
            f"Open while being flexed: {named}. "
            f"{'That conductor is' if len(conductors) == 1 else 'Those conductors are'} broken "
            f"or badly terminated and the cable will fail in service. "
            f"Repair the end{'s' if len(conductors) > 1 else ''}, or throw the cable away."
        )

    if speed_drops:
        drop = speed_drops[0]
        fell_from = drop.get("from")
        fell_to = drop.get("to")
        held = "and it stayed there" if drop.get("still_open") else "and recovered"
        where = (f"from {fell_from}Mb to {fell_to}Mb" if fell_from and fell_to
                 else "to a lower speed")
        parts.append(
            f"The link fell {where} while the cable was moved, {held}. The carrier "
            f"never dropped, so this is one pair opening rather than the whole "
            f"cable breaking: gigabit needs all four pairs and 100Mb needs only "
            f"the orange and green. Look at the blue and brown pairs, pins 4, 5, "
            f"7 and 8."
        )

    if not parts:
        mins = elapsed / 60.0
        how_long = f"{elapsed:.0f} seconds" if mins < 1 else f"{mins:.0f} minutes"
        clean = (
            f"No opens in {how_long} of flexing. That is not proof the cable is "
            f"sound: breaks shorter than about {resolution_ms:.0f} ms are invisible "
            f"to this test, and a fault only shows if the cable was moved where it "
            f"is damaged."
        )
        if not_fitted:
            # Saying what was NOT under watch matters more on a clean run than
            # on a dirty one. "No opens" over a cable where two thirds of the
            # conductors were never being watched is the instrument overstating
            # what it looked at.
            clean += (
                f" This is a 3-wire cable, so only the data pair (pins 2 and 3) "
                f"was under watch. It has no handshake conductors to break."
            )
        return clean
    return " ".join(parts)


def affected_pins(events: List[dict],
                  dead_at_start: Optional[List[str]] = None) -> List[int]:
    """DB9 pins to light up on the diagram.

    Includes anything already open at the baseline. A pin that was dead before
    the watch started is exactly the pin a technician needs pointed out, and
    leaving it off the diagram because it produced no event would highlight
    nothing on a cable with a broken conductor in it.
    """
    pins = set()
    for line in [e["line"] for e in events] + list(dead_at_start or []):
        pins.update(LINE_PINS.get(line, []))
    return sorted(pins)
