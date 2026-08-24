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
"""

from __future__ import annotations

import struct
import threading
import time
from typing import Callable, Dict, List, Optional

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
#: reads as an instrument that has hung.
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

#: Which DB9 pin each line arrives on. A technician repairs a pin, not a
#: signal name, so every finding names the conductor they have to go and look
#: at rather than leaving them to translate it.
LINE_PIN = {"CTS": 8, "DSR": 6, "DCD": 1, "RI": 9}

_TIOCM_BIT = {}
if termios is not None:
    _TIOCM_BIT = {"cts": termios.TIOCM_CTS, "dsr": termios.TIOCM_DSR,
                  "cd": termios.TIOCM_CAR, "ri": termios.TIOCM_RNG}
_TIOCM_ZERO = struct.pack("I", 0)


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


def run_serial_monitor(
    device: str,
    emit: Callable[[str, dict], None] = serial_tests._noop,
    cancel: Optional[threading.Event] = None,
    serial_factory=None,
) -> dict:
    """Hold DTR and RTS asserted and watch the inputs until cancelled.

    Runs until the technician stops it. There is no duration: the test is over
    when they have finished working the cable, and only they know when that is.
    """
    started = time.monotonic()
    events: List[dict] = []
    ser = None
    baseline: Dict[str, bool] = {}
    samples = 0

    try:
        ser = serial_tests.open_serial(
            device, baudrate=9600, timeout=0, serial_factory=serial_factory
        )
        ser.dtr = True
        ser.rts = True
        time.sleep(BASELINE_SETTLE_S)

        sample = _sampler(ser)

        # The baseline is whatever this cable does when still, not what a
        # correct cable would do. A 3-wire cable holds its handshake lines low
        # and that is not a fault; a change from its own resting state is.
        baseline = sample()
        emit("mon_baseline", {
            "lines": {LINE_LABEL[k]: v for k, v in baseline.items()},
            "resolution_ms": SERIAL_ADAPTER_FLOOR_MS,
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

            clock = time.monotonic()
            if clock >= next_tick:
                next_tick = clock + TICK_S
                elapsed = clock - started
                emit("mon_tick", {
                    "at_ms": round(elapsed * 1000.0, 1),
                    "samples": samples,
                    "rate_hz": round(samples / elapsed, 1) if elapsed > 0 else 0,
                    "dropouts": len(events),
                    "open_now": sorted(LINE_LABEL[k] for k in open_since),
                })
            time.sleep(SERIAL_POLL_S)

        # A line still away from rest when the tech stops is a dropout that has
        # not ended. Recording it open-ended is more honest than dropping it.
        for name, began in open_since.items():
            event = {"line": LINE_LABEL[name], "at_ms": round(began, 1),
                     "duration_ms": None, "still_open": True}
            events.append(event)
            emit("mon_event", event)

    except serial_tests.CableTesterError:
        raise
    finally:
        # The port is always closed, including on the cancel path. This monitor
        # is the longest-running thing the instrument does and the most likely
        # to be interrupted.
        serial_tests._close_quietly(ser)

    return _summarise("serial", device, started, events, samples,
                      SERIAL_ADAPTER_FLOOR_MS,
                      {LINE_LABEL[k]: v for k, v in baseline.items()})


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
    """
    started = time.monotonic()
    events: List[dict] = []
    samples = 0

    for iface in (iface_a, iface_b):
        ethernet_tests._validate(iface)
        if ethernet_tests.carries_default_route(iface):
            raise ethernet_tests.EthernetTestError(
                f"'{iface}' carries this box's default route.")

    baseline = ethernet_tests.link_state(iface_a)
    emit("mon_baseline", {
        "lines": {"Link": baseline["link"],
                  "Speed": f"{baseline['speed']}Mb/s" if baseline["speed"] else "none"},
        "resolution_ms": ETH_RESOLUTION_MS,
    })

    up = baseline["link"]
    down_at: Optional[float] = None

    while cancel is None or not cancel.is_set():
        samples += 1
        now = ethernet_tests.link_state(iface_a)
        if now["link"] != up:
            up = now["link"]
            at = _now_ms(started)
            if not up:
                down_at = at
            else:
                began = down_at if down_at is not None else at
                down_at = None
                event = {"line": "Link", "at_ms": round(began, 1),
                         "duration_ms": round(at - began, 1)}
                events.append(event)
                emit("mon_event", event)
        time.sleep(ETH_POLL_S)

    if down_at is not None:
        event = {"line": "Link", "at_ms": round(down_at, 1),
                 "duration_ms": None, "still_open": True}
        events.append(event)
        emit("mon_event", event)

    return _summarise("ethernet", f"{iface_a} to {iface_b}", started, events, samples,
                      ETH_RESOLUTION_MS,
                      {"Link": baseline["link"]})


def _summarise(kind, subject, started, events, samples, floor_ms, baseline) -> dict:
    elapsed = time.monotonic() - started
    rate = (samples / elapsed) if elapsed > 0 else 0.0
    # The honest resolution is the WORSE of what the loop managed and what the
    # hardware can deliver. Quoting the loop's figure would claim to see
    # something the adapter never reported.
    loop_ms = (1000.0 / rate) if rate > 0 else float("inf")
    resolution_ms = max(floor_ms, loop_ms)
    return {
        "type": "continuity",
        "protocol": kind,
        "subject": subject,
        "elapsed_s": round(elapsed, 1),
        "samples": samples,
        "events": events,
        "dropouts": len(events),
        "baseline": baseline,
        "resolution_ms": round(resolution_ms, 1),
        "sample_rate_hz": round(rate, 1),
        "loop_resolution_ms": round(loop_ms, 2) if rate > 0 else None,
        "verdict": verdict_text(events, elapsed, resolution_ms),
        "affected_pins": affected_pins(events),
        "by_line": _by_line(events),
        "passed": len(events) == 0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _by_line(events: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in events:
        out[e["line"]] = out.get(e["line"], 0) + 1
    return out


def verdict_text(events: List[dict], elapsed: float, resolution_ms: float) -> str:
    """Name the conductor, then say what to do about it.

    "Condemn it" was the wrong ending: a technician's next move is to repair
    the cable or bin it, and which one depends on whether it is worth their
    time. The instrument reports the fault and the choice stays theirs.
    """
    if not events:
        mins = elapsed / 60.0
        how_long = f"{elapsed:.0f} seconds" if mins < 1 else f"{mins:.0f} minutes"
        return (
            f"No opens in {how_long} of flexing. That is not proof the cable is "
            f"sound: breaks shorter than about {resolution_ms:.0f} ms are invisible "
            f"to this test, and a fault only shows if the cable was moved where it "
            f"is damaged."
        )

    counts: Dict[str, int] = {}
    for e in events:
        counts[e["line"]] = counts.get(e["line"], 0) + 1
    named = ", ".join(
        f"{line} (pin {LINE_PIN.get(line, '?')}) {n} time{'s' if n != 1 else ''}"
        for line, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    total = len(events)
    return (
        f"Open while being flexed: {named}. "
        f"{'That conductor is' if len(counts) == 1 else 'Those conductors are'} broken "
        f"or badly terminated and the cable will fail in service. "
        f"Repair the end{'s' if len(counts) > 1 else ''}, or throw the cable away."
    ) if total else ""


def affected_pins(events: List[dict]) -> List[int]:
    """DB9 pins to light up on the diagram."""
    pins = {LINE_PIN.get(e["line"]) for e in events}
    return sorted(p for p in pins if p)
