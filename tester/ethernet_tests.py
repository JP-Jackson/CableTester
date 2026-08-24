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

def ethtool_available() -> bool:
    return shutil.which("ethtool") is not None


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
    """Driver name, from sysfs rather than ethtool.

    Reading it deliberately does not need ethtool, so the interface list still
    works on a box where ethtool was never installed. That box cannot run a
    ladder, but it should say so on a screen rather than fail with a stack
    trace where the port list belongs.
    """
    try:
        return os.path.basename(os.readlink(f"/sys/class/net/{iface}/device/driver"))
    except OSError:
        return ""


def link_state(iface: str) -> dict:
    """Current link state, read from sysfs.

    sysfs rather than ethtool for three reasons, and the third is the one that
    matters.

    It needs no ethtool, so the read path survives on a box that has none. It
    needs no subprocess, so _settle can poll it cheaply in a loop rather than
    forking a process twice a second.

    And it cannot reproduce the trap ethtool has: with the link down, `ethtool`
    echoes back the speed it was last CONFIGURED with, which is
    indistinguishable from a negotiated result, and a probe run duly reported
    "10Mb/s Full" for a cable that was not plugged in. Here the carrier file is
    the authority and speed is not read at all unless it says the link is up,
    so the wrong answer is not filtered out, it is never fetched.
    """
    link = _sysfs(iface, "carrier") == "1"
    if not link:
        return {"iface": iface, "link": False, "speed": None, "duplex": None}
    raw_speed = _sysfs(iface, "speed")
    speed: Optional[int] = None
    if raw_speed and raw_speed.lstrip("-").isdigit() and int(raw_speed) > 0:
        speed = int(raw_speed)
    duplex = _sysfs(iface, "duplex") or None
    if duplex:
        duplex = duplex.capitalize()
    return {"iface": iface, "link": True, "speed": speed, "duplex": duplex}


def carries_default_route(iface: str) -> bool:
    """Is this interface the box's way out?

    Walking an interface through three advertisement changes drops its link at
    every rung.  Doing that to the route the technician arrived on ends the
    session mid-test and looks like the instrument crashing.

    Read from /proc rather than by shelling out to `ip`. The first version ran
    `ip route show default dev X`, which is fine until `ip` is absent, at which
    point the conservative fallback fired for EVERY interface and the port list
    came back entirely untestable with a note claiming they all carried the
    default route. Failing safe was right; failing safe while stating something
    untrue was not.

    Both families are checked, because JP's own Pi spent an evening holding an
    IPv6 address and no IPv4 one, so "the default route" cannot be assumed to
    be v4. A MISSING table is not the same as an unreadable one: no
    /proc/net/ipv6_route means the box has no IPv6 routing, which is an answer.
    Only failing to read *any* table means we genuinely do not know, and that
    is the only case that falls back to assuming the interface is load bearing.
    """
    known = False
    for path, matcher, header in (
        ("/proc/net/route", _ipv4_default, True),
        ("/proc/net/ipv6_route", _ipv6_default, False),
    ):
        try:
            with open(path) as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        known = True
        for line in (lines[1:] if header else lines):
            if matcher(line.split(), iface):
                return True
    # Nothing readable at all: assume load bearing. The cost of guessing wrong
    # the other way is the box losing its network part way through a test.
    return not known


def _ipv4_default(fields: List[str], iface: str) -> bool:
    # Iface Destination Gateway Flags RefCnt Use Metric Mask ...
    # A default route is destination 0.0.0.0 under a 0.0.0.0 mask.
    return (
        len(fields) >= 8
        and fields[0] == iface
        and fields[1] == "00000000"
        and fields[7] == "00000000"
    )


def _ipv6_default(fields: List[str], iface: str) -> bool:
    # dest_prefix dest_plen src_prefix src_plen next_hop metric ... iface
    # A default route is the all-zero prefix with length 0.
    return (
        len(fields) >= 10
        and fields[-1] == iface
        and fields[0] == "0" * 32
        and fields[1] == "00"
    )


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
            raise EthernetTestError(_permission_help(iface))
        raise EthernetTestError(f"Could not set the advertised speed on {iface}: {detail}")


