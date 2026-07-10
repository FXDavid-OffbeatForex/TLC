"""Aggregate a set of ballots into a verdict and persist both (PRD §2.4 step 3).

Usage:
    python3 -m tlc.run_council <ballots.json> [--config config.yaml] [--alert]

`ballots.json` is a JSON array of ballot objects (one per legend). Invalid
ballots are reported and dropped. The verdict is printed and, together with the
ballots, written through the LocalJsonSink so local scoring can pick them up.

`--alert` additionally pushes the verdict to the channels in `alerts.enabled`
(same path as scheduled fires; a no-op when none are configured, and NO_TRADE
respects `quiet_no_trade`) — this is how an on-demand convene alerts, per
PRD §2.15's "same alerting however the verdict was produced".
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
    ap.add_argument("--alert", action="store_true",
                    help="push the verdict to enabled alert channels")
    args = ap.parse_args()

    cfg = load_config(args.config)
    with open(args.ballots, encoding="utf-8") as fh:
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
        timeframe=(valid[0].get("timeframe", "") if valid else ""),
    )

    if not args.no_save:
        sink = LocalJsonSink(cfg.get("data_dir", "data"))
        for b in valid:
            sink.emit_ballot(b)
        sink.emit_verdict(verdict)

    if args.alert:
        from .notify import notify_verdict
        fired = notify_verdict(verdict, cfg)
        if fired:
            print(f"alerted: {', '.join(fired)}", file=sys.stderr)

    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
