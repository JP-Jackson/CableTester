"""Tests for the pin check, sweep, scoring and profile logic.

Every serial interaction runs against the FakeCable simulator, so the whole
suite passes on a machine with no serial hardware at all.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tester import profiles, scoring, serial_tests  # noqa: E402
from tester.simulator import FakeCable, factory_for  # noqa: E402

FULL = {"DTR": ["DCD", "DSR"], "RTS": ["CTS"]}
FAST_RATES = [1200, 9600]


def pin_check(cable):
    return serial_tests.run_pin_check("SIM0", serial_factory=factory_for(cable))


def sweep(cable, rates=FAST_RATES, seconds=0.05):
    return serial_tests.run_baud_sweep(
        "SIM0", payload_seconds=seconds, rates=rates, serial_factory=factory_for(cable)
    )


class PinCheckTests(unittest.TestCase):
    def test_good_cable_passes_every_pin(self):
        result = pin_check(FakeCable(FULL))
        self.assertTrue(result["passed"], result["summary"])
        self.assertTrue(result["data_loopback"]["ok"])
        self.assertEqual(result["matrix"]["RTS"]["CTS"], True)
        self.assertEqual(result["matrix"]["DTR"]["DSR"], True)
        self.assertEqual(result["matrix"]["DTR"]["CTS"], False)
        self.assertEqual(result["matrix"]["RTS"]["RI"], False)

    def test_open_handshake_line_reported_as_open(self):
        result = pin_check(FakeCable({"DTR": ["DCD", "DSR"], "RTS": []}))
        cts = next(p for p in result["pins"] if p["signal"] == "CTS")
        self.assertEqual(cts["result"], "open")
        self.assertFalse(result["passed"])

    def test_crossed_line_reported_as_short(self):
        # DTR wrongly drives CTS as well as its own pair.
        result = pin_check(FakeCable({"DTR": ["DCD", "DSR", "CTS"], "RTS": ["CTS"]}))
        cts = next(p for p in result["pins"] if p["signal"] == "CTS")
        self.assertEqual(cts["result"], "short")
        self.assertIn("DTR", cts["detail"])

    def test_stuck_line_reported_as_short_not_pass(self):
        result = pin_check(FakeCable(FULL, stuck_lines={"CTS"}))
        cts = next(p for p in result["pins"] if p["signal"] == "CTS")
        self.assertEqual(cts["result"], "short")
        self.assertIn("stuck", cts["detail"])

    def test_broken_data_path_reported_on_pins_two_and_three(self):
        result = pin_check(FakeCable(FULL, data=False))
        rxd = next(p for p in result["pins"] if p["signal"] == "RXD")
        txd = next(p for p in result["pins"] if p["signal"] == "TXD")
        self.assertEqual(rxd["result"], "open")
        self.assertEqual(txd["result"], "open")
        self.assertFalse(result["passed"])

    def test_ground_pin_is_not_graded(self):
        result = pin_check(FakeCable(FULL))
        gnd = next(p for p in result["pins"] if p["pin"] == 5)
        self.assertFalse(gnd["graded"])
        self.assertEqual(gnd["result"], "reference")


class TopologyTests(unittest.TestCase):
    def test_full_handshake_is_ambiguous_between_straight_and_null_modem(self):
        result = pin_check(FakeCable(FULL))
        self.assertEqual(result["topology"]["kind"], "ambiguous")
        self.assertEqual(
            {m["id"] for m in result["topology"]["matches"]},
            {"straight_through", "null_modem"},
        )

    def test_three_wire_is_identified_as_an_observation(self):
        result = pin_check(FakeCable({"DTR": [], "RTS": []}))
        self.assertEqual(result["topology"]["kind"], "match")
        self.assertEqual(result["topology"]["matches"][0]["id"], "three_wire")
        self.assertTrue(result["topology"]["matches"][0]["observation"])

    def test_three_wire_passes_so_the_sweep_is_not_locked_out(self):
        # A 3-wire cable is a valid type: its handshake lines read n/c, not open,
        # and the cable must still qualify for the baud sweep.
        result = pin_check(FakeCable({"DTR": [], "RTS": []}))
        self.assertTrue(result["passed"], result["summary"])
        cts = next(p for p in result["pins"] if p["signal"] == "CTS")
        self.assertEqual(cts["result"], "nc")
        self.assertFalse(cts["graded"])
        self.assertIn("no hardware flow control", result["summary"])

    def test_a_dead_cable_still_fails_even_though_it_matches_a_reference(self):
        result = pin_check(FakeCable({"DTR": [], "RTS": []}, data=False))
        self.assertEqual(result["topology"]["matches"][0]["id"], "dead")
        self.assertFalse(result["passed"])

    def test_partially_open_handshake_is_a_fault_not_an_observation(self):
        # Full handshake minus one line matches no reference, so the missing
        # line must be reported as an open circuit.
        result = pin_check(FakeCable({"DTR": ["DCD", "DSR"], "RTS": []}))
        self.assertFalse(result["passed"])
        cts = next(p for p in result["pins"] if p["signal"] == "CTS")
        self.assertEqual(cts["result"], "open")

    def test_learned_three_wire_profile_also_reads_as_n_c(self):
        learned = [{
            "id": "shop-3wire", "name": "Shop 3-wire",
            "signature": {"DTR": [], "RTS": [], "data": True},
        }]
        result = serial_tests.run_pin_check(
            "SIM0", learned=learned, serial_factory=factory_for(FakeCable({"DTR": [], "RTS": []}))
        )
        self.assertTrue(result["passed"])
        self.assertIn("Shop 3-wire", result["summary"])

    def test_unrecognised_wiring_is_non_standard(self):
        result = pin_check(FakeCable({"DTR": ["CTS"], "RTS": ["DSR"]}))
        self.assertEqual(result["topology"]["kind"], "unknown")
        self.assertEqual(result["topology"]["label"], "Non-standard")

    def test_learned_profile_takes_priority_over_builtins(self):
        result = pin_check(FakeCable(FULL))
        learned = [{"id": "shop-cable", "name": "Shop cable #4", "signature": result["signature"]}]
        again = serial_tests.run_pin_check(
            "SIM0", learned=learned, serial_factory=factory_for(FakeCable(FULL))
        )
        self.assertEqual(again["topology"]["kind"], "learned")
        self.assertEqual(again["topology"]["label"], "Shop cable #4")


class SweepTests(unittest.TestCase):
    def test_clean_cable_scores_full_marks(self):
        result = sweep(FakeCable(FULL))
        for entry in result["rates"]:
            for run in entry["runs"].values():
                self.assertEqual(run["mismatched"], 0)
                self.assertEqual(run["missing"], 0)
        score = scoring.score_sweep(result["rates"])
        self.assertEqual(score["score"], 100.0)
        self.assertEqual(score["band"], "green")

    def test_sweep_runs_every_rate_despite_failures(self):
        rates = [1200, 9600, 19200]
        result = sweep(FakeCable(FULL, corrupt_above=1200, corrupt_rate=0.5), rates=rates)
        self.assertEqual([e["baud"] for e in result["rates"]], rates)
        self.assertEqual(len(result["rates"][-1]["runs"]), 2)

    def test_errors_above_a_rate_are_caught(self):
        result = sweep(FakeCable(FULL, corrupt_above=1200, corrupt_rate=0.5))
        low = result["rates"][0]["runs"]["none"]
        high = result["rates"][1]["runs"]["none"]
        self.assertEqual(low["mismatched"], 0)
        self.assertGreater(high["mismatched"], 0)
        self.assertGreater(high["ber"], 0.0)

    def test_both_parity_modes_are_run(self):
        result = sweep(FakeCable(FULL))
        self.assertEqual(set(result["rates"][0]["runs"]), {"none", "even"})

    def test_parity_only_failure_docks_the_score_without_failing_the_rate(self):
        result = sweep(FakeCable(FULL, parity_fails_above=1200, corrupt_rate=0.5))
        score = scoring.score_sweep(result["rates"])
        top = score["per_rate"][-1]
        self.assertEqual(top["none"], scoring.CLEAN)
        self.assertEqual(top["even"], scoring.FAIL)
        self.assertEqual(top["credit"], 0.6)
        self.assertEqual(top["status"], "pass")
        self.assertLess(score["score"], 100.0)

    def test_payload_scales_with_baud_and_is_reproducible(self):
        self.assertEqual(
            serial_tests.payload_for(9600, 2.0), serial_tests.payload_for(9600, 2.0)
        )
        self.assertLess(
            len(serial_tests.payload_for(1200, 2.0)), len(serial_tests.payload_for(115200, 2.0))
        )
        self.assertNotEqual(
            serial_tests.payload_for(1200, 2.0)[:32], serial_tests.payload_for(9600, 2.0)[:32]
        )

    def test_dropped_bytes_count_as_missing(self):
        result = sweep(FakeCable(FULL, drop_above=1200, corrupt_rate=0.2), rates=[9600])
        run = result["rates"][0]["runs"]["none"]
        self.assertGreater(run["missing"] + run["mismatched"], 0)
        self.assertGreaterEqual(run["timeouts"], 1)


class ScoringTests(unittest.TestCase):
    @staticmethod
    def _run(clean=True):
        if clean:
            return {"sent": 100, "received": 100, "mismatched": 0, "missing": 0, "ber": 0.0}
        return {"sent": 100, "received": 100, "mismatched": 50, "missing": 0, "ber": 0.2}

    def _entry(self, baud, none_clean=True, even_clean=True):
        return {
            "baud": baud,
            "runs": {"none": self._run(none_clean), "even": self._run(even_clean)},
        }

    def test_high_rates_dominate_the_score(self):
        low_only = [self._entry(b) for b in [1200, 2400, 4800, 9600, 19200]]
        low_only += [self._entry(b, False, False) for b in [38400, 57600, 115200]]
        result = scoring.score_sweep(low_only)
        self.assertEqual(result["max_reliable_baud"], 19200)
        self.assertLess(result["score"], 40.0)
        self.assertEqual(result["band"], "red")
        self.assertIn("19200", result["verdict"])
        self.assertIn("38400", result["verdict"])

    def test_bands(self):
        self.assertEqual(scoring.band(100), "green")
        self.assertEqual(scoring.band(85), "green")
        self.assertEqual(scoring.band(84.9), "amber")
        self.assertEqual(scoring.band(60), "amber")
        self.assertEqual(scoring.band(59.9), "red")

    def test_dead_cable_verdict(self):
        entries = [self._entry(b, False, False) for b in serial_tests.BAUD_RATES]
        result = scoring.score_sweep(entries)
        self.assertEqual(result["score"], 0.0)
        self.assertIsNone(result["max_reliable_baud"])
        self.assertIn("No reliable communication", result["verdict"])

    def test_partial_sweep_reports_coverage(self):
        result = scoring.score_sweep([self._entry(1200), {"baud": 2400, "runs": {}}])
        self.assertLess(result["coverage"], 100.0)
        self.assertEqual(len(result["per_rate"]), 1)

    def test_weights_match_the_specified_ratios(self):
        self.assertEqual(
            scoring.BAUD_WEIGHTS,
            {1200: 1, 2400: 1, 4800: 2, 9600: 3, 19200: 4, 38400: 6, 57600: 8, 115200: 10},
        )


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(
            os.environ.get("TMPDIR", "/tmp"), f"cabletester-test-{os.getpid()}.json"
        )
        self.store = profiles.ProfileStore(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_save_load_and_delete(self):
        sig = {"DTR": ["DCD", "DSR"], "RTS": ["CTS"], "data": True}
        saved = self.store.save("Bench cable", sig, "known good")
        self.assertEqual(saved["id"], "bench-cable")
        self.assertEqual(len(self.store.load()), 1)
        self.assertTrue(self.store.delete("bench-cable"))
        self.assertEqual(self.store.load(), [])
        self.assertFalse(self.store.delete("bench-cable"))

    def test_saving_the_same_name_replaces_rather_than_duplicates(self):
        sig = {"DTR": [], "RTS": [], "data": True}
        self.store.save("Cable A", sig)
        self.store.save("cable a", {"DTR": ["DSR"], "RTS": [], "data": True})
        loaded = self.store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["signature"]["DTR"], ["DSR"])

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save("   ", {"DTR": [], "RTS": [], "data": True})

    def test_corrupt_file_does_not_crash_the_tool(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.store.load(), [])


class ErrorHandlingTests(unittest.TestCase):
    def test_busy_port_raises_a_clear_error(self):
        def busy(**kwargs):
            raise OSError("[Errno 16] Device or resource busy: '/dev/ttyUSB0'")

        with self.assertRaises(serial_tests.PortBusyError) as ctx:
            serial_tests.open_serial("/dev/ttyUSB0", serial_factory=busy)
        self.assertIn("PCCU", ctx.exception.hint)

    def test_windows_access_denied_reads_as_busy(self):
        def denied(**kwargs):
            raise OSError("could not open port 'COM3': PermissionError(13, 'Access is denied.')")

        with self.assertRaises(serial_tests.PortBusyError):
            serial_tests.open_serial("COM3", serial_factory=denied)

    def test_missing_port_raises_port_not_found(self):
        def missing(**kwargs):
            raise OSError("[Errno 2] No such file or directory: '/dev/ttyUSB9'")

        with self.assertRaises(serial_tests.PortNotFoundError):
            serial_tests.open_serial("/dev/ttyUSB9", serial_factory=missing)

    def test_port_is_closed_even_when_the_test_raises(self):
        opened = []

        def factory(**kwargs):
            from tester.simulator import FakeSerial

            port = FakeSerial(FakeCable(FULL), **kwargs)
            opened.append(port)
            return port

        import threading

        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(serial_tests.TestCancelled):
            serial_tests.run_pin_check("SIM0", cancel=cancel, serial_factory=factory)
        self.assertTrue(opened)
        self.assertFalse(opened[0].is_open)


if __name__ == "__main__":
    unittest.main(verbosity=2)
