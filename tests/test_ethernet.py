"""Ethernet speed ladder tests.

Every one of these runs against eth_simulator, which is a model of a cable.
They prove the ladder logic is self-consistent. They prove nothing about how a
real PHY negotiates, and the hardware findings that shaped this code are in
DOC 12, not here.
"""

import importlib
import threading
import unittest

from tester import continuity, eth_simulator, ethernet_tests, scoring


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


class EthContinuityTests(unittest.TestCase):
    """The ethernet monitor, which had no heartbeat and watched only carrier.

    Both of those were invisible failures. With no tick the screen showed
    "idle" and a steady GOOD for the whole run, which is indistinguishable
    from an instrument that has hung. And watching carrier alone cannot see
    the fault this side is FOR: a pair that opens under flex renegotiates the
    link down without the carrier ever dropping.
    """

    #: install() rebinds module-level functions in place. LadderTests reloads
    #: the module, which gives it a NEW object, but continuity imported the
    #: original at module scope and still holds it. So these install into the
    #: object continuity actually calls, and put it back afterwards rather than
    #: leaving the real read path faked for whatever runs next.
    PATCHED = ("_run", "_sysfs", "_driver", "ethtool_available", "_validate",
               "carries_default_route", "RECONFIG_SETTLE_S", "LINK_POLL_S",
               "LINK_TIMEOUT_S", "ETH_POLL_S")

    def setUp(self):
        self.eth = continuity.ethernet_tests
        self.saved = {name: getattr(self.eth, name)
                      for name in self.PATCHED if hasattr(self.eth, name)}
        self.saved_poll = continuity.ETH_POLL_S
        continuity.ETH_POLL_S = 0.005

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(self.eth, name, value)
        continuity.ETH_POLL_S = self.saved_poll

    def _watch(self, link, seconds=0.9, at=None, do=None):
        eth_simulator.install(self.eth, link, "simA", "simB")
        link.advertised = {"simA": 0x03F, "simB": 0x03F}
        cancel = threading.Event()
        threading.Timer(seconds, cancel.set).start()
        if do is not None:
            threading.Timer(at, do).start()
        ticks = []
        result = continuity.run_eth_monitor(
            "simA", "simB", cancel=cancel,
            emit=lambda kind, payload: ticks.append(payload) if kind == "mon_tick" else None)
        return result, ticks

    def test_it_reports_that_it_is_alive(self):
        """A clean run emits no events at all, so the tick is the only proof."""
        result, ticks = self._watch(eth_simulator.FakeLink(1000))
        self.assertTrue(ticks, "the monitor sent no heartbeat")
        self.assertGreater(result["sample_rate_hz"], 0)
        self.assertIn("open_now", ticks[0])

    def test_it_watches_both_ends(self):
        result, _ = self._watch(eth_simulator.FakeLink(1000))
        self.assertEqual(result["watching"], ["Link A", "Link B"])

    def test_it_refuses_when_there_is_no_link_to_watch(self):
        eth_simulator.install(self.eth, eth_simulator.FakeLink(0), "simA", "simB")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(continuity.NothingToWatch):
            continuity.run_eth_monitor("simA", "simB", cancel=cancel)

    def test_the_refusal_names_the_end_that_is_down(self):
        eth_simulator.install(self.eth, eth_simulator.FakeLink(0), "simA", "simB")
        cancel = threading.Event()
        cancel.set()
        try:
            continuity.run_eth_monitor("simA", "simB", cancel=cancel)
        except continuity.NothingToWatch as exc:
            self.assertIn("simA", exc.hint)
        else:
            self.fail("expected the monitor to refuse")

    def test_a_pair_opening_is_caught_even_though_the_link_holds(self):
        link = eth_simulator.FakeLink(1000)
        result, _ = self._watch(link, seconds=1.1, at=0.3,
                                do=lambda: setattr(link, "max_speed", 100))
        drops = [e for e in result["events"] if e["line"] == "Speed"]
        self.assertEqual(len(drops), 1, result["events"])
        self.assertEqual(drops[0]["from"], 1000)
        self.assertEqual(drops[0]["to"], 100)
        self.assertFalse(result["passed"])

    def test_a_speed_drop_is_not_worded_as_a_broken_conductor(self):
        link = eth_simulator.FakeLink(1000)
        result, _ = self._watch(link, seconds=1.1, at=0.3,
                                do=lambda: setattr(link, "max_speed", 100))
        self.assertIn("blue and brown", result["verdict"])
        self.assertNotIn("That conductor is broken", result["verdict"])
        self.assertNotIn("pin ?", result["verdict"])


