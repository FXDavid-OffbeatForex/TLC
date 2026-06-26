"""Resource + budget + plan calculator for scheduled mode (PRD §2.17).

From `#jobs · interval · engine · platform · council size` it returns:
  1. Feed budget (EXACT): tvremix calls/day vs 20/min · 200/hr · 1,500/day.
  2. LLM cost (engine=api, ESTIMATE): tokens/day → ~$/month.
  3. Resources (HEURISTIC, labelled): vCPU / RAM for the chosen engine.
  4. Plan recommendation: smallest InterServer slice + affiliate link
     (TradingView/Linux), or a deep-link to our Windows VPS calculator (MT5).

InterServer model (source: interserver-slices.md, https://www.interserver.net/vps/):
  linear — $3 / slice, each slice = 2 GB RAM + 40 GB SSD + 2 TB transfer,
  cores = ceil(slices / 2), for slices 1..32.

Surfaced in two places from this one module: the README, and live inside the
`/schedule` set-up step.

CLI:
    python3 -m tlc.vps_calc --jobs 3 --interval 1h --engine api --platform tv
"""

from __future__ import annotations

import argparse
import math
from typing import Dict, Optional

from .cron import fires_per_day, parse_interval

FRAMES_PER_CONVENING = 4                 # 15m / 1h / 4h / 1d
TV_CAPS = {"per_minute": 20, "per_hour": 200, "per_day": 1500}

# Default monetization links (override via config["vps_plans"]).
DEFAULT_INTERSERVER_AFFILIATE = "https://www.interserver.net/vps/?id=579551"
DEFAULT_WINDOWS_CALCULATOR = "https://offbeatforex.com/best-forex-vps/"

# Heuristic per-legend token cost (input+output) for the api engine cost estimate.
TOKENS_PER_LEGEND = 12600
# Rough blended $/1M tokens on a cheap-tier model. A range is shown around it.
USD_PER_MTOK = 0.60


def interserver_slice(n: int) -> Dict[str, float]:
    """Spec for InterServer slice n (1..32)."""
    n = max(1, min(32, n))
    return {
        "slices": n,
        "cores": math.ceil(n / 2),
        "ram_gb": 2 * n,
        "ssd_gb": 40 * n,
        "transfer_tb": 2 * n,
        "price_usd": 3 * n,
    }


def smallest_slice_for(ram_gb: float, cores: float) -> Dict[str, float]:
    """Smallest InterServer slice meeting the RAM and CPU estimate."""
    for n in range(1, 33):
        s = interserver_slice(n)
        if s["ram_gb"] >= ram_gb and s["cores"] >= cores:
            return s
    return interserver_slice(32)


def _resource_estimate(engine: str, concurrency: int) -> Dict[str, float]:
    """Heuristic vCPU/RAM. concurrency = jobs that can fire on the same tick."""
    if engine == "api":                  # I/O-bound Python: light
        ram_gb = 0.25 + 0.13 * concurrency
        cores = max(1, math.ceil(0.3 * concurrency))
    else:                                # agent: Node + CLI + subagents: heavy
        ram_gb = 0.5 + 0.8 * concurrency
        cores = max(1, math.ceil(0.6 * concurrency))
    return {"ram_gb": round(ram_gb, 2), "cores": cores}


def feed_budget(jobs: int, interval, platform: str) -> Optional[Dict[str, object]]:
    """Exact tvremix call budget. None for MT5 (no caps)."""
    if platform == "mt5":
        return None
    fpd = fires_per_day(interval)
    per_day = jobs * fpd * FRAMES_PER_CONVENING
    per_hour = jobs * (fpd / 24.0) * FRAMES_PER_CONVENING
    per_minute_peak = jobs * FRAMES_PER_CONVENING        # worst case: jobs aligned on a tick
    warnings = []
    if per_day > TV_CAPS["per_day"]:
        warnings.append(f"{per_day:.0f} calls/day exceeds {TV_CAPS['per_day']}/day")
    if per_hour > TV_CAPS["per_hour"]:
        warnings.append(f"{per_hour:.0f} calls/hour exceeds {TV_CAPS['per_hour']}/hour")
    if per_minute_peak > TV_CAPS["per_minute"]:
        warnings.append(f"{per_minute_peak} calls/min (peak) exceeds {TV_CAPS['per_minute']}/min")
    return {
        "per_day": round(per_day),
        "per_hour": round(per_hour, 1),
        "per_minute_peak": per_minute_peak,
        "ok": not warnings,
        "warnings": warnings,
    }


