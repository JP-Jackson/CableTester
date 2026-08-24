"""Continuity monitor tests.

The monitor exists to catch what every other test here misses: a cable that is
wired correctly and opens only when moved. These run against a fake port, so
they prove the counting and the reporting. They prove nothing about what a real
adapter can see, which is the limit the verdict text is careful about.
"""

import threading
import time
import unittest

from tester import continuity


class FlakyPort:
    """A port whose CTS drops out on a schedule.

    Models the fault the monitor is for: everything reads steady, then a
    conductor opens for a few tens of milliseconds, then recovers.
    """

    def __init__(self, drop_after=0.75, drop_for=0.12, drops=1):
        self.is_open = True
        self._dtr = False
        self._rts = False
        # Recorded rather than read at the end: _close_quietly drops both
        # lines before closing, deliberately, so the state afterwards says
        # nothing about whether they were ever asserted.
        self.dtr_was_asserted = False
        self.rts_was_asserted = False
        self.dsr = True
        self.cd = True
        self._t0 = time.monotonic()
        self._windows = [(drop_after + i * (drop_for + 0.2), drop_for) for i in range(drops)]

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = value
        self.dtr_was_asserted = self.dtr_was_asserted or bool(value)

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self._rts = value
        self.rts_was_asserted = self.rts_was_asserted or bool(value)

    @property
    def cts(self):
        now = time.monotonic() - self._t0
        return not any(start <= now < start + length for start, length in self._windows)

    def close(self):
        self.is_open = False


def run_for(port, seconds, **kw):
    cancel = threading.Event()
    threading.Timer(seconds, cancel.set).start()
    return continuity.run_serial_monitor(
        "SIM", cancel=cancel, serial_factory=lambda *a, **k: port, **kw)


class MonitorTests(unittest.TestCase):
    def test_a_steady_cable_records_no_dropouts(self):
        port = FlakyPort(drops=0)
        res = run_for(port, 0.5)
        self.assertEqual(res["dropouts"], 0)
        self.assertTrue(res["passed"])

    def test_a_dropout_is_caught_and_measured(self):
        port = FlakyPort(drop_after=0.6, drop_for=0.12, drops=1)
        res = run_for(port, 1.1)
        self.assertEqual(res["dropouts"], 1, res["events"])
        event = res["events"][0]
        self.assertEqual(event["line"], "CTS")
        # Timing is sampled, so allow slack; the point is it is roughly right
        # rather than an invented number.
        self.assertGreater(event["duration_ms"], 60)
        self.assertLess(event["duration_ms"], 250)

    def test_several_dropouts_are_all_recorded(self):
        port = FlakyPort(drop_after=0.55, drop_for=0.08, drops=3)
        res = run_for(port, 1.6)
        self.assertGreaterEqual(res["dropouts"], 2, res["events"])
        self.assertFalse(res["passed"])

    def test_a_clean_run_is_never_reported_as_proof(self):
        """The distinction between a useful instrument and a dangerous one.

        A monitor that saw nothing has established that nothing happened while
        it watched, at the resolution it could watch. Saying more than that on
        the one test meant to catch what others miss would be the instrument
        overstating what it knows.
        """
        res = run_for(FlakyPort(drops=0), 0.4)
        self.assertIn("not proof", res["verdict"])
        self.assertIn("No opens", res["verdict"])
        self.assertIn("invisible", res["verdict"])

    def test_a_found_dropout_condemns_the_cable_plainly(self):
        port = FlakyPort(drop_after=0.6, drop_for=0.1, drops=1)
        res = run_for(port, 1.0)
        self.assertIn("fail in service", res["verdict"])
        self.assertIn("pin 8", res["verdict"])
        self.assertIn("throw the cable away", res["verdict"])

    def test_the_port_is_closed_even_though_the_test_ends_by_cancelling(self):
        """Stopping is the normal end of this test, not an exception path."""
        port = FlakyPort(drops=0)
        run_for(port, 0.3)
        self.assertFalse(port.is_open)

    def test_dtr_and_rts_are_asserted_so_there_is_something_to_watch(self):
        """Checked as "was ever asserted", not "is asserted now".

        _close_quietly drops both lines before closing, on purpose, so reading
        them after the run would test the teardown rather than the test.
        """
        port = FlakyPort(drops=0)
        run_for(port, 0.5)
        self.assertTrue(port.dtr_was_asserted)
        self.assertTrue(port.rts_was_asserted)

    def test_a_fault_present_during_the_baseline_becomes_the_baseline(self):
        """Not a bug, and worth pinning so nobody "fixes" it.

        The baseline is whatever the cable does at rest. A line already open
        when the monitor starts is that cable's resting state, and the monitor
        reports changes from it. The tech is told to move the cable AFTER
        starting, which is what makes this the right behaviour.
        """
        port = FlakyPort(drop_after=0.0, drop_for=10.0, drops=1)
        res = run_for(port, 0.6)
        self.assertEqual(res["baseline"]["CTS"], False)
        self.assertEqual(res["dropouts"], 0)

    def test_the_baseline_is_the_cable_at_rest_not_an_ideal(self):
        """A 3-wire cable holds its handshake lines low. That is not a fault.

        Baselining against what a correct cable would do would report every
        3-wire cable as permanently faulty.
        """
        port = FlakyPort(drops=0)
        port.dsr = False
        port.cd = False
        res = run_for(port, 0.4)
        self.assertEqual(res["baseline"]["DSR"], False)
        self.assertEqual(res["dropouts"], 0)

    def test_the_resolution_limit_is_reported(self):
        res = run_for(FlakyPort(drops=0), 0.3)
        self.assertGreater(res["resolution_ms"], 0)


if __name__ == "__main__":
    unittest.main()


class WordingTests(unittest.TestCase):
    """The screen names the conductor and leaves the decision to a person."""

    def test_the_verdict_names_the_pin_not_only_the_signal(self):
        from tester.continuity import verdict_text
        text = verdict_text([{"line": "CTS"}], 30, 10)
        self.assertIn("CTS", text)
        self.assertIn("pin 8", text)

    def test_it_offers_repair_or_scrap_rather_than_condemning(self):
        from tester.continuity import verdict_text
        text = verdict_text([{"line": "DSR"}], 30, 10)
        self.assertIn("Repair", text)
        self.assertIn("throw the cable away", text)
        self.assertNotIn("Condemn", text)

    def test_affected_pins_drive_the_diagram(self):
        from tester.continuity import affected_pins
        self.assertEqual(affected_pins([{"line": "CTS"}, {"line": "DCD"}]), [1, 8])
