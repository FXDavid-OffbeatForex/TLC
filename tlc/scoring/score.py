"""Turn saved ballots into an MBT signal CSV and (optionally) backtest them.

Usage:
    python -m tlc.scoring.score data/ballots.jsonl signals.csv [--legend gann]

The CSV header matches MBT's SignalLogger output exactly, so MBT's `backtest`
tool / core.backtest.run_backtest can consume it directly. Per-legend filtering
gives you the raw material for a leaderboard.
"""

from __future__ import annotations

import argparse
import csv
import json
from typing import Iterable, List, Optional

from ..ballot import MBT_SIGNAL_HEADER, to_mbt_signal, validate_ballot


def load_ballots(path: str) -> List[dict]:
    rows: List[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def to_signal_rows(ballots: Iterable[dict], legend: Optional[str] = None) -> List[dict]:
    rows = []
    for b in ballots:
        if legend and b.get("legend", "").lower() != legend.lower():
            continue
        # A partial/hand-edited line in ballots.jsonl could be directional yet
        # missing entry/invalidation/target; validate first so to_mbt_signal's
        # direct field access can't KeyError and abort the whole run.
        if validate_ballot(b):
            continue
        sig = to_mbt_signal(b)
        if sig is not None:
            rows.append(sig)
    return rows


def write_csv(rows: List[dict], out_path: str) -> int:
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MBT_SIGNAL_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return len(rows)


def _main() -> int:
    ap = argparse.ArgumentParser(description="Down-project ballots to an MBT signal CSV.")
    ap.add_argument("ballots", help="path to ballots.jsonl")
    ap.add_argument("out", help="output signals CSV")
    ap.add_argument("--legend", help="filter to one legend id", default=None)
    args = ap.parse_args()

    ballots = load_ballots(args.ballots)
    rows = to_signal_rows(ballots, args.legend)
    n = write_csv(rows, args.out)
    scope = f" for legend '{args.legend}'" if args.legend else ""
    print(f"wrote {n} signal rows{scope} → {args.out}")
    print("Next: run MBT `backtest` on this CSV (requires MT5) to score it in R.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
