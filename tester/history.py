"""Version history, shown on the instrument.

One source of truth for what the tester is and what arrived when. The UI reads
this; nothing parses git, because the bench box has no network and a shallow
clone has no useful history anyway.

**On the project rule this sits beside.** CLAUDE.md says the UI describes the
instrument as it is and never as it was, and bans version-to-version
comparisons from visible copy. That rule governs OPERATIONAL copy: the pin
check's description must not explain itself by describing the bug it replaced.
A version screen a technician opens deliberately is a different thing, and JP
asked for it explicitly on 8/23/2026. The rule still holds everywhere else, and
this file is the only place in the UI allowed to talk about the past.

So write entries as "what this version does", not "what we changed". A
technician opening this wants to know whether the box in front of them has the
ethernet ladder, not what the previous release got wrong.

`released` is ISO because it is a record that has to sort and parse. The UI
formats it for display; see `fmt_when()` in app.py.
"""

from __future__ import annotations

from typing import Dict, List

#: Newest first. The first entry is the running version.
VERSIONS: List[Dict] = [
    {
        "version": "1.2.0",
        "released": "2026-08-23",
        "title": "Ethernet cables",
        "notes": [
            "Tests ethernet cables as well as serial. A cable is strung between "
            "the two network ports and the tester walks 10, 100 and 1000 Mb.",
            "Names the pairs at fault. 10 and 100 Mb use only the orange and "
            "green pairs, and gigabit needs all four, so the highest speed that "
            "links says which conductors are bad.",
            "Catches the cable that will pass in service and quietly "
            "underperform: one that links at 100 but not gigabit lets a gigabit "
            "device fall back without telling anyone.",
        ],
    },
    {
        "version": "1.1.0",
        "released": "2026-08-23",
        "title": "The bench box",
        "notes": [
            "Runs as a standalone instrument on a Raspberry Pi with a 7 inch "
            "touchscreen, full screen, with no desktop and no login.",
            "Reachable over the network at the same time, so the same live test "
            "can be watched from a laptop or a phone.",
            "Works with no internet. Fonts and icons are carried locally, so the "
            "screen looks the same on an isolated bench as on a desk.",
            "Reports the Pi's power state alongside the serial ports, because an "
            "underfed board produces timing errors that look exactly like a "
            "marginal cable.",
        ],
    },
    {
        "version": "1.0.0",
        "released": "2026-08-20",
        "title": "First release",
        "notes": [
            "Pin check and baud sweep for DB9 RS-232 cables, using a loopback "
            "plug on the far end.",
            "Grades signal integrity at speed rather than DC continuity, which is "
            "what a continuity tester misses.",
            "Health score, plain-English verdict, and a printable summary to "
            "staple to the cable.",
            "Identifies the cable's topology from what it observes rather than "
            "trusting a pin map.",
        ],
    },
]


def current() -> Dict:
    """The running version's entry."""
    return VERSIONS[0]


def current_version() -> str:
    return VERSIONS[0]["version"]
