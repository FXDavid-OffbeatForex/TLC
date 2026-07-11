"""Route a verdict to the user's enabled alert channels (PRD §2.15).

Public ships one alert channel — Telegram. `notify_verdict` reads
`alerts.enabled` from config and fans the verdict out; the on-demand flow and
both scheduled engines (agent / api) call the same path, so alerting behaves
identically however the verdict was produced.

CLI:
    python3 -m tlc.notify <verdict.json> [--config config.yaml]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from .config import load_config
from .sinks.telegram import TelegramSink


def build_alert_sinks(config: dict) -> List[object]:
    """Instantiate the alert sinks named in config['alerts']['enabled']."""
    alerts = config.get("alerts") or {}
    enabled = alerts.get("enabled") or []
    sinks: List[object] = []
    for name in enabled:
        if name == "telegram":
            tg = alerts.get("telegram") or {}
            sinks.append(TelegramSink(
                quiet_no_trade=tg.get("quiet_no_trade", True),
                show_pnl=tg.get("show_pnl", False),
                data_dir=config.get("data_dir", "data"),
                pnl_cfg=config.get("pnl") or {},
            ))
        # generic webhook / ntfy / discord are easy future additions here.
    return sinks


def notify_verdict(verdict: dict, config: dict) -> List[str]:
    """Send the verdict to every enabled alert channel. Returns channel names that
    fired; channels that raise (missing token, network) are reported, not fatal."""
    fired: List[str] = []
    for sink in build_alert_sinks(config):
        name = getattr(sink, "name", sink.__class__.__name__)
        try:
            # A sink may return False to say it deliberately suppressed the
            # message (e.g. quiet_no_trade); don't report it as having fired.
            if sink.emit_verdict(verdict) is not False:
                fired.append(name)
        except Exception as exc:  # noqa: BLE001 — one bad channel must not abort
            # A missing token, a network error, or a malformed verdict that trips
            # formatting should degrade gracefully, not kill the scheduled fire.
            print(f"  alert via {name} failed: {exc}", file=sys.stderr)
    return fired


def notify_outcome(outcome: dict, config: dict) -> List[str]:
    """Send a resolved-trade outcome (WIN/LOSS/EXPIRED, from the open-trade gate)
    to every enabled alert channel. Same degrade-and-continue contract as
    notify_verdict: a failing channel is reported, never fatal."""
    fired: List[str] = []
    for sink in build_alert_sinks(config):
        name = getattr(sink, "name", sink.__class__.__name__)
        try:
            sink.emit_outcome(outcome)
            fired.append(name)
        except Exception as exc:  # noqa: BLE001 — one bad channel must not abort
            print(f"  outcome alert via {name} failed: {exc}", file=sys.stderr)
    return fired


def _main() -> int:
    ap = argparse.ArgumentParser(description="Send a verdict to enabled alert channels.")
    ap.add_argument("verdict", help="path to a verdict JSON file")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    with open(args.verdict, encoding="utf-8") as fh:
        verdict = json.load(fh)

    enabled = (cfg.get("alerts") or {}).get("enabled") or []
    if not enabled:
        print("no alert channels enabled (set alerts.enabled: [telegram] in config.yaml)")
        return 0

    fired = notify_verdict(verdict, cfg)
    if fired:
        print(f"alerted: {', '.join(fired)}")
    else:
        print("no alerts sent (see errors above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
