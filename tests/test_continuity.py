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

    def __init__(self, drop_after=0.75, drop_for=0.12, drops=1,
                 data=False, data_drop_after=None, data_drop_for=0.4):
        self.is_open = True
        self._dtr = False
        self._rts = False
        # The data pair, modelled only when a test asks for it. Most of these
        # tests are about the handshake lines, and a port with no data path is
        # also the honest model of one this probe cannot drive.
        self.data = data
        self._echo = bytearray()
        self._data_windows = ([] if data_drop_after is None
                              else [(data_drop_after, data_drop_for)])
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

    # -- the data pair, pins 2 and 3 ----------------------------------------
    def _data_joined(self):
        now = time.monotonic() - self._t0
        return not any(start <= now < start + length
                       for start, length in self._data_windows)

    def write(self, payload):
        if not self.data:
            raise AttributeError("this port has no data path")
        if self._data_joined():
            self._echo.extend(payload)
        return len(payload)

    def read(self, size=1):
        chunk = bytes(self._echo[:size])
        del self._echo[:size]
        return chunk

    @property
    def in_waiting(self):
        return len(self._echo)

    def reset_input_buffer(self):
        self._echo.clear()

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
        # Still the baseline, and still not a dropout. What it is no longer is
        # invisible: a conductor that was open before the cable was touched is
        # reported as such rather than quietly becoming the reference.
        self.assertIn("CTS", res["dead_at_start"])
        self.assertFalse(res["passed"])

    def test_the_baseline_is_the_cable_at_rest_not_an_ideal(self):
        """The baseline stays the cable at rest, never an ideal cable.

        Grading against what a correct cable would do would report every cable
        that is not full-handshake as permanently faulty. What the baseline is
        NOT allowed to do is swallow the finding: this port has CTS alive and
        DSR and DCD dead, which is a full-handshake cable with two broken
        conductors, and it must not come back clean just because nothing
        changed while it was watched.
        """
        port = FlakyPort(drops=0)
        port.dsr = False
        port.cd = False
        res = run_for(port, 0.4)
        self.assertEqual(res["baseline"]["DSR"], False)
        self.assertEqual(res["dropouts"], 0)
        self.assertEqual(res["dead_at_start"], ["DSR", "DCD"])
        self.assertFalse(res["passed"])

    def test_the_resolution_limit_is_reported(self):
        res = run_for(FlakyPort(drops=0), 0.3)
        self.assertGreater(res["resolution_ms"], 0)


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

    def test_a_pin_already_open_is_still_lit_on_the_diagram(self):
        """It produced no event, and it is exactly the pin to point at."""
        from tester.continuity import affected_pins
        self.assertEqual(affected_pins([], ["DSR"]), [6])

    def test_the_data_pair_names_both_its_pins(self):
        from tester.continuity import verdict_text
        text = verdict_text([{"line": "Data"}], 30, 10)
        self.assertIn("pins 2 and 3", text)

    def test_a_line_with_no_pin_is_not_given_a_question_mark(self):
        """An ethernet finding has no DB9 pin, and must not pretend to.

        Reaching for the pin table regardless produced findings reading
        "Link A (pin ?)", which reads as the instrument having lost track of
        what it was measuring.
        """
        from tester.continuity import verdict_text
        text = verdict_text([{"line": "Link A"}], 30, 50)
        self.assertIn("Link A", text)
        self.assertNotIn("pin ?", text)
        self.assertNotIn("(pin", text)


