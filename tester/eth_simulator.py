"""Virtual ethernet links, so the ladder can be exercised with no hardware.

Same bargain as ``simulator.py``: this is a model of a cable, not a cable. It
proves the ladder logic is self-consistent and proves nothing about how a real
PHY negotiates. Read it before trusting any test result that uses it.

What it models is the one physical fact the ladder rests on: 10 and 100BASE-T
need pairs 1-2 and 3-6 only, while 1000BASE-T needs all four. So a cable is
described by the highest speed its intact pairs can carry, and a rung links if
and only if both ends advertise a speed at or below that.
"""

from __future__ import annotations

import subprocess
from typing import Dict, Optional


class FakeLink:
    """A cable between two virtual ports.

    ``max_speed`` is the highest speed the surviving pairs support:
      1000  every pair intact
       100  blue and brown open, orange and green fine
        10  marginal on the pairs everything needs
         0  1-2 or 3-6 open or shorted, nothing links
    """

    def __init__(self, max_speed: int = 1000, honour_advertisement: bool = True):
        self.max_speed = max_speed
        # A chip that ignores the advertisement and links at whatever it likes.
        # Real behaviour on some adapters, and the ladder has to notice rather
        # than score it as a cable result.
        self.honour_advertisement = honour_advertisement
        self.advertised: Dict[str, int] = {}

    # Masks, mirroring ethernet_tests.
    _SPEED_FOR = {0x002: 10, 0x008: 100, 0x020: 1000}

    def _requested(self, iface: str) -> Optional[int]:
        mask = self.advertised.get(iface)
        if mask is None:
            return None
        if mask == 0x03F:                       # everything on offer
            return self.max_speed or None
        return self._SPEED_FOR.get(mask)

    def state(self, iface: str, other: str) -> dict:
        """What ethtool would report for ``iface``."""
        want_a = self._requested(iface)
        want_b = self._requested(other)
        # Both ends have to agree. One end restricted and the other offering
        # everything is exactly the false-pass this models so tests can catch it.
        if want_a is None or want_b is None or want_a != want_b:
            return {"link": False, "speed": None, "duplex": None}
        if want_a > self.max_speed:
            return {"link": False, "speed": None, "duplex": None}
        got = want_a if self.honour_advertisement else self.max_speed
        return {"link": True, "speed": got, "duplex": "Full"}


class FakeEthtool:
    """Stands in for the ethtool binary."""

    def __init__(self, link: FakeLink, iface_a: str, iface_b: str):
        self.link = link
        self.pair = {iface_a: iface_b, iface_b: iface_a}

    def __call__(self, args, timeout: float = 15.0) -> subprocess.CompletedProcess:
        """Only the write path goes through ethtool now.

        Reading link state moved to sysfs (see FakeSysfs below), so this models
        'ethtool -s ... advertise' and little else.
        """
        argv = list(args)
        if argv and argv[0] == "-s":
            iface = argv[1]
            if "advertise" in argv:
                mask = int(argv[argv.index("advertise") + 1], 16)
                self.link.advertised[iface] = mask
            return self._done("")
        return self._done("")

    @staticmethod
    def _done(stdout: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=["ethtool"], returncode=0,
                                           stdout=stdout, stderr="")


#: Named cables, mirroring simulator.SIM_CABLES.
SIM_LINKS = {
    "SIM-ETH-GOOD": FakeLink(1000),
    "SIM-ETH-100": FakeLink(100),      # blue and brown pairs open
    "SIM-ETH-10": FakeLink(10),
    "SIM-ETH-DEAD": FakeLink(0),
}


class FakeSysfs:
    """Stands in for /sys/class/net/<iface>/<file>.

    The real read path is sysfs, so the simulator has to be sysfs too. Note
    that `speed` is only consulted when `carrier` says the link is up, which is
    the point: unlike ethtool, sysfs is not asked for a speed it would have to
    invent.
    """

    def __init__(self, link: FakeLink, iface_a: str, iface_b: str):
        self.link = link
        self.pair = {iface_a: iface_b, iface_b: iface_a}

    def __call__(self, iface: str, name: str) -> str:
        st = self.link.state(iface, self.pair.get(iface, ""))
        if name == "carrier":
            return "1" if st["link"] else "0"
        if name == "speed":
            return str(st["speed"]) if st["link"] and st["speed"] else "-1"
        if name == "duplex":
            return (st["duplex"] or "").lower() if st["link"] else ""
        if name == "address":
            return "00:00:5e:00:53:01"
        return ""


def install(ethernet_tests, link: FakeLink, iface_a: str = "simA", iface_b: str = "simB") -> None:
    """Point a module at a virtual link instead of real hardware."""
    ethernet_tests._run = FakeEthtool(link, iface_a, iface_b)
    ethernet_tests._sysfs = FakeSysfs(link, iface_a, iface_b)
    ethernet_tests._driver = lambda name: "sim"
    ethernet_tests.ethtool_available = lambda: True
    ethernet_tests._validate = lambda name: name
    ethernet_tests.carries_default_route = lambda name: False
    # Nothing to settle in a model; keep the suite fast.
    ethernet_tests.RECONFIG_SETTLE_S = 0.0
    ethernet_tests.LINK_POLL_S = 0.0
    ethernet_tests.LINK_TIMEOUT_S = 0.05