def llm_cost(jobs: int, interval, council_size: int) -> Dict[str, float]:
    """Estimated monthly LLM spend for engine=api."""
    tokens_per_day = jobs * fires_per_day(interval) * council_size * TOKENS_PER_LEGEND
    usd_day = tokens_per_day / 1_000_000 * USD_PER_MTOK
    usd_month = usd_day * 30
    return {
        "tokens_per_day": round(tokens_per_day),
        "usd_per_month": round(usd_month, 2),
        "usd_per_month_low": round(usd_month * 0.5, 2),
        "usd_per_month_high": round(usd_month * 2.0, 2),
    }


def estimate(
    jobs: int = 1,
    interval: str = "1h",
    engine: str = "api",
    platform: str = "tv",
    council_size: int = 10,
    concurrency: Optional[int] = None,
    config: Optional[dict] = None,
) -> Dict[str, object]:
    """Full calculation. `platform`: 'tv'|'tradingview' vs 'mt5'."""
    iv = parse_interval(interval)
    plat = "mt5" if platform in ("mt5", "broker") else "tv"
    concurrency = concurrency if concurrency is not None else jobs

    plans = (config or {}).get("vps_plans") or {}
    affiliate = plans.get("interserver_affiliate", DEFAULT_INTERSERVER_AFFILIATE)
    windows_link = plans.get("windows_calculator", DEFAULT_WINDOWS_CALCULATOR)

    res = _resource_estimate(engine, concurrency)
    result: Dict[str, object] = {
        "jobs": jobs,
        "interval": iv.label,
        "fires_per_day": round(fires_per_day(iv), 1),
        "engine": engine,
        "platform": plat,
        "council_size": council_size,
        "resources": res,
        "feed_budget": feed_budget(jobs, iv, plat),
    }

    if engine == "api":
        result["llm_cost"] = llm_cost(jobs, iv, council_size)

    if plat == "mt5":
        result["deploy"] = {
            "lane": "windows",
            "note": "MT5 needs a Windows VPS (MetaTrader must run). Size it on our calculator.",
            "link": windows_link,
        }
    else:
        slice_ = smallest_slice_for(res["ram_gb"], res["cores"])
        result["deploy"] = {
            "lane": "interserver",
            "plan": slice_,
            "link": affiliate,
        }
    return result


def format_report(e: Dict[str, object]) -> str:
    lines = [
        f"Schedule: {e['jobs']} job(s) · every {e['interval']} · "
        f"engine={e['engine']} · {e['platform']}  ({e['fires_per_day']:g}×/day)",
        "─" * 60,
    ]
    fb = e.get("feed_budget")
    if fb:
        flag = "✅" if fb["ok"] else "⚠️"
        lines.append(
            f"Feed budget (TV): {fb['per_day']} calls/day {flag}  "
            f"(caps 1,500/day · 200/hr · 20/min)"
        )
        for w in fb["warnings"]:
            lines.append(f"   ⚠️  {w}")
    else:
        lines.append("Feed budget: n/a (MT5 broker feed — no rate limit or cache)")

    if "llm_cost" in e:
        c = e["llm_cost"]
        lines.append(
            f"LLM cost (est.): ~${c['usd_per_month_low']}–{c['usd_per_month_high']}/month "
            f"(api engine; ~{c['tokens_per_day']:,} tok/day)"
        )

    r = e["resources"]
    lines.append(f"Resources (heuristic): ~{r['cores']} vCPU · {r['ram_gb']} GB RAM")

    d = e["deploy"]
    if d["lane"] == "interserver":
        p = d["plan"]
        lines.append(
            f"Recommended: InterServer {p['slices']}-slice "
            f"({p['cores']} core / {p['ram_gb']} GB / {p['ssd_gb']} GB SSD) "
            f"= ${p['price_usd']}/mo"
        )
        lines.append(f"   → {d['link']}")
    else:
        lines.append(f"Recommended: {d['note']}")
        lines.append(f"   → {d['link']}")
    lines.append("(sizing is a heuristic; feed/cost math is exact)")
    return "\n".join(lines)


def _main() -> int:
    ap = argparse.ArgumentParser(description="Size a VPS for a TLC schedule.")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--interval", default="1h", help="e.g. 15m / 1h / 3d")
    ap.add_argument("--engine", choices=["agent", "api"], default="api")
    ap.add_argument("--platform", choices=["tv", "mt5"], default="tv")
    ap.add_argument("--council-size", type=int, default=10)
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    try:
        from .config import load_config
        cfg = load_config(args.config)
    except Exception:
        cfg = {}

    e = estimate(
        jobs=args.jobs, interval=args.interval, engine=args.engine,
        platform=args.platform, council_size=args.council_size, config=cfg,
    )
    print(format_report(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
