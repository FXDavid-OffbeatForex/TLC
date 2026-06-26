"""Ballot schema, validation, and down-projection to MBT's signal format (PRD §1.3).

A ballot is the unit of a legend's vote. It is a superset of MBT's signal schema
{time, symbol, timeframe, direction, entry, sl, tp, regime}; down-projecting lets
MBT's backtest() score legends with no extra plumbing.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

DIRECTIONS = {"LONG", "SHORT", "FLAT"}
_REQUIRED = ("legend", "symbol", "timeframe", "direction", "conviction")
_DIRECTIONAL_NUMERIC = ("entry", "invalidation", "target")


def is_directional(ballot: dict) -> bool:
    return ballot.get("direction") in {"LONG", "SHORT"}


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_ballot(ballot: dict) -> List[str]:
    """Return a list of validation errors (empty list == valid)."""
    errors: List[str] = []
    if not isinstance(ballot, dict):
        return ["ballot must be an object"]

    for key in _REQUIRED:
        if key not in ballot or ballot[key] in (None, ""):
            errors.append(f"missing required field '{key}'")

    direction = ballot.get("direction")
    if direction is not None and direction not in DIRECTIONS:
        errors.append(f"direction must be one of {sorted(DIRECTIONS)}, got '{direction}'")

    conv = ballot.get("conviction")
    if conv is not None:
        if not _is_number(conv) or not (0.0 <= conv <= 1.0):
            errors.append("conviction must be a number in [0, 1]")

    if is_directional(ballot):
        for key in _DIRECTIONAL_NUMERIC:
            v = ballot.get(key)
            if not _is_number(v) or v <= 0:
                errors.append(f"directional ballot needs positive numeric '{key}'")
        # geometry: invalidation and target on the correct sides of entry
        e, inval, tgt = (ballot.get(k) for k in _DIRECTIONAL_NUMERIC)
        if all(_is_number(x) for x in (e, inval, tgt)):
            if direction == "LONG" and not (inval < e < tgt):
                errors.append("LONG requires invalidation < entry < target")
            if direction == "SHORT" and not (tgt < e < inval):
                errors.append("SHORT requires target < entry < invalidation")

    return errors


def to_mbt_signal(ballot: dict) -> Optional[dict]:
    """Down-project a ballot to MBT's signal schema. FLAT ballots return None."""
    if not is_directional(ballot):
        return None
    return {
        "time": ballot.get("created_at", ""),
        "symbol": ballot["symbol"],
        "timeframe": ballot["timeframe"],
        "direction": ballot["direction"],
        "entry": ballot["entry"],
        "sl": ballot["invalidation"],
        "tp": ballot["target"],
        "regime": ballot.get("regime_assumption", ""),
    }


MBT_SIGNAL_HEADER = ["time", "symbol", "timeframe", "direction", "entry", "sl", "tp", "regime"]


def partition(ballots: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Split ballots into (valid, invalid). Each invalid item carries an '_errors' list."""
    valid, invalid = [], []
    for b in ballots:
        errs = validate_ballot(b)
        if errs:
            invalid.append({**b, "_errors": errs})
        else:
            valid.append(b)
    return valid, invalid
