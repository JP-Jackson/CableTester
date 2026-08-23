"""Ethernet speed ladder tests.

Every one of these runs against eth_simulator, which is a model of a cable.
They prove the ladder logic is self-consistent. They prove nothing about how a
real PHY negotiates, and the hardware findings that shaped this code are in
DOC 12, not here.
"""

import importlib
import unittest

from tester import eth_simulator, scoring


class LadderTests(unittest.TestCase):
    def _run(self, link):
        # A fresh module per test: install() rebinds module-level functions, so
        # sharing one instance would leak a previous test's fake into the next.
        eth = importlib.reload(importlib.import_module("tester.ethernet_tests"))
        eth_simulator.install(eth, link)
        return eth.run_speed_ladder("simA", "simB")

    def test_good_cable_links_every_rung(self):
        res = self._run(eth_simulator.FakeLink(1000))
        self.assertEqual([r["speed"] for r in res["rungs"]], [10, 100, 1000])
        self.assertTrue(all(r["link"] for r in res["rungs"]))
        self.assertEqual([r["negotiated"] for r in res["rungs"]], [10, 100, 1000])

    def test_hundred_meg_cable_fails_only_gigabit(self):
        res = self._run(eth_simulator.FakeLink(100))
        linked = {r["speed"]: r["link"] for r in res["rungs"]}
        self.assertTrue(linked[10])
        self.assertTrue(linked[100])
        self.assertFalse(linked[1000])

    def test_dead_cable_links_nothing(self):
        res = self._run(eth_simulator.FakeLink(0))
        self.assertFalse(any(r["link"] for r in res["rungs"]))

    def test_speed_is_never_reported_without_a_link(self):
        """The trap the hardware probe found.

        ethtool echoes the last configured speed with the link down, which
        reads exactly like a negotiated result. A probe run once reported
        10Mb/s and 100Mb/s for a cable that was not plugged in.
        """
        res = self._run(eth_simulator.FakeLink(0))
        for rung in res["rungs"]:
            self.assertFalse(rung["link"])
            self.assertIsNone(rung["negotiated"], "reported a speed with no link")
            self.assertIsNone(rung["duplex"])

    def test_autonegotiation_is_restored_afterwards(self):
        """Leaving an interface advertising 10BASE-T alone breaks the box."""
        link = eth_simulator.FakeLink(1000)
        self._run(link)
        self.assertEqual(link.advertised["simA"], 0x03F)
        self.assertEqual(link.advertised["simB"], 0x03F)

    def test_autonegotiation_is_restored_after_a_failure(self):
        eth = importlib.reload(importlib.import_module("tester.ethernet_tests"))
        link = eth_simulator.FakeLink(1000)
        eth_simulator.install(eth, link)

        calls = {"n": 0}
        real = eth._advertise

        def explode(iface, mask):
            calls["n"] += 1
            if calls["n"] == 3:
                raise eth.EthernetTestError("simulated adapter failure")
            return real(iface, mask)

        eth._advertise = explode
        with self.assertRaises(eth.EthernetTestError):
            eth.run_speed_ladder("simA", "simB")
        # The restore path uses the patched _advertise too, so the point is
        # that it ran at all rather than the exact value it left behind.
        self.assertGreater(calls["n"], 3, "no restore was attempted after the failure")

    def test_refuses_the_same_interface_twice(self):
        eth = importlib.reload(importlib.import_module("tester.ethernet_tests"))
        eth_simulator.install(eth, eth_simulator.FakeLink(1000))
        with self.assertRaises(eth.EthernetTestError):
            eth.run_speed_ladder("simA", "simA")

    def test_refuses_an_interface_carrying_the_default_route(self):
        """Walking the box's own uplink through three rungs ends the session."""
        eth = importlib.reload(importlib.import_module("tester.ethernet_tests"))
        eth_simulator.install(eth, eth_simulator.FakeLink(1000))
        eth.carries_default_route = lambda name: name == "simB"
        with self.assertRaises(eth.EthernetTestError):
            eth.run_speed_ladder("simA", "simB")

    def test_notices_an_adapter_ignoring_the_advertisement(self):
        """A link at the wrong speed says nothing about the cable."""
        res = self._run(eth_simulator.FakeLink(1000, honour_advertisement=False))
        anomalies = [r for r in res["rungs"] if r.get("anomaly")]
        self.assertTrue(anomalies, "an unhonoured advertisement went unflagged")


