"""Reference signatures and learned "known-good" profiles.

A *signature* is the empirical stimulus/response map recorded by the pin check:
which output line, when asserted, produced a response on which input lines, plus
whether the 2/3 data path looped back.  Topology is identified by comparing the
observed signature against references rather than by trusting a hardcoded pin
map, because real cables vary.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Dict, List, Optional

OUTPUT_LINES = ["DTR", "RTS"]
INPUT_LINES = ["CTS", "DSR", "DCD", "RI"]

DEFAULT_PROFILE_PATH = os.environ.get(
    "CABLETESTER_PROFILES",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles.json"),
)


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
# are electrically indistinguishable — a null modem crosses 2/3, 7/8 and 4/6,
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
            "type, not necessarily a fault — but hardware flow control will not "
            "work over it."
        ),
    },
    {
        "id": "handshake_only",
        "name": "Handshake only — data path open",
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


def identify(signature: dict, learned: Optional[List[dict]] = None) -> dict:
    """Compare a signature against learned profiles first, then built-ins.

    Returns ``{"kind": ..., "matches": [...], "signature": ...}`` where kind is
    one of ``learned``, ``match``, ``ambiguous`` or ``unknown``.
    """
    learned = learned or []

    learned_hits = [p for p in learned if p.get("signature") == signature]
    if learned_hits:
        return {
            "kind": "learned",
            "matches": learned_hits,
            "signature": signature,
            "label": learned_hits[0]["name"]
            if len(learned_hits) == 1
            else " / ".join(p["name"] for p in learned_hits),
        }

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


class ProfileStore:
    """Learned known-good profiles, persisted as a small JSON file."""

    def __init__(self, path: str = DEFAULT_PROFILE_PATH):
        self.path = path

    def load(self) -> List[dict]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        profiles = data.get("profiles") if isinstance(data, dict) else data
        return profiles if isinstance(profiles, list) else []

    def _write(self, profiles: List[dict]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", dir=directory, delete=False, encoding="utf-8", suffix=".tmp"
        )
        try:
            json.dump({"version": 1, "profiles": profiles}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(handle.name, self.path)
        except BaseException:
            handle.close()
            if os.path.exists(handle.name):
                os.unlink(handle.name)
            raise

    @staticmethod
    def slug(name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        return base or "profile"

    def save(self, name: str, signature: dict, notes: str = "", extra: Optional[dict] = None) -> dict:
        """Add or replace a learned profile. Names are unique (case-insensitive)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Profile name is required.")
        profiles = [p for p in self.load() if p.get("name", "").lower() != name.lower()]
        profile = {
            "id": self.slug(name),
            "name": name,
            "builtin": False,
            "signature": signature,
            "note": notes,
            "learned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if extra:
            profile.update(extra)
        profiles.append(profile)
        self._write(profiles)
        return profile

    def delete(self, profile_id: str) -> bool:
        profiles = self.load()
        remaining = [p for p in profiles if p.get("id") != profile_id]
        if len(remaining) == len(profiles):
            return False
        self._write(remaining)
        return True
