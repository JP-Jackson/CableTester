"""Sweep settings: validation, persistence and duration estimates."""

import importlib
import os
import tempfile
import unittest

from tester import serial_tests


class SweepSettingsTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)
        os.environ["CABLETESTER_SWEEP_SETTINGS"] = self.path
        self.ss = importlib.reload(importlib.import_module("tester.sweep_settings"))

    def tearDown(self):
        os.environ.pop("CABLETESTER_SWEEP_SETTINGS", None)
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_factory_settings_are_available_with_nothing_saved(self):
        names = [s["name"] for s in self.ss.load()]
        self.assertEqual(names, ["Quick", "Standard", "Thorough", "Soak", "Custom"])

    def test_every_setting_states_a_time_cost(self):
        """The button has to say '10 min' before a tech commits to ten minutes."""
        for s in self.ss.load():
            self.assertTrue(s["duration"])
            self.assertGreater(s["seconds"], 0)

    def test_thorough_costs_more_than_quick(self):
        by_id = {s["id"]: s for s in self.ss.load()}
        self.assertGreater(by_id["thorough"]["seconds"], by_id["quick"]["seconds"] * 10)

    def test_edits_survive_a_reload(self):
        self.ss.save("custom", {"rates": [9600], "passes": 3, "pattern": "stress"})
        again = importlib.reload(importlib.import_module("tester.sweep_settings"))
        got = again.get("custom")
        self.assertEqual(got["rates"], [9600])
        self.assertEqual(got["passes"], 3)
        self.assertEqual(got["pattern"], "stress")

    def test_every_setting_is_editable_not_only_custom(self):
        """A shop whose links all run at 9600 should be able to redefine Standard."""
        self.ss.save("standard", {"rates": [9600]})
        self.assertEqual(self.ss.get("standard")["rates"], [9600])

    def test_nonsense_values_fall_back_rather_than_crashing(self):
        """A stored file gets hand-edited sooner or later.

        A bad value there must degrade to something sensible, not take the
        instrument down at the moment a technician presses start.
        """
        got = self.ss.save("custom", {
            "rates": [1, 2, 3],            # none are real baud rates
            "payload_seconds": "banana",
            "passes": -5,
            "parity": "sideways",
            "pattern": "polkadot",
        })
        self.assertTrue(set(got["rates"]).issubset(set(serial_tests.BAUD_RATES)))
        self.assertGreaterEqual(got["payload_seconds"], serial_tests.MIN_PAYLOAD_SECONDS)
        self.assertGreaterEqual(got["passes"], 1)
        self.assertIn(got["parity"], self.ss.PARITIES)
        self.assertIn(got["pattern"], self.ss.PATTERNS)

    def test_payload_seconds_cannot_exceed_the_engine_cap(self):
        got = self.ss.save("custom", {"payload_seconds": 9999})
        self.assertLessEqual(got["payload_seconds"], serial_tests.MAX_PAYLOAD_SECONDS)

    def test_reset_restores_the_factory_values(self):
        self.ss.save("quick", {"passes": 7})
        self.assertEqual(self.ss.get("quick")["passes"], 7)
        self.ss.reset()
        self.assertEqual(self.ss.get("quick")["passes"], 1)

    def test_unknown_setting_is_refused(self):
        with self.assertRaises(ValueError):
            self.ss.save("nonexistent", {})


class PatternTests(unittest.TestCase):
    def test_stress_pattern_is_alternating_bits(self):
        """0x55 every clock is the worst case for slew rate and capacitance.

        This is what actually kills a marginal cable at high baud, and it is
        why a longer random run is not a harder one.
        """
        payload = serial_tests.payload_for(9600, 1.0, "stress")
        self.assertEqual(set(payload), {0x55})

    def test_dc_pattern_is_a_run_of_ones_then_zeros(self):
        payload = serial_tests.payload_for(9600, 1.0, "dc")
        self.assertEqual(payload[0], 0xFF)
        self.assertEqual(payload[-1], 0x00)

    def test_random_pattern_is_reproducible(self):
        a = serial_tests.payload_for(9600, 1.0, "random")
        b = serial_tests.payload_for(9600, 1.0, "random")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