class ScoringTests(unittest.TestCase):
    @staticmethod
    def _rungs(*linked):
        return [{"speed": s, "link": s in linked} for s in (10, 100, 1000)]

    def test_gigabit_is_green(self):
        r = scoring.score_link_ladder(self._rungs(10, 100, 1000))
        self.assertEqual(r["band"], scoring.BAND_GREEN)
        self.assertIsNone(r["suspect_pairs"])

    def test_hundred_meg_is_amber_and_names_the_pairs(self):
        r = scoring.score_link_ladder(self._rungs(10, 100))
        self.assertEqual(r["band"], scoring.BAND_AMBER)
        self.assertIn("4-5", r["suspect_pairs"])
        self.assertIn("gigabit", r["verdict"])

    def test_dead_cable_is_red(self):
        r = scoring.score_link_ladder(self._rungs())
        self.assertEqual(r["band"], scoring.BAND_RED)
        self.assertEqual(r["score"], 0.0)

    def test_an_inconsistent_ladder_never_reads_green(self):
        """A gauge is read from across a bench; a paragraph is not.

        Scoring on the highest rung that linked would put a green gauge above a
        verdict saying the measurement cannot be trusted.
        """
        r = scoring.score_link_ladder(self._rungs(100, 1000))
        self.assertTrue(r["inconsistent"])
        self.assertEqual(r["band"], scoring.BAND_RED)

    def test_an_unhonoured_rung_is_excluded_from_the_score(self):
        rungs = [
            {"speed": 10, "link": True},
            {"speed": 100, "link": True},
            {"speed": 1000, "link": True, "anomaly": "negotiated 100Mb"},
        ]
        self.assertEqual(scoring.best_link_speed(rungs), 100)


class RouteDetectionTests(unittest.TestCase):
    """Refusing to test the box's own uplink is a safety rule, so it is tested.

    The first implementation shelled out to `ip`, and on a box without it the
    conservative fallback marked every interface untestable while claiming they
    all carried the default route. Failing safe was right; saying something
    untrue while doing it was not.
    """

    IPV4 = (
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t010200C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        "eth0\t000200C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
        "eth1\t000100C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
    )

    def _eth(self):
        import importlib
        return importlib.reload(importlib.import_module("tester.ethernet_tests"))

    def test_the_uplink_is_recognised_and_the_others_are_not(self):
        eth = self._eth()
        rows = self.IPV4.splitlines()
        self.assertTrue(eth._ipv4_default(rows[1].split(), "eth0"))
        self.assertFalse(eth._ipv4_default(rows[2].split(), "eth0"))
        self.assertFalse(eth._ipv4_default(rows[3].split(), "eth1"))

    def test_an_ipv6_default_route_counts(self):
        """JP's Pi spent an evening on IPv6 with no IPv4 address at all."""
        eth = self._eth()
        fields = ["0" * 32, "00", "0" * 32, "00", "0" * 32,
                  "00000400", "00000000", "00000000", "00000003", "wlan0"]
        self.assertTrue(eth._ipv6_default(fields, "wlan0"))
        self.assertFalse(eth._ipv6_default(fields, "eth0"))

    def test_no_readable_routing_table_assumes_load_bearing(self):
        """Not knowing must never read as 'safe to reconfigure'."""
        eth = self._eth()
        real_open = open

        def no_proc(path, *a, **kw):
            if str(path).startswith("/proc/net/"):
                raise OSError("no routing table here")
            return real_open(path, *a, **kw)

        import builtins
        builtins.open = no_proc
        try:
            self.assertTrue(eth.carries_default_route("eth9"))
        finally:
            builtins.open = real_open


if __name__ == "__main__":
    unittest.main()


class VersionTests(unittest.TestCase):
    def test_version_string_matches_the_history_the_ui_shows(self):
        """Two sources of truth for one fact is one too many.

        __version__ is what the code reports; history.VERSIONS[0] is what a
        technician reads off the panel. If they drift, the box tells one story
        to a log and another to the person holding it.
        """
        from tester import __version__, history
        self.assertEqual(__version__, history.current_version())

    def test_history_dates_are_stored_iso(self):
        """Stored timestamps sort and parse; only display strings are pretty."""
        import datetime
        from tester import history
        for entry in history.VERSIONS:
            datetime.datetime.strptime(entry["released"], "%Y-%m-%d")

    def test_history_is_newest_first(self):
        from tester import history
        released = [v["released"] for v in history.VERSIONS]
        self.assertEqual(released, sorted(released, reverse=True))
