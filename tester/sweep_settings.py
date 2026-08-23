"""Named sweep settings, and where they are kept.

The sweep has knobs: which rates, how long to push at each, how many passes,
which parities, and what byte pattern.  Exposing those to a technician as a
page of numbers was the wrong shape.  Nobody at a bench knows what to set
"payload per rate" to, and the previous UI asked exactly that.

So the knobs live behind four named settings, and the settings are what a
technician chooses between.  All four are editable and saved, not just Custom:
a shop whose links all run at 9600 should be able to redefine Standard so it
stops spending a minute on 115200 that nobody will ever use.

**Each one states its time cost**, which is the part that makes this work. A
technician choosing a ten minute test has to see "10 min" before committing,
or they start it, walk away, and come back to a half-finished bench.

Stored as JSON beside the code, like the profile store used to be. Unlike that
store this needs no typing to use: the factory settings are usable as they
stand, and editing one is a numeric adjustment rather than naming something.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Dict, List, Optional

from .serial_tests import BAUD_RATES, MAX_PAYLOAD_SECONDS, MIN_PAYLOAD_SECONDS

SETTINGS_PATH = os.environ.get(
    "CABLETESTER_SWEEP_SETTINGS",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "sweep-settings.json"),
)

#: Byte patterns. Random is the historical default and is a fair average case.
#: Stress is the one worth knowing about: alternating bits every clock is the
#: worst case for slew rate and cable capacitance, which is exactly what kills
#: a marginal cable at high baud, and a pseudorandom payload averages that
#: stress away. A "thorough" setting that is merely longer is not much harder.
PATTERNS = {
    "random": "Pseudorandom. A fair average case.",
    "stress": "Alternating bits (0x55). Worst case for slew rate and capacitance.",
    "dc": "All ones then all zeros. Worst case for DC balance.",
}

PARITIES = {
    "none": ["none"],
    "even": ["even"],
    "both": ["none", "even"],
}

FACTORY: List[dict] = [
    {
        "id": "quick",
        "name": "Quick",
        "summary": "Three rates, half a second each. Catches an obviously bad cable.",
        "rates": [9600, 19200, 115200],
        "payload_seconds": 0.5,
        "passes": 1,
        "parity": "none",
        "pattern": "random",
    },
    {
        "id": "standard",
        "name": "Standard",
        "summary": "All eight rates, both parities. The everyday check.",
        "rates": list(BAUD_RATES),
        "payload_seconds": 2.0,
        "passes": 1,
        "parity": "both",
        "pattern": "random",
    },
    {
        "id": "thorough",
        "name": "Thorough",
        "summary": "All eight, three passes, stress pattern. For a cable going into service.",
        "rates": list(BAUD_RATES),
        "payload_seconds": 5.0,
        "passes": 3,
        "parity": "both",
        "pattern": "stress",
    },
    {
        "id": "custom",
        "name": "Custom",
        "summary": "Yours to set.",
        "rates": list(BAUD_RATES),
        "payload_seconds": 2.0,
        "passes": 1,
        "parity": "both",
        "pattern": "random",
    },
]


def estimate_seconds(setting: dict) -> float:
    """Roughly how long this setting will take, for the button that starts it.

    The payload time is exact by construction: payload_for sizes each rate's
    bytes so the transfer takes the requested seconds. What is estimated is the
    overhead, which is a port open and a line settle per run.
    """
    per_run_overhead = 0.45
    runs = len(PARITIES.get(setting["parity"], ["none"])) * max(1, int(setting["passes"]))
    rates = len(setting["rates"]) or 1
    return round(rates * runs * (float(setting["payload_seconds"]) + per_run_overhead), 1)


def describe_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{int(round(seconds))} s"
    return f"{int(round(seconds / 60.0))} min"


def _clean(setting: dict, factory: dict) -> dict:
    """Validate one setting, falling back to the factory value field by field.

    A stored file is edited by hand sooner or later, and a bad value there must
    degrade to something sensible rather than crash the instrument at the point
    a technician presses start.
    """
    out = dict(factory)
    out["name"] = str(setting.get("name") or factory["name"])[:24]
    out["summary"] = str(setting.get("summary") or factory["summary"])[:160]

    rates = [r for r in (setting.get("rates") or []) if r in BAUD_RATES]
    out["rates"] = sorted(set(rates)) or list(factory["rates"])

    try:
        secs = float(setting.get("payload_seconds", factory["payload_seconds"]))
    except (TypeError, ValueError):
        secs = factory["payload_seconds"]
    out["payload_seconds"] = max(MIN_PAYLOAD_SECONDS, min(MAX_PAYLOAD_SECONDS, secs))

    try:
        passes = int(setting.get("passes", factory["passes"]))
    except (TypeError, ValueError):
        passes = factory["passes"]
    out["passes"] = max(1, min(10, passes))

    out["parity"] = setting.get("parity") if setting.get("parity") in PARITIES else factory["parity"]
    out["pattern"] = setting.get("pattern") if setting.get("pattern") in PATTERNS else factory["pattern"]
    return out


def load() -> List[dict]:
    """Every setting, factory values where nothing has been saved."""
    stored: Dict[str, dict] = {}
    try:
        with open(SETTINGS_PATH) as fh:
            for entry in json.load(fh):
                if isinstance(entry, dict) and entry.get("id"):
                    stored[entry["id"]] = entry
    except (OSError, ValueError):
        pass
    out = []
    for factory in FACTORY:
        merged = _clean(stored.get(factory["id"], {}), factory)
        merged["id"] = factory["id"]
        merged["seconds"] = estimate_seconds(merged)
        merged["duration"] = describe_duration(merged["seconds"])
        merged["modified"] = merged.get("id") in stored
        out.append(merged)
    return out


def get(setting_id: str) -> Optional[dict]:
    for s in load():
        if s["id"] == setting_id:
            return s
    return None


def save(setting_id: str, changes: dict) -> dict:
    factory = next((f for f in FACTORY if f["id"] == setting_id), None)
    if factory is None:
        raise ValueError(f"No sweep setting called '{setting_id}'.")
    current = {s["id"]: s for s in load()}
    merged = _clean({**current[setting_id], **(changes or {})}, factory)
    merged["id"] = setting_id
    keep = [{k: v for k, v in (current[f["id"]] if f["id"] != setting_id else merged).items()
             if k not in ("seconds", "duration", "modified")}
            for f in FACTORY]
    _write(keep)
    return get(setting_id)


def reset() -> List[dict]:
    try:
        os.remove(SETTINGS_PATH)
    except OSError:
        pass
    return load()


def _write(settings: List[dict]) -> None:
    """Atomic, so a power cut mid-write cannot leave a half-file.

    This box gets its power yanked; that is the whole premise of the kiosk
    handling elsewhere. A truncated settings file would take the instrument
    down at the next boot.
    """
    directory = os.path.dirname(os.path.abspath(SETTINGS_PATH)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(settings, fh, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