def _permission_help(iface: str) -> str:
    """Say what to do, in the context the caller is actually in.

    Reconfiguring an interface needs CAP_NET_ADMIN, and how you get it depends
    entirely on how the tester was started. The service is granted it by its
    unit file; a shell is not, and telling someone at a prompt to read a
    systemd unit is useless advice. So the message branches on who is asking.
    """
    if os.geteuid() == 0:
        return (
            f"Not permitted to reconfigure {iface} even as root. The capability "
            f"is being dropped somewhere: check CapabilityBoundingSet in "
            f"deploy/cabletester.service, or whether a container or LSM policy "
            f"is in the way."
        )
    return (
        f"Not permitted to reconfigure {iface}. Changing what an interface "
        f"advertises needs CAP_NET_ADMIN.\n"
        f"  From a shell:  sudo .venv/bin/python run.py --eth-test IFACE_A IFACE_B\n"
        f"  As the service: deploy/cabletester.service grants it. If the tester "
        f"is running and still says this, re-run ./deploy/setup-pi.sh (the unit "
        f"file is a copy, so a git pull does not update it) and "
        f"'sudo systemctl restart cabletester'."
    )


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
        # Reported, never scored. A crossover is a legitimate cable.
        "orientation": cable_orientation(a, b),
        "cancelled": bool(cancelled and cancelled()),
        "elapsed": round(time.time() - started, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# --------------------------------------------------------------------------
# Moving actual data
#
# The ladder proves a link comes up. It does not move one byte, which means a
# cable with marginal crosstalk that negotiates gigabit perfectly and then
# drops frames under load scores 100 and green. That is the cable that passes
# on the bench and fails a large download, and until this existed the
# instrument had nothing whatever to say about it.
#
# **Raw layer 2, not TCP or ping.** Two interfaces on one host cannot simply be
# given addresses and talked between: Linux sees both as local, short-circuits
# the traffic through loopback, and the cable under test is never touched. The
# usual fix is a network namespace per interface, which needs root, teardown,
# and a great deal that can be left half-built on a bench box. An AF_PACKET
# socket bound to an interface bypasses the routing table completely: the frame
# goes out of that NIC and arrives on the other, or it does not. That is also
# the right layer for the question, because this is a test of copper rather
# than of a protocol stack.
#
# NOTHING HERE IS VERIFIED ON HARDWARE. It is written from the documented
# behaviour of AF_PACKET and sysfs counters, and it has been exercised against
# a fake. Until it has run on the kit, treat every number it produces as
# unproven, and see DOC 14.

import socket
import struct as _struct

#: Locally-administered EtherType, from the range IEEE reserves for exactly
#: this. Nothing else on a bench cable will be using it, and no stack will try
#: to interpret what we send.
CT_ETHERTYPE = 0x88B5

#: One full frame, less the 14 byte header. Deliberately the largest a standard
#: link carries: a marginal cable fails on long frames first, because a longer
#: frame is more bit periods for jitter to accumulate over and more chance of
#: hitting an error at any given bit error rate.
FRAME_PAYLOAD = 1486

#: Header we put inside the payload: a magic word and a sequence number, so a
#: frame that arrives can be identified, ordered, and checked.
_MAGIC = b"CTST"
_HDR = _struct.Struct("!4sI")

#: Counters worth reading around a transfer. rx_crc_errors is the one that
#: matters: a CRC error is a frame that arrived physically corrupted, which is
#: direct evidence about the copper rather than an inference from packet loss.
ERROR_COUNTERS = ("rx_crc_errors", "rx_frame_errors", "rx_errors",
                  "rx_over_errors", "rx_missed_errors", "tx_errors",
                  "tx_carrier_errors")


def read_counters(iface: str) -> Dict[str, int]:
    """NIC error counters, from sysfs. Missing ones are absent, not zero."""
    out: Dict[str, int] = {}
    for name in ERROR_COUNTERS:
        raw = _sysfs_stat(iface, name)
        if raw.isdigit():
            out[name] = int(raw)
    return out


def _sysfs_stat(iface: str, name: str) -> str:
    try:
        with open(f"/sys/class/net/{iface}/statistics/{name}") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def counter_delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    """Only counters that MOVED, so a clean run reports an empty dict."""
    return {k: after[k] - before.get(k, 0)
            for k in after if after[k] - before.get(k, 0) > 0}


def _open_raw(iface: str, rx: bool):
    """AF_PACKET socket bound to one interface.

    Raised as a CableTester-shaped error rather than a bare PermissionError,
    because "you need CAP_NET_RAW" is only useful next to how to get it, and
    that depends entirely on how the tester was started.
    """
    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW,
                             socket.htons(CT_ETHERTYPE if rx else 0))
        sock.bind((iface, CT_ETHERTYPE))
        return sock
    except PermissionError as exc:
        raise EthernetTestError(_raw_permission_help()) from exc
    except OSError as exc:
        raise EthernetTestError(
            f"Could not open a raw socket on {iface}: {exc}") from exc