class LoadTestTests(unittest.TestCase):
    """The throughput test's reporting.

    NOT the transfer itself: that needs two real interfaces with a cable
    between them and cannot be faked honestly, so what is proven here is the
    arithmetic and the wording. See DOC 14. The transfer path is unverified on
    hardware and the docs say so.
    """

    def test_counter_delta_reports_only_what_moved(self):
        delta = ethernet_tests.counter_delta(
            {"rx_crc_errors": 4, "rx_errors": 9},
            {"rx_crc_errors": 11, "rx_errors": 9})
        self.assertEqual(delta, {"rx_crc_errors": 7})

    def test_a_counter_that_did_not_move_is_absent_not_zero(self):
        delta = ethernet_tests.counter_delta({"rx_errors": 3}, {"rx_errors": 3})
        self.assertEqual(delta, {})

    def test_a_clean_run_says_what_size_it_vouches_for(self):
        """The same honesty the serial sweep carries: a sample bounds the rate."""
        text = ethernet_tests.load_verdict(80000, 0, 0, 0, 10.0, 1000)
        self.assertIn("no loss", text)
        self.assertIn("vouches", text)

    def test_crc_errors_are_blamed_on_the_cable_and_nothing_else(self):
        """A CRC error is the NIC reporting on copper, not an inference."""
        text = ethernet_tests.load_verdict(80000, 0, 0, 37, 10.0, 1000)
        self.assertIn("physically damaged", text)
        self.assertIn("cable itself", text)

    def test_loss_is_named_as_the_download_failure_it_causes(self):
        text = ethernet_tests.load_verdict(80000, 412, 0, 0, 10.0, 1000)
        self.assertIn("large download", text)

    def test_a_run_that_sent_nothing_claims_nothing(self):
        text = ethernet_tests.load_verdict(0, 0, 0, 0, 0.0, None)
        self.assertIn("did not run", text)

    def test_a_clean_summary_passes_and_a_dirty_one_does_not(self):
        clean = ethernet_tests._summarise_load(
            "a", "b", 1000, 1000, 0, 0, 10.0, 1000, {"a": {}, "b": {}})
        self.assertTrue(clean["passed"])
        dirty = ethernet_tests._summarise_load(
            "a", "b", 1000, 1000, 0, 0, 10.0, 1000,
            {"a": {"rx_crc_errors": 2}, "b": {}})
        self.assertFalse(dirty["passed"])
        self.assertEqual(dirty["crc_errors"], 2)

    def test_crc_errors_fail_the_run_even_with_no_frames_lost(self):
        """Every frame arrived AND the wire was damaging some of them.

        Counting only what arrived would call that cable good.
        """
        r = ethernet_tests._summarise_load(
            "a", "b", 5000, 5000, 0, 0, 10.0, 1000,
            {"a": {"rx_crc_errors": 9}, "b": {}})
        self.assertFalse(r["passed"])


class OrientationTests(unittest.TestCase):
    """Straight against crossover, and the one that cannot be measured at all.

    T568A against T568B is NOT detectable. Both standards are pin 1 to pin 1
    all the way through and differ only in which colour of insulation lands on
    which pin, so an instrument at the connector sees identical cables. Same
    class of honest limit as straight-through against null modem on the serial
    side. Straight against crossover IS detectable, because that one really
    does change which pin reaches which pin.
    """

    def setUp(self):
        self.eth = ethernet_tests
        self.saved = self.eth.mdix_state

    def tearDown(self):
        self.eth.mdix_state = self.saved

    def _orient(self, a, b):
        self.eth.mdix_state = lambda iface: {"A": a, "B": b}[iface]
        return self.eth.cable_orientation("A", "B")

    def test_opposite_mdix_states_mean_a_straight_cable(self):
        """Exactly one end swaps its pairs, so the cable did not."""
        self.assertEqual(self._orient("mdi", "mdix")["kind"], "straight")

    def test_matching_mdix_states_mean_a_crossover(self):
        """Neither end needed to swap, because the cable already had."""
        self.assertEqual(self._orient("mdix", "mdix")["kind"], "crossover")
        self.assertEqual(self._orient("mdi", "mdi")["kind"], "crossover")

    def test_a_silent_driver_is_reported_as_unknown_not_guessed(self):
        result = self._orient(None, "mdix")
        self.assertEqual(result["kind"], "unknown")
        self.assertIn("does not report", result["detail"])

    def test_a_crossover_is_never_described_as_a_fault(self):
        """Anything gigabit handles one. Saying "fault" would condemn a good cable."""
        detail = self._orient("mdix", "mdix")["detail"]
        self.assertIn("Not a fault", detail)
        self.assertNotIn("replace", detail.lower())

    def test_an_unreadable_wiring_does_not_blame_the_cable_either(self):
        self.assertIn("Nothing is wrong with the cable",
                      self._orient(None, None)["detail"])
