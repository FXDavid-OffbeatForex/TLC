"""The Chairman: weighted aggregation of ballots → a verdict (PRD §1.4, §2.5).

Public tier weighting is intentionally simple:
    vote_weight = self_conviction × weight_multiplier
where weight_multiplier defaults to 1.0 for every legend (regime_fit and
track_record are premium and ship neutral). The Chairman defaults to NO_TRADE
unless the council earns a trade — disagreement is a position.
"""

from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional

from .ballot import is_directional, partition


def _weight(ballot: dict, weights: Dict[str, float]) -> float:
    mult = float(weights.get(ballot["legend"], 1.0)) if weights else 1.0
    return float(ballot["conviction"]) * mult


def aggregate(
    ballots: List[dict],
    weights: Optional[Dict[str, float]] = None,
    threshold: float = 0.65,
    regime: str = "",
    as_of: str = "",
) -> dict:
    """Aggregate validated ballots into a verdict. Invalid ballots are dropped."""
    weights = weights or {}
    valid, _invalid = partition(ballots)

    long_w = sum(_weight(b, weights) for b in valid if b["direction"] == "LONG")
    short_w = sum(_weight(b, weights) for b in valid if b["direction"] == "SHORT")
    directional_w = long_w + short_w

    for_legends = []
    against_legends = []
    abstain = [b["legend"] for b in valid if not is_directional(b)]

    base = {
        "symbol": (valid[0]["symbol"] if valid else ""),
        "regime": regime,
        "for": [],
        "against": [],
        "abstain": abstain,
        "created_at": as_of,
    }

    if directional_w == 0 or long_w == short_w:
        return {
            **base,
            "decision": "NO_TRADE",
            "consensus": 0.0,
            "rationale": "No directional majority — council split or flat. Standing aside.",
        }

    winner = "LONG" if long_w > short_w else "SHORT"
    winner_w = max(long_w, short_w)
    consensus = round(winner_w / directional_w, 4)

    winning = [b for b in valid if b["direction"] == winner]
    losing = [b for b in valid if is_directional(b) and b["direction"] != winner]
    for_legends = [b["legend"] for b in winning]
    against_legends = [b["legend"] for b in losing]

    if consensus < threshold:
        return {
            **base,
            "decision": "NO_TRADE",
            "consensus": consensus,
            "for": for_legends,
            "against": against_legends,
            "rationale": (
                f"{winner} leaning but weighted consensus {consensus:.0%} "
                f"below threshold {threshold:.0%}. Standing aside."
            ),
        }

    entry = round(median([b["entry"] for b in winning]), 8)
    stop = round(median([b["invalidation"] for b in winning]), 8)
    target = round(median([b["target"] for b in winning]), 8)
    risk = abs(entry - stop)
    rr = round(abs(target - entry) / risk, 2) if risk > 0 else None
    avg_conv = sum(b["conviction"] for b in winning) / len(winning)
    size_fraction = round(min(1.0, consensus * avg_conv), 2)

    return {
        **base,
        "decision": winner,
        "consensus": consensus,
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr": rr,
        "size_fraction": size_fraction,
        "for": for_legends,
        "against": against_legends,
        "rationale": (
            f"{len(winning)}/{len(valid)} legends weighted {winner} "
            f"(consensus {consensus:.0%}); stop {stop} from clustered invalidations, "
            f"target {target}, R:R {rr}."
        ),
    }