def _raw_permission_help() -> str:
    if os.geteuid() == 0:
        return ("Not permitted to open a raw socket even as root. CAP_NET_RAW "
                "is being dropped: check CapabilityBoundingSet in "
                "deploy/cabletester.service.")
    return (
        "Not permitted to open a raw socket. Moving real data needs "
        "CAP_NET_RAW.\n"
        "  From a shell:  sudo .venv/bin/python run.py --eth-load IFACE_A IFACE_B\n"
        "  As the service: deploy/cabletester.service grants it. If the tester "
        "is running and still says this, re-run ./deploy/setup-pi.sh, since the "
        "unit file is a copy and a git pull does not update it."
    )


def run_load_test(
    iface_a: str,
    iface_b: str,
    seconds: float = 10.0,
    on_event: Optional[Callable[[str, dict], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> dict:
    """Push frames from A to B for a while and count what does not arrive intact.

    This is the ethernet answer to the serial baud sweep's payload: the ladder
    says the link comes up, and this says whether the cable carries traffic
    once it has. A frame is checked three ways, and they fail differently:

      lost        never arrived at all
      corrupted   arrived with the payload altered, CRC notwithstanding
      crc errors  the NIC itself rejected frames as physically damaged

    The last of those is the strongest evidence a cable is marginal, because it
    is the hardware reporting on the copper rather than us inferring it.
    """
    emit = on_event or (lambda kind, payload: None)
    a = _validate(iface_a)
    b = _validate(iface_b)
    if a == b:
        raise EthernetTestError("Pick two different interfaces: the cable needs two ends.")
    for iface in (a, b):
        if carries_default_route(iface):
            raise EthernetTestError(
                f"'{iface}' carries this box's default route. Flooding it with "
                f"raw frames would take the network down mid-test.")

    state_a = link_state(a)
    state_b = link_state(b)
    if not state_a["link"] or not state_b["link"]:
        down = [n for n, st in ((a, state_a), (b, state_b)) if not st["link"]]
        raise EthernetTestError(
            f"No link on {' and '.join(down)}. There is nothing to send down. "
            f"Run the speed sweep first and check both plugs are seated.")

    before = {a: read_counters(a), b: read_counters(b)}
    speed = state_a["speed"] or state_b["speed"]

    tx = _open_raw(a, rx=False)
    rx = _open_raw(b, rx=True)
    sent = received = corrupted = 0
    seen = set()
    started = time.time()
    try:
        rx.setblocking(False)
        deadline = started + max(0.5, seconds)
        # A frame is built once and its sequence number patched in, rather than
        # rebuilt each time: at gigabit this loop is the bottleneck, and a
        # bottleneck in the tester is measured as a slow cable.
        filler = bytes((i * 37 + 11) & 0xFF for i in range(FRAME_PAYLOAD - _HDR.size))
        last_emit = 0.0
        while time.time() < deadline:
            if cancelled and cancelled():
                break
            for _ in range(64):
                try:
                    tx.send(_HDR.pack(_MAGIC, sent & 0xFFFFFFFF) + filler)
                    sent += 1
                except BlockingIOError:
                    break
                except OSError:
                    break
            received, corrupted = _drain(rx, filler, seen, received, corrupted)
            now = time.time()
            if now - last_emit >= 0.4:
                last_emit = now
                emit("load_progress", {
                    "sent": sent, "received": received,
                    "elapsed": round(now - started, 1),
                    "mbps": _mbps(sent, now - started),
                })
        # Frames in flight when the clock ran out are not losses.
        drain_until = time.time() + 0.4
        while time.time() < drain_until:
            received, corrupted = _drain(rx, filler, seen, received, corrupted)
    finally:
        # Both sockets, on every path. A leaked AF_PACKET socket keeps the
        # interface in promiscuous mode and the next run inherits it.
        for sock in (tx, rx):
            try:
                sock.close()
            except OSError:
                pass

    elapsed = time.time() - started
    after = {a: read_counters(a), b: read_counters(b)}
    lost = max(0, sent - received)
    return _summarise_load(a, b, sent, received, lost, corrupted, elapsed, speed,
                           {a: counter_delta(before[a], after[a]),
                            b: counter_delta(before[b], after[b])})


def _drain(rx, filler: bytes, seen: set, received: int, corrupted: int):
    """Read whatever has arrived without blocking. Returns updated counts."""
    while True:
        try:
            frame = rx.recv(2048)
        except (BlockingIOError, InterruptedError):
            return received, corrupted
        except OSError:
            return received, corrupted
        # Our own EtherType only, and long enough to hold the header.
        if len(frame) < 14 + _HDR.size:
            continue
        body = frame[14:]
        magic, seq = _HDR.unpack(body[:_HDR.size])
        if magic != _MAGIC or seq in seen:
            continue
        seen.add(seq)
        received += 1
        # The NIC's CRC already rejected physically damaged frames, so a
        # payload mismatch here is rarer and worse: it means damage that
        # survived the check.
        if body[_HDR.size:_HDR.size + len(filler)] != filler:
            corrupted += 1
    return received, corrupted


def _mbps(frames: int, elapsed: float) -> float:
    if elapsed <= 0:
        return 0.0
    return round(frames * (FRAME_PAYLOAD + 14) * 8 / elapsed / 1e6, 1)


def _summarise_load(a, b, sent, received, lost, corrupted, elapsed, speed, counters):
    loss = (lost / sent) if sent else 1.0
    crc = sum(v for side in counters.values()
              for k, v in side.items() if k in ("rx_crc_errors", "rx_frame_errors"))
    clean = lost == 0 and corrupted == 0 and crc == 0
    return {
        "kind": "eth_load",
        "iface_a": a,
        "iface_b": b,
        "seconds": round(elapsed, 1),
        "frames_sent": sent,
        "frames_received": received,
        "frames_lost": lost,
        "frames_corrupted": corrupted,
        "loss_ratio": round(loss, 8),
        "bytes": sent * FRAME_PAYLOAD,
        "mbps": _mbps(sent, elapsed),
        "link_speed": speed,
        "counters": counters,
        "crc_errors": crc,
        "passed": clean,
        "verdict": load_verdict(sent, lost, corrupted, crc, elapsed, speed),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load_verdict(sent, lost, corrupted, crc, elapsed, speed) -> str:
    """Say what was moved, then what it does and does not prove."""
    if not sent:
        return "No frames were sent. The load test did not run."

    moved = sent * FRAME_PAYLOAD
    size = (f"{moved / 1e6:.1f} MB" if moved >= 1e6 else f"{moved / 1e3:.0f} kB")

    if crc:
        return (
            f"{crc:,} frames arrived physically damaged out of {sent:,} sent. "
            f"The NIC's own CRC check rejected them, which is the cable itself "
            f"rather than anything above it. Replace it."
        )
    if lost or corrupted:
        rate = (lost + corrupted) / sent
        return (
            f"{lost:,} frames lost and {corrupted:,} corrupted out of {sent:,}, "
            f"a loss rate of {rate:.2%}. A link that comes up and then drops "
            f"traffic is exactly the cable that passes a link test and fails a "
            f"large download."
        )
    # The same honesty the serial sweep now carries: a clean sample bounds the
    # error rate, it does not prove there is no error.
    vouches = moved / 3.0
    vouch_size = (f"{vouches / 1e6:.1f} MB" if vouches >= 1e6
                  else f"{vouches / 1e3:.0f} kB")
    at = f" at {speed} Mb" if speed else ""
    return (
        f"{size} moved{at} in {elapsed:.0f}s with no loss, no corruption and no "
        f"CRC errors. That vouches for transfers up to roughly {vouch_size}. "
        f"A larger download is outside what this test covered."
    )


# --------------------------------------------------------------------------
# Which way round is the cable wired?
#
# Two separate questions that are easy to confuse.
#
# **T568A against T568B is NOT detectable, ever.** The two standards swap the
# orange and green pairs wholesale, so a cable wired A at both ends and one
# wired B at both ends are pin 1 to pin 1, pin 2 to pin 2, identical all the
# way through. They differ only in which COLOUR of insulation lands on which
# pin, and an instrument at the connector sees pins, not colours. No amount of
# electrical cleverness recovers it, exactly as a symmetric loopback plug
# cannot tell straight-through from null modem on the serial side. Go by the
# colours visible through the plug body.
#
# **Straight against crossover IS detectable**, because that one really does
# change which pin reaches which pin. A crossover is A at one end and B at the
# other. It shows up in the MDI/MDI-X state each end settles on: with a
# straight cable exactly one end swaps its pairs, and with a crossover the
# cable has already done the swap so both ends agree. Same state at both ends
# means crossover; opposite states mean straight.
#
# The catch is driver support. Plenty of PHYs never report MDI-X, and the two
# chips in the kit do not support ethtool's --cable-test either, so this may
# simply come back unknown. Unknown is reported as unknown.

_MDIX_RE = re.compile(r"MDI-X:\s*(\S+)")


def mdix_state(iface: str) -> Optional[str]:
    """"mdi", "mdix", or None when the driver will not say."""
    if not ethtool_available():
        return None
    out = _run([iface])
    if out.returncode != 0:
        return None
    found = _MDIX_RE.search(out.stdout or "")
    if not found:
        return None
    value = found.group(1).strip().lower()
    if value in ("on", "mdi-x", "mdix"):
        return "mdix"
    if value in ("off", "mdi"):
        return "mdi"
    return None


def cable_orientation(iface_a: str, iface_b: str) -> dict:
    """Straight-through or crossover, when the hardware will tell us.

    Reported alongside the ladder rather than scored. A crossover cable is not
    a faulty cable: anything gigabit sorts it out with Auto MDI-X, and this
    tester links on one and grades it normally. It is worth SAYING because a
    technician holding an unlabelled lead usually wants to know.
    """
    a = mdix_state(iface_a)
    b = mdix_state(iface_b)
    if a is None or b is None:
        return {
            "kind": "unknown",
            "detail": "This adapter does not report its MDI-X state, so the "
                      "wiring cannot be read off it. Nothing is wrong with the "
                      "cable.",
            "mdix": {iface_a: a, iface_b: b},
        }
    crossed = a == b
    return {
        "kind": "crossover" if crossed else "straight",
        "detail": (
            "Crossover: transmit meets receive, so this is T568A at one end and "
            "T568B at the other. Not a fault. Anything gigabit handles it with "
            "Auto MDI-X, and it is graded the same as any other cable."
            if crossed else
            "Straight-through: every pin goes to the same pin. The ordinary "
            "patch lead, and what almost every installation uses."
        ),
        "mdix": {iface_a: a, iface_b: b},
    }
