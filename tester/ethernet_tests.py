"""Ethernet cable testing: the link-speed ladder.

The serial sweep walks baud rates and finds where a cable gives up.  This is
the same idea one layer down: it walks link speeds between two ethernet ports
with the cable under test strung between them, and reports which ones come up.

That is diagnostic rather than a benchmark, because the speeds use different
pairs.  10 and 100BASE-T need only pairs 1-2 and 3-6; 1000BASE-T needs all
four.  So "links at 100 but not at 1000" localises the fault to the blue and
brown pairs without any reflectometry, which matters because ``--cable-test``
is unsupported on both chips in the kit.

Three things were established on real hardware (DOC 12) and every one of them
shapes the code below:

1. **Gigabit cannot be forced.**  ``ethtool -s IF speed 1000 autoneg off`` is
   silently downgraded to 100Mb/s.  1000BASE-T *requires* autonegotiation,
   because the standard uses it to settle which end is master and which is
   slave for clock recovery, so a forced gigabit link does not exist.  The
   ladder restricts what is ADVERTISED instead and leaves autoneg on: offer
   one speed and the link either comes up at it or does not come up at all.

2. **Speed and duplex are meaningless while the link is down.**  ethtool
   echoes back the last configured value, which reads exactly like a
   negotiated result.  A probe run with the cable unplugged duly reported
   "10Mb/s Full".  Every read here is gated on ``Link detected: yes``.

3. **Autonegotiation is not instant**, least of all at gigabit.  Nothing waits
   a fixed interval; ``_settle`` polls.

**This is the only module that touches a network interface**, exactly as
``serial_tests`` is the only one that opens a port.  And like that module, it
puts the interfaces back in a ``finally``: a test that leaves an interface
advertising 10BASE-T alone has broken the box until someone notices.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from typing import Callable, Dict, List, Optional

# Autonegotiation advertisement masks, from the ethtool ABI.
ADV_10_FULL = 0x002
ADV_100_FULL = 0x008
ADV_1000_FULL = 0x020
ADV_ALL = 0x03F

#: The ladder, slowest first.  ``pairs`` is what each speed physically needs,
#: and is the whole reason a failure at one rung localises the fault.
RUNGS: List[dict] = [
    {"speed": 10, "mask": ADV_10_FULL, "pairs": "1-2 and 3-6"},
    {"speed": 100, "mask": ADV_100_FULL, "pairs": "1-2 and 3-6"},
    {"speed": 1000, "mask": ADV_1000_FULL, "pairs": "all four"},
]

#: How long to wait for a link to come up before calling the rung failed.
#: Gigabit autonegotiation is the slow case.  Measured at well under this on
#: the kit, but adapters vary and the cost of being generous is only time on a
#: cable that was going to fail anyway.
LINK_TIMEOUT_S = 12.0
LINK_POLL_S = 0.5

#: Settling pause after an interface is reconfigured, before polling starts.
#: Without it the first poll can read the previous link state and report a
#: rung as passing on the strength of the rung before it.
RECONFIG_SETTLE_S = 1.0

_IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


class EthernetTestError(RuntimeError):
    """Raised for anything a technician should see rather than a stack trace."""


# --------------------------------------------------------------------------
# Shelling out to ethtool
# --------------------------------------------------------------------------

def _ethtool_path() -> str:
    path = shutil.which("ethtool")
    if not path:
        raise EthernetTestError(
            "ethtool is not installed. Run deploy/setup-pi.sh, or "
            "'sudo apt install ethtool'."
        )
    return path


def _run(args: List[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_ethtool_path()] + args,
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def _validate(iface: str) -> str:
    """Reject anything that is not a plausible interface name.

    Interface names reach here from an HTTP request and go into an argv, so
    they are validated rather than trusted.  There is no shell involved, but a
    name that is not an interface produces a confusing failure deep inside
    ethtool rather than a clear one here.
    """
    if not isinstance(iface, str) or not _IFACE_RE.match(iface):
        raise EthernetTestError(f"'{iface}' is not a valid interface name.")
    if not os.path.isdir(f"/sys/class/net/{iface}"):
        raise EthernetTestError(f"No network interface named '{iface}'.")
    return iface


# --------------------------------------------------------------------------
# Reading interface state
# --------------------------------------------------------------------------

def _sysfs(iface: str, name: str) -> str:
    try:
        with open(f"/sys/class/net/{iface}/{name}") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _driver(iface: str) -> str:
    out = _run(["-i", iface])
    for line in out.stdout.splitlines():
        if line.startswith("driver:"):
            return line.split(":", 1)[1].strip()
    return ""


def link_state(iface: str) -> dict:
    """Current link state.

    ``speed`` and ``duplex`` are None unless the link is actually up.  This is
    not defensiveness: with the link down ethtool reports the last value it was
    *configured* with, which is indistinguishable from a negotiated result and
    caused a probe run to report speeds for a cable that was not plugged in.
    """
    out = _run([iface])
    link = False
    speed: Optional[int] = None
    duplex: Optional[str] = None
    for raw in out.stdout.splitlines():
        line = raw.strip()
        if line.startswith("Link detected:"):
            link = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("Speed:"):
            m = re.search(r"(\d+)", line)
            if m:
                speed = int(m.group(1))
        elif line.startswith("Duplex:"):
            duplex = line.split(":", 1)[1].strip()
    if not link:
        return {"iface": iface, "link": False, "speed": None, "duplex": None}
    return {"iface": iface, "link": True, "speed": speed, "duplex": duplex}


def carries_default_route(iface: str) -> bool:
    """Is this interface the box's way out?

    Walking an interface through three advertisement changes drops its link at
    every rung.  Doing that to the route the technician arrived on ends the
    session mid-test and looks like the instrument crashing.
    """
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default", "dev", iface],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        # If the route cannot be determined, assume it is load bearing. The
        # failure mode of guessing wrong the other way is losing the network.
        return True


def list_interfaces() -> List[dict]:
    """Ethernet interfaces that could be used for a test.

    Wireless and loopback are excluded because neither can carry a cable, and
    anything holding the default route is reported but marked untestable.
    """
    found: List[dict] = []
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return found
    for name in names:
        if name == "lo" or os.path.isdir(f"/sys/class/net/{name}/wireless"):
            continue
        if os.path.exists(f"/sys/class/net/{name}/phy80211"):
            continue
        default_route = carries_default_route(name)
        state = link_state(name)
        found.append({
            "iface": name,
            "driver": _driver(name),
            "mac": _sysfs(name, "address"),
            "link": state["link"],
            "speed": state["speed"],
            "carries_default_route": default_route,
            "testable": not default_route,
            "note": "Carries the default route. Testing it would drop this box's network."
                    if default_route else "",
        })
    return found


# --------------------------------------------------------------------------
# Driving the ladder
# --------------------------------------------------------------------------

def _advertise(iface: str, mask: int) -> None:
    """Restrict what the interface offers, leaving autonegotiation on.

    Deliberately not 'speed N duplex full autoneg off'. See the module
    docstring: that cannot produce a gigabit link and is silently downgraded.
    """
    out = _run(["-s", iface, "autoneg", "on", "advertise", f"0x{mask:03x}"])
    if out.returncode != 0:
        err = (out.stderr or out.stdout).strip().splitlines()
        detail = err[0] if err else f"exit {out.returncode}"
        if "Operation not permitted" in detail or "permission" in detail.lower():
            raise EthernetTestError(
                f"Not permitted to reconfigure {iface}. The tester needs "
                f"CAP_NET_ADMIN; see deploy/cabletester.service."
            )
        raise EthernetTestError(f"Could not set the advertised speed on {iface}: {detail}")


def _settle(ifaces: List[str], timeout: Optional[float] = None,
            cancelled: Optional[Callable[[], bool]] = None) -> bool:
    """Poll until every interface reports link, or give up.

    Polls rather than sleeping a fixed interval because autonegotiation timing
    varies by chip and by speed, and a fixed wait is either too short (a good
    cable reported as failed) or wastes time on every rung.
    """
    # Resolved here, not in the signature. A default argument is evaluated once
    # at import, so `timeout=LINK_TIMEOUT_S` would freeze the value and the
    # module constant could never be tuned afterwards. That is not just a test
    # inconvenience: LINK_TIMEOUT_S is exactly the kind of constant that gets
    # adjusted per adapter once someone meets a slow one on a bench.
    timeout = LINK_TIMEOUT_S if timeout is None else timeout
    time.sleep(RECONFIG_SETTLE_S)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled and cancelled():
            return False
        if all(link_state(i)["link"] for i in ifaces):
            return True
        time.sleep(LINK_POLL_S)
    return False


def run_speed_ladder(
    iface_a: str,
    iface_b: str,
    on_event: Optional[Callable[[str, dict], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> dict:
    """Walk the link speeds with the cable under test between two ports.

    Both interfaces are advertised one speed at a time, because a link needs
    both ends to agree.  With one end restricted and the other offering
    everything, parallel detection brings the link up regardless and every
    rung passes, which is a false result that looks like a healthy cable.

    Autonegotiation is restored in a ``finally``.  A test that leaves an
    interface advertising 10BASE-T alone has quietly broken the box, and the
    person who finds out is the next person to plug something into it.
    """
    emit = on_event or (lambda kind, payload: None)
    a = _validate(iface_a)
    b = _validate(iface_b)

    if a == b:
        raise EthernetTestError("Pick two different interfaces: the cable needs two ends.")
    for iface in (a, b):
        if carries_default_route(iface):
            raise EthernetTestError(
                f"'{iface}' carries this box's default route. Testing it would drop "
                f"the network part way through. Use a different port."
            )

    rungs: List[dict] = []
    started = time.time()
    try:
        for rung in RUNGS:
            if cancelled and cancelled():
                break
            emit("rung_start", {"speed": rung["speed"]})
            _advertise(a, rung["mask"])
            _advertise(b, rung["mask"])
            linked = _settle([a, b], cancelled=cancelled)
            state = link_state(a)
            far = link_state(b)
            entry = {
                "speed": rung["speed"],
                "pairs": rung["pairs"],
                "link": bool(linked and state["link"]),
                # Only meaningful while linked; link_state already returns None
                # otherwise, and nothing downstream may infer a speed from a
                # dead link.
                "negotiated": state["speed"],
                "duplex": state["duplex"],
                "far_end_link": far["link"],
            }
            # A rung that links at a speed other than the one offered means the
            # advertisement was not honoured, and the result says nothing about
            # the cable. Surfaced rather than scored.
            if entry["link"] and entry["negotiated"] not in (None, rung["speed"]):
                entry["anomaly"] = (
                    f"advertised {rung['speed']}Mb but negotiated "
                    f"{entry['negotiated']}Mb; the adapter is not honouring the "
                    f"advertisement, so this result is about the adapter, not the cable"
                )
            rungs.append(entry)
            emit("rung_done", entry)
    finally:
        # Both ends, both on the way out of a normal run and out of an
        # exception. This is the ethernet equivalent of closing the port.
        for iface in (a, b):
            try:
                _advertise(iface, ADV_ALL)
            except EthernetTestError:
                pass

    return {
        "kind": "eth_ladder",
        "iface_a": a,
        "iface_b": b,
        "rungs": rungs,
        "cancelled": bool(cancelled and cancelled()),
        "elapsed": round(time.time() - started, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