class NothingToWatchTests(unittest.TestCase):
    """The failure mode that made this monitor dangerous rather than useless.

    A monitor reports change from a baseline, so a conductor that was already
    open when the baseline was taken produces a perfectly clean run. Clean runs
    read as good cables. That is how a cable with a broken pin 8 left the bench
    with the instrument's blessing.
    """

    def test_it_refuses_to_watch_a_cable_with_nothing_alive_in_it(self):
        port = FlakyPort(drop_after=0.0, drop_for=99.0, drops=1)
        port.dsr = False
        port.cd = False
        with self.assertRaises(continuity.NothingToWatch):
            run_for(port, 0.6)

    def test_the_refusal_says_what_to_go_and_do(self):
        port = FlakyPort(drop_after=0.0, drop_for=99.0, drops=1)
        port.dsr = False
        port.cd = False
        try:
            run_for(port, 0.6)
        except continuity.NothingToWatch as exc:
            self.assertIn("loopback plug", exc.hint)
            self.assertIn("seated", exc.hint)
        else:
            self.fail("expected the monitor to refuse")

    def test_the_port_is_closed_on_the_refusal_path_too(self):
        """The refusal happens after the port is open. It still has to close."""
        port = FlakyPort(drop_after=0.0, drop_for=99.0, drops=1)
        port.dsr = False
        port.cd = False
        with self.assertRaises(continuity.NothingToWatch):
            run_for(port, 0.6)
        self.assertFalse(port.is_open)

    def test_a_3_wire_cable_is_a_cable_type_and_still_passes(self):
        """The distinction that keeps the refusal from condemning good cables.

        Every handshake line absent AND the data pair carrying is a 3-wire
        cable, which the pin check passes. All three absent is a cable type;
        two of three absent is a fault.
        """
        port = FlakyPort(drop_after=0.0, drop_for=99.0, drops=1, data=True)
        port.dsr = False
        port.cd = False
        res = run_for(port, 0.7)
        self.assertTrue(res["passed"])
        self.assertEqual(res["not_fitted"], ["CTS", "DSR", "DCD"])
        self.assertEqual(res["dead_at_start"], [])
        self.assertEqual(res["watching"], ["Data"])

    def test_a_3_wire_run_says_what_it_did_not_watch(self):
        port = FlakyPort(drop_after=0.0, drop_for=99.0, drops=1, data=True)
        port.dsr = False
        port.cd = False
        res = run_for(port, 0.7)
        self.assertIn("3-wire", res["verdict"])
        self.assertIn("only the data pair", res["verdict"])


class DataPairTests(unittest.TestCase):
    """Pins 2 and 3 are watched too, not just the handshake lines."""

    def test_the_data_pair_is_watched_on_a_full_handshake_cable(self):
        res = run_for(FlakyPort(drops=0, data=True), 0.7)
        self.assertIn("Data", res["watching"])
        self.assertTrue(res["passed"])

    def test_a_break_in_the_data_pair_is_caught(self):
        port = FlakyPort(drops=0, data=True, data_drop_after=0.8, data_drop_for=0.5)
        res = run_for(port, 1.9)
        data_events = [e for e in res["events"] if e["line"] == "Data"]
        self.assertEqual(len(data_events), 1, res["events"])
        self.assertFalse(res["passed"])
        self.assertIn("pins 2 and 3", res["verdict"])

    def test_latency_below_the_threshold_is_not_called_a_fault(self):
        """The instrument's worst failure would be confidence about a good cable.

        A round trip through a USB adapter costs milliseconds and a scheduler
        hiccup costs tens of them. Anything under the threshold is latency.
        """
        port = FlakyPort(drops=0, data=True, data_drop_after=0.6,
                         data_drop_for=continuity.DATA_OPEN_MS / 1000.0 * 0.4)
        res = run_for(port, 1.3)
        self.assertEqual([e for e in res["events"] if e["line"] == "Data"], [])

    def test_a_port_with_no_data_path_is_not_reported_as_a_broken_one(self):
        """Cannot probe is not the same finding as probed and found open."""
        res = run_for(FlakyPort(drops=0, data=False), 0.5)
        self.assertNotIn("Data", res["watching"])
        self.assertNotIn("Data", res["dead_at_start"])
        self.assertTrue(res["passed"])


if __name__ == "__main__":
    unittest.main()
