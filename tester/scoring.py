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


#: Credit when only ONE parity mode was measured at this rate.
#:
#: Not measuring something is not the same as it failing, and the pair table
#: above cannot express the difference because classify_run(None) is `fail`.
#: A sweep setting that runs no parity only used to be scored as though every
#: even-parity run had failed: every rate capped at 0.6, the whole score capped
#: at 60 on a flawless cable, and the verdict read "errors at every rate" over
#: a table showing PASS on every row.
#:
#: A clean run earns this rate its full weight. The even-parity pass is a
#: timing stressor rather than an independent check of the cable (both ends of
#: the loopback are the same UART), so its absence is a narrower test, not a
#: worse cable. How much of the range was measured is reported by `coverage`,
#: which is where a partial sweep belongs.
_SOLO_CREDIT = {CLEAN: 1.0, MARGINAL: 0.4, FAIL: 0.0}


def rate_credit(none_run: Optional[dict], parity_run: Optional[dict]) -> float:
    """Partial credit (0.0-1.0) earned by one baud rate.

    A run of ``None`` means that parity mode was never attempted, which is
    scored on what WAS measured rather than as a failure.
    """
    if none_run is None and parity_run is None:
        return 0.0
    if parity_run is None:
        return _SOLO_CREDIT[classify_run(none_run)]
    if none_run is None:
        return _SOLO_CREDIT[classify_run(parity_run)]
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
        # Name the lowest rate ACTUALLY swept. This said "including 1200 baud"
        # whatever was run, so a sweep that started at 9600 accused a rate it
        # had never tried, which is the kind of detail that costs a technician
        # their trust in the whole instrument.
        return (
            f"Errors at every rate including {tested[0]['baud']} baud. "
            f"Cable is degraded, replace it."
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


# ---------------------------------------------------------------------------
# Ethernet: the link-speed ladder
#
# Deliberately NOT the weighted-sum shape used for baud rates above. There are
# only three rungs and they are pass/fail, so a weighted sum would imply a
# resolution the measurement does not have. Four outcomes are possible, and
# each one is a different cable, so they are scored as a table.
#
# The numbers are chosen so the bands say the right thing:
#   gigabit        -> 100, green.  A sound cable.
#   100 but not 1k ->  62, amber.  Two pairs are dead. It will carry a 100Mb
#                      device perfectly well and will silently fail to
#                      negotiate gigabit, which is the failure worth flagging.
#   10 but not 100 ->  22, red.    Marginal on the pairs everything needs.
#   nothing        ->   0, red.
#
# The 100-only case is the one worth arguing about, and it is a judgement
# call: 62 treats a 100Mb-capable cable as usable-with-reservations rather
# than failed, because a great deal of industrial gear is 100Mb only. A plant
# standardising on gigabit would want that number lower. See DOC 5.
# ---------------------------------------------------------------------------

ETH_SCORES: Dict[int, float] = {1000: 100.0, 100: 62.0, 10: 22.0, 0: 0.0}


def best_link_speed(rungs: List[dict]) -> int:
    """Highest speed that actually linked. 0 if none did.

    A rung flagged with an anomaly is excluded: the adapter did not honour the
    advertisement, so the result describes the adapter rather than the cable.
    """
    linked = [r["speed"] for r in rungs if r.get("link") and not r.get("anomaly")]
    return max(linked) if linked else 0


def score_link_ladder(rungs: List[dict]) -> dict:
    """Score a completed (or partial) ethernet speed ladder."""
    best = best_link_speed(rungs)
    score = ETH_SCORES.get(best, 0.0)
    attempted = [r["speed"] for r in rungs]
    coverage = len(attempted) / float(len(ETH_SCORES) - 1) if attempted else 0.0

    # A gap in the middle is not a cable this model describes: a cable that
    # links at 1000 but not at 100 is not physically sensible, so it means the
    # test misbehaved rather than that the cable is exotic.
    linked = {r["speed"] for r in rungs if r.get("link")}
    inconsistent = bool(linked) and any(
        s < max(linked) and s in attempted and s not in linked for s in (10, 100)
    )

    # An inconsistent ladder must never present as a healthy cable. Scoring it
    # on the highest rung that linked would put a green gauge above a verdict
    # saying the measurement is untrustworthy, and the gauge is what gets read
    # from across a bench. Red is not a claim that the cable is dead; it is a
    # refusal to report a number this measurement did not earn, and it puts the
    # tech where they should be, which is running it again.
    if inconsistent:
        score = 0.0

    return {
        "score": round(score, 1),
        "band": band(score),
        "best_speed": best,
        "coverage": round(min(1.0, coverage), 3),
        "inconsistent": inconsistent,
        "suspect_pairs": eth_suspect_pairs(best),
        "verdict": eth_verdict_text(best, inconsistent),
    }


def eth_suspect_pairs(best: int) -> Optional[str]:
    """Which conductors the failure points at.

    This is the whole reason a speed ladder beats a simple link check: 10 and
    100BASE-T use only pairs 1-2 and 3-6, while 1000BASE-T needs all four. So
    the highest speed that links localises the fault without reflectometry.
    """
    if best >= 1000:
        return None
    if best == 100:
        return "4-5 and 7-8 (blue and brown)"
    if best == 10:
        return "1-2 or 3-6, marginal (orange and green)"
    return "1-2 or 3-6, open or shorted (orange and green)"


def eth_verdict_text(best: int, inconsistent: bool = False) -> str:
    if inconsistent:
        return (
            "Inconsistent result. A cable cannot link at a high speed and fail a "
            "lower one, so this is the test misbehaving rather than the cable. "
            "Re-run it, and check both plugs are seated."
        )
    if best >= 1000:
        return "Good to gigabit. All four pairs carrying."
    if best == 100:
        return (
            "100 Mb only. Will not negotiate gigabit, because the blue and brown "
            "pairs are not carrying. Fine for a 100 Mb device, and a gigabit one "
            "will quietly fall back to 100 without telling anyone."
        )
    if best == 10:
        return (
            "10 Mb only. The pairs every speed depends on are marginal. "
            "Do not put this cable into service."
        )
    return (
        "No link at any speed. Pair 1-2 or 3-6 is open or shorted. "
        "Check both plugs before condemning the cable."
    )
