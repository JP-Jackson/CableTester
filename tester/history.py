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
        "version": "1.5.0",
        "released": "2026-08-24",
        "title": "A test that says how much it proved",
        "notes": [
            "Testing a cable is a procedure and the test screen is now one. "
            "A step strip states the order and where the run has got to, one "
            "button always offers the next action, and each step shows its own "
            "detail, so the result of the thing you started is never somewhere "
            "you have to go and find.",
            "Every result says how much data it moved and how large a transfer "
            "that vouches for. A cable can pass a short test and still corrupt "
            "a big download, so a score is good to the depth it looked and the "
            "screen says how deep that was.",
            "Soak works one cable for minutes rather than seconds, moving "
            "megabytes. It is the setting for a cable that passes everything "
            "else and still fails a large download.",
            "Ethernet moves real data and counts what does not arrive, "
            "including frames the network card rejects as damaged. A link that "
            "comes up is not the same as a cable that carries traffic.",
            "The flex test holds a fault once it has seen one. A conductor that "
            "opens and recovers leaves the screen reading FAULT FOUND, not GOOD.",
            "The dial reads how much data has gone down the cable, with the "
            "rate against a scale in thousands of baud and how far through that "
            "rate it has got.",
            "Wiring carries three references on each protocol: the loopback "
            "plug with its jumpers drawn on the connector, every pin named, and "
            "straight-through against null modem or crossover.",
            "The serial drawing shows a male shell as pins and a female shell "
            "as sockets, so which end you are holding is visible rather than "
            "implied by the row order.",
        ],
    },
    {
        "version": "1.4.0",
        "released": "2026-08-24",
        "title": "Ports in Setup, and a clearer continuity screen",
        "notes": [
            "Which ports the cable is on is set once under Setup, not chosen "
            "per test. They are wired into the case and do not change between "
            "cables, and the status bar reports what is under test.",
            "The test screen now shows the results, so you do not have to go "
            "looking for the answer to the thing you just started. Each line "
            "opens the screen with the detail.",
            "Continuity names the conductor and the pin, shows it on the plug "
            "diagram, and draws a timeline of when each open happened while you "
            "were flexing the cable.",
            "The plug diagram can be shown as a male or a female shell, and the "
            "heading says which. The rows mirror between them.",
            "Continuity samples about ten times faster than before, and says on "
            "screen how fast it is going and how short a break it can see.",
        ],
    },
    {
        "version": "1.3.0",
        "released": "2026-08-23",
        "title": "Settings, continuity, and one screen",
        "notes": [
            "The whole instrument is now one screen at a time, sized for the "
            "panel, and nothing scrolls. What will not fit gets its own screen.",
            "Sweep settings: Quick, Standard, Thorough and Custom. Each says how "
            "long it will take before you start it, and all four can be edited "
            "and saved to suit the links your shop actually runs.",
            "A stress pattern that flips every bit, which is far harder on a "
            "cable than random data and is what finds a marginal one at high "
            "baud. Thorough uses it.",
            "Repeat passes, keeping the worst result of each. A fault that shows "
            "one time in three is still a fault.",
            "Continuity: watches the cable while you flex it in your hands and "
            "counts every dropout. This finds the cable that passes every other "
            "test here and still fails in service, because it only opens when "
            "it moves.",
        ],
    },
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
