"""Health score calculation.

The score answers one question: "how much of the useful speed range does this
cable actually deliver?"  Higher baud rates are weighted more heavily, because
a cable that only works slowly is only fit for slow work.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Weight per baud rate.  Sum = 35.
BAUD_WEIGHTS: Dict[int, int] = {
    1200: 1,
    2400: 1,
    4800: 2,
    9600: 3,
    19200: 4,
    38400: 6,
    57600: 8,
    115200: 10,
}

# Bit error rate at or below which a rate is "marginal" rather than "failed".
MARGINAL_BER = 1e-3

CLEAN = "clean"
MARGINAL = "marginal"
FAIL = "fail"

BAND_GREEN = "green"
BAND_AMBER = "amber"
BAND_RED = "red"


def classify_run(run: Optional[dict]) -> str:
    """Classify a single parity run of a single baud rate."""
    if not run or run.get("error"):
        return FAIL
    sent = run.get("sent", 0)
    if sent == 0 or run.get("received", 0) == 0:
        return FAIL
    if run.get("mismatched", 0) == 0 and run.get("missing", 0) == 0:
        return CLEAN
    if run.get("ber", 1.0) <= MARGINAL_BER:
        return MARGINAL
    return FAIL


# credit[(none_run_class, parity_run_class)] -> fraction of this rate's weight
_CREDIT = {
    (CLEAN, CLEAN): 1.0,
    (CLEAN, MARGINAL): 0.8,
    (CLEAN, FAIL): 0.6,
    (MARGINAL, CLEAN): 0.4,
    (MARGINAL, MARGINAL): 0.4,
    (MARGINAL, FAIL): 0.3,
    (FAIL, CLEAN): 0.0,
    (FAIL, MARGINAL): 0.0,
    (FAIL, FAIL): 0.0,
}


def rate_credit(none_run: Optional[dict], parity_run: Optional[dict]) -> float:
    """Partial credit (0.0-1.0) earned by one baud rate."""
    return _CREDIT[(classify_run(none_run), classify_run(parity_run))]


def rate_status(credit: float) -> str:
    """UI status for a rate given its credit."""
    if credit >= 0.6:
        return "pass"
    if credit > 0.0:
        return "marginal"
    return "fail"


def band(score: float) -> str:
    if score >= 85:
        return BAND_GREEN
    if score >= 60:
        return BAND_AMBER
    return BAND_RED


def score_sweep(rates: List[dict]) -> dict:
    """Score a completed (or partial) baud sweep.

    ``rates`` is a list of per-rate dicts as produced by serial_tests.run_baud_sweep:
    ``{"baud": int, "runs": {"none": {...}, "even": {...}}}``.

    Rates that were never run (sweep cancelled or aborted) are excluded from the
    denominator, and ``coverage`` reports how much of the range was measured, so
    a half-finished sweep is not silently reported as a passing cable.
    """
    total_weight = 0
    earned = 0.0
    per_rate = []
    for entry in rates:
        baud = entry["baud"]
        weight = BAUD_WEIGHTS.get(baud, 1)
        runs = entry.get("runs") or {}
        none_run = runs.get("none")
        parity_run = runs.get("even")
        if none_run is None and parity_run is None:
            continue
        credit = rate_credit(none_run, parity_run)
        total_weight += weight
        earned += weight * credit
        per_rate.append(
            {
                "baud": baud,
                "weight": weight,
                "credit": credit,
                "status": rate_status(credit),
                "none": classify_run(none_run),
                "even": classify_run(parity_run),
            }
        )

    score = (earned / total_weight * 100.0) if total_weight else 0.0
    all_weight = sum(BAUD_WEIGHTS.values())
    return {
        "score": round(score, 1),
        "band": band(score),
        "verdict": verdict_text(per_rate),
        "max_reliable_baud": max_reliable_baud(per_rate),
        "coverage": round(total_weight / all_weight * 100.0, 1),
        "per_rate": per_rate,
        "weights": BAUD_WEIGHTS,
    }


def max_reliable_baud(per_rate: List[dict]) -> Optional[int]:
    """Highest baud rate reachable with every rate below it also reliable.

    "Reliable" means credit >= 0.8: byte-perfect with no parity mode, and at
    worst slightly degraded with even parity.
    """
    best = None
    for entry in sorted(per_rate, key=lambda e: e["baud"]):
        if entry["credit"] >= 0.8:
            best = entry["baud"]
        else:
            break
    return best


def verdict_text(per_rate: List[dict]) -> str:
    """One line of plain English for the technician."""
    if not per_rate:
        return "No baud sweep data."

    tested = sorted(per_rate, key=lambda e: e["baud"])
    top = tested[-1]["baud"]
    reliable = max_reliable_baud(tested)

    if reliable is None:
        if all(e["credit"] == 0.0 for e in tested):
            return "No reliable communication at any baud rate. Cable is not usable."
        return (
            "Errors at every rate including 1200 baud. Cable is degraded, replace it."
        )

    if reliable == top:
        degraded = [e["baud"] for e in tested if e["credit"] < 1.0]
        if degraded:
            return (
                f"Clean to {top} baud, with elevated parity-mode errors at "
                f"{', '.join(str(b) for b in degraded)}. Usable, but watch it."
            )
        return f"Clean at every rate to {top} baud. Cable is good for full-speed use."

    failed = [e["baud"] for e in tested if e["baud"] > reliable and e["credit"] == 0.0]
    if failed:
        return (
            f"Good to {reliable} baud. Fails at {failed[0]} and above, "
            "not suitable for high-speed use."
        )
    return (
        f"Good to {reliable} baud. Errors above that, "
        "not suitable for high-speed use."
    )
