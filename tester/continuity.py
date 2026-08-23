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

import threading
import time
from typing import Callable, Dict, List, Optional

from . import ethernet_tests, serial_tests

#: How often to sample. Fast enough to catch a flex-induced break, slow enough
#: not to saturate a USB bus that the serial test also depends on.
SERIAL_POLL_S = 0.005
ETH_POLL_S = 0.05

#: Settle before taking the baseline, so the lines are steady before anything
#: is called a change.
BASELINE_SETTLE_S = 0.35

#: Below this, the honest answer is that the adapter, not the cable, decided
#: what was visible. Reported with the result so the UI can say so.
SERIAL_RESOLUTION_MS = 10.0
ETH_RESOLUTION_MS = 50.0

#: The lines a loopback plug should hold steady once DTR and RTS are asserted.
WATCHED = ["cts", "dsr", "cd"]
LINE_LABEL = {"cts": "CTS", "dsr": "DSR", "cd": "DCD", "ri": "RI"}


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

        # The baseline is whatever this cable does when still, not what a
        # correct cable would do. A 3-wire cable holds its handshake lines low
        # and that is not a fault; a change from its own resting state is.
        baseline = {name: bool(getattr(ser, name)) for name in WATCHED}
        emit("mon_baseline", {
            "lines": {LINE_LABEL[k]: v for k, v in baseline.items()},
            "resolution_ms": SERIAL_RESOLUTION_MS,
        })

        current = dict(baseline)
        open_since: Dict[str, float] = {}

        while cancel is None or not cancel.is_set():
            samples += 1
            for name in WATCHED:
                value = bool(getattr(ser, name))
                if value == current[name]:
                    continue
                current[name] = value
                at = _now_ms(started)
                if value != baseline[name]:
                    open_since[name] = at
                else:
                    # Back to rest: this was a dropout with a measurable length.
                    began = open_since.pop(name, at)
                    event = {
                        "line": LINE_LABEL[name],
                        "at_ms": round(began, 1),
                        "duration_ms": round(at - began, 1),
                    }
                    events.append(event)
                    emit("mon_event", event)
            time.sleep(SERIAL_POLL_S)

        # A line still away from rest when the tech stops is a dropout that has
        # not ended. Recording it as open-ended is more honest than dropping it.
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
                      SERIAL_RESOLUTION_MS,
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


def _summarise(kind, subject, started, events, samples, resolution_ms, baseline) -> dict:
    elapsed = time.monotonic() - started
    return {
        "type": "continuity",
        "protocol": kind,
        "subject": subject,
        "elapsed_s": round(elapsed, 1),
        "samples": samples,
        "events": events,
        "dropouts": len(events),
        "baseline": baseline,
        "resolution_ms": resolution_ms,
        "verdict": verdict_text(len(events), elapsed, resolution_ms),
        "passed": len(events) == 0,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def verdict_text(dropouts: int, elapsed: float, resolution_ms: float) -> str:
    """Deliberately refuses to call a clean run a pass.

    A monitor that saw nothing has only established that nothing happened
    while it was watching, at the resolution it could watch. Saying more than
    that would be the instrument overstating what it knows, on the one test
    whose whole purpose is catching what other tests miss.
    """
    if dropouts:
        word = "dropout" if dropouts == 1 else "dropouts"
        return (
            f"{dropouts} {word} while the cable was being worked. "
            f"This cable will fail in service. Condemn it."
        )
    mins = elapsed / 60.0
    how_long = f"{elapsed:.0f} seconds" if mins < 1 else f"{mins:.0f} minutes"
    return (
        f"No dropouts in {how_long} of flexing. That is not proof the cable is "
        f"sound: breaks shorter than about {resolution_ms:.0f} ms are invisible "
        f"to this test, and a fault only shows if the cable was moved where it "
        f"is damaged."
    )
