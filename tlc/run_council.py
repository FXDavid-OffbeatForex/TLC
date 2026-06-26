"""Aggregate a set of ballots into a verdict and persist both (PRD §2.4 step 3).

Usage:
    python3 -m tlc.run_council <ballots.json> [--config config.yaml]

`ballots.json` is a JSON array of ballot objects (one per legend). Invalid
ballots are reported and dropped. The verdict is printed and, together with the
ballots, written through the LocalJsonSink so local scoring can pick them up.
"""

from __future__ import annotations

import argparse
import json
import sys

from .ballot import partition
from .chairman import aggregate
from .config import load_config
from .sinks import LocalJsonSink


def _main() -> int:
    ap = argparse.ArgumentParser(description="Run the Chairman over a set of ballots.")
    ap.add_argument("ballots", help="path to a JSON array of ballots")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-save", action="store_true", help="do not write to the sink")
    args = ap.parse_args()

    cfg = load_config(args.config)
    with open(args.ballots) as fh:
        ballots = json.load(fh)
    if not isinstance(ballots, list):
        print("error: ballots file must contain a JSON array", file=sys.stderr)
        return 2

    valid, invalid = partition(ballots)
    for bad in invalid:
        print(f"  dropped {bad.get('legend','?')}: {bad['_errors']}", file=sys.stderr)

    verdict = aggregate(
        valid,
        weights=cfg.get("weights", {}),
        threshold=cfg.get("consensus_threshold", 0.65),
        as_of=(valid[0].get("created_at", "") if valid else ""),
    )

    if not args.no_save:
        sink = LocalJsonSink(cfg.get("data_dir", "data"))
        for b in valid:
            sink.emit_ballot(b)
        sink.emit_verdict(verdict)

    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
