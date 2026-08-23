"""Reference signatures for identifying a cable's topology.

A *signature* is the empirical stimulus/response map recorded by the pin check:
which output line, when asserted, produced a response on which input lines, plus
whether the 2/3 data path looped back.  Topology is identified by comparing the
observed signature against references rather than by trusting a hardcoded pin
map, because real cables vary.

There used to be a learn-and-save layer here so a nonstandard-but-correct cable
could be recognised by name. It was removed on 8/23/2026 and the reasoning is
in DOC 12: its only interaction was typing a name into a prompt, which was
reasonable when this ran on a laptop and is not on a keyboardless panel, and
"matches your reference cable" implied a claim about quality that a wiring
signature cannot make. The built-in references below cover straight-through,
null modem and 3-wire, which is essentially every RS-232 cable in the field.
"""

from __future__ import annotations

import re
from typing import Dict, List

OUTPUT_LINES = ["DTR", "RTS"]
INPUT_LINES = ["CTS", "DSR", "DCD", "RI"]

def canonical(matrix: Dict[str, Dict[str, bool]], data_loopback: bool) -> dict:
    """Normalise a raw stimulus/response matrix into a comparable signature."""
    sig = {}
    for out in OUTPUT_LINES:
        responses = (matrix or {}).get(out) or {}
        sig[out] = sorted(inp for inp in INPUT_LINES if responses.get(inp))
    sig["data"] = bool(data_loopback)
    return sig


# ---------------------------------------------------------------------------
# Built-in references
#
# All of these describe what the tester sees with the standard loopback plug
# (2-3, 7-8, 4-1-6) fitted to the FAR end of the cable under test.
#
# Note on straight-through vs null modem: with a symmetric loopback plug the two
# are electrically indistinguishable: a null modem crosses 2/3, 7/8 and 4/6,
# and the plug crosses them straight back again.  Both signatures are shipped so
# the tester reports the ambiguity honestly instead of guessing.
# ---------------------------------------------------------------------------
BUILTIN_PROFILES: List[dict] = [
    {
        "id": "straight_through",
        "name": "Straight-through (full handshake)",
        "builtin": True,
        "signature": {"DTR": ["DCD", "DSR"], "RTS": ["CTS"], "data": True},
        "observation": False,
        "note": (
            "Pin N to pin N, all nine conductors. Electrically indistinguishable "
            "from a null modem through a symmetric loopback plug."
        ),
    },
    {
        "id": "null_modem",
        "name": "Null modem (2/3, 7/8, 4/6 crossed)",
        "builtin": True,
        "signature": {"DTR": ["DCD", "DSR"], "RTS": ["CTS"], "data": True},
        "observation": False,
        "note": (
            "Crossed cable. The loopback plug crosses the same pairs back, so it "
            "presents the same matrix as a straight-through cable."
        ),
    },
    {
        "id": "three_wire",
        "name": "3-wire (2, 3, 5 only)",
        "builtin": True,
        "signature": {"DTR": [], "RTS": [], "data": True},
        "observation": True,
        "note": (
            "Data passes; every handshake line reads open. This is a valid cable "
            "type, not necessarily a fault, but hardware flow control will not "
            "work over it."
        ),
    },
    {
        "id": "handshake_only",
        "name": "Handshake only, data path open",
        "builtin": True,
        "signature": {"DTR": ["DCD", "DSR"], "RTS": ["CTS"], "data": False},
        "observation": False,
        "note": "Control lines are intact but pin 2 or pin 3 is broken.",
    },
    {
        "id": "dead",
        "name": "No continuity",
        "builtin": True,
        "signature": {"DTR": [], "RTS": [], "data": False},
        "observation": False,
        "note": (
            "Nothing responded. Check that the loopback plug is fitted and that "
            "the cable is seated at both ends before condemning it."
        ),
    },
]


def identify(signature: dict) -> dict:
    """Match an observed signature against the built-in references.

    Returns ``{"kind": ..., "matches": [...], "signature": ...}`` where kind is
    one of ``match``, ``ambiguous`` or ``unknown``.
    """

    hits = [p for p in BUILTIN_PROFILES if p["signature"] == signature]
    if len(hits) == 1:
        return {
            "kind": "match",
            "matches": hits,
            "signature": signature,
            "label": hits[0]["name"],
        }
    if len(hits) > 1:
        return {
            "kind": "ambiguous",
            "matches": hits,
            "signature": signature,
            "label": " or ".join(p["name"] for p in hits),
        }
    return {
        "kind": "unknown",
        "matches": [],
        "signature": signature,
        "label": "Non-standard",
    }


def describe(signature: dict) -> List[str]:
    """Human-readable rendering of an observed signature."""
    lines = []
    for out in OUTPUT_LINES:
        responders = signature.get(out) or []
        lines.append(
            f"{out} -> {', '.join(responders)}" if responders else f"{out} -> (nothing)"
        )
    lines.append(
        "TXD/RXD (2/3) -> loops back" if signature.get("data") else "TXD/RXD (2/3) -> open"
    )
    return lines
