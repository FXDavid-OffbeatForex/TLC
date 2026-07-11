"""Running PnL / trade statistics for a schedule (PRD §2.15 alert footer).

Every resolved scheduled trade is already appended to `data/outcomes.jsonl` by
the open-trade gate (`trade_gate.build_outcome`), each row carrying an
R-multiple (`r`: +reward/risk on a win, -1.0 on a loss, 0.0 on an expire) plus
the schedule `name` and its `started_at`. This module aggregates that ledger
into the running stats a Telegram alert shows as a footer -- trades closed, win
rate, net R, profit factor, expectancy, max drawdown -- scoped to ONE schedule
SINCE IT STARTED.

R is the native, account-agnostic unit. When `pnl.account_balance` +
`pnl.risk_per_trade_pct` are configured, a fixed-fractional CURRENCY estimate is
layered on top: per-trade cash = balance * pct/100, so cash = R * that. It is
NON-compounding and an ESTIMATE -- it assumes every trade risked the same
nominal amount, which is what a fixed-fractional trader targets but not exactly
what a broker fills.

No imports from trade_gate / notify / sinks: this module must stay importable
from the Telegram sink without a circular import. Outcomes are matched to the
current verdict by RAW (symbol, timeframe, platform) -- both originate from the
same native verdict, so no cross-platform symbol normalisation is needed here.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional


def load_outcomes(data_dir: str) -> List[dict]:
    """Every parseable record in outcomes.jsonl, in resolution (append) order.

    errors="replace" + skip-bad-line: a legacy locale-encoded or half-written
    line degrades to nothing, never a raise (same contract as
    trade_gate._read_verdict_lines) -- a stats footer must not break alerting.
    """
    path = os.path.join(data_dir, "outcomes.jsonl")
    if not os.path.exists(path):
        return []
    rows: List[dict] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _matches(o: dict, symbol: str, timeframe: str, platform: str) -> bool:
    """Same schedule identity as the verdict being alerted. Raw equality is
    correct: outcome['symbol'] is the verdict's own native symbol (broker suffix
    / exchange prefix included), so it matches the verdict we're footing."""
    if symbol and str(o.get("symbol", "")) != str(symbol):
        return False
    if timeframe and str(o.get("timeframe", "")) != str(timeframe):
        return False
    # platform may be absent on very old rows; only filter when both sides have it
    if platform and o.get("platform") and str(o.get("platform")) != str(platform):
        return False
    return True


def select_since_start(rows: List[dict]) -> List[dict]:
    """Keep only the CURRENT schedule run: the rows sharing the latest
    `started_at`. A schedule that was cleared/restarted gets a new started_at, so
    this drops a prior run's trades from the 'since start' window. Rows with no
    started_at (legacy) form their own group and win only if nothing newer
    exists."""
    if not rows:
        return []
    starts = {str(r.get("started_at", "")) for r in rows}
    if len(starts) <= 1:
        return rows
    latest = max(starts)  # ISO-like "%Y-%m-%d %H:%M" sorts lexically = chronologically
    return [r for r in rows if str(r.get("started_at", "")) == latest]


def compute(rows: List[dict], risk_cash: Optional[float] = None,
            currency: str = "USD") -> Optional[Dict]:
    """Aggregate a list of outcome records into running stats. None if empty.

    win_rate and expectancy are over DECISIVE trades (wins+losses); EXPIRED
    trades (0R, no directional information) are counted separately and excluded
    from those two ratios. profit_factor is gross_win / gross_loss, or None when
    there are no losses yet (undefined -- rendered as an infinity glyph).
    """
    if not rows:
        return None

    wins = [r for r in rows if str(r.get("outcome")).upper() == "WIN"]
    losses = [r for r in rows if str(r.get("outcome")).upper() == "LOSS"]
    expired = [r for r in rows if str(r.get("outcome")).upper() == "EXPIRED"]
    decisive = len(wins) + len(losses)

    def _r(rec: dict) -> float:
        try:
            return float(rec.get("r", 0.0))
        except (TypeError, ValueError):
            return 0.0

    gross_win_r = sum(_r(w) for w in wins)
    gross_loss_r = -sum(_r(l) for l in losses)   # positive magnitude of losses
    net_r = sum(_r(r) for r in rows)

    profit_factor: Optional[float]
    if gross_loss_r > 0:
        profit_factor = gross_win_r / gross_loss_r
    else:
        profit_factor = None  # no losses yet -> undefined

    # Max drawdown in R: deepest dip of the cumulative-R curve below its peak.
    peak = 0.0
    cum = 0.0
    max_dd_r = 0.0
    for r in rows:
        cum += _r(r)
        peak = max(peak, cum)
        max_dd_r = min(max_dd_r, cum - peak)

    stats: Dict = {
        "closed": len(rows),
        "decisive": decisive,
        "wins": len(wins),
        "losses": len(losses),
        "expired": len(expired),
        "win_rate": (len(wins) / decisive) if decisive else 0.0,
        "net_r": net_r,
        "gross_win_r": gross_win_r,
        "gross_loss_r": gross_loss_r,
        "profit_factor": profit_factor,
        "expectancy_r": (net_r / decisive) if decisive else 0.0,
        "avg_win_r": (gross_win_r / len(wins)) if wins else 0.0,
        "avg_loss_r": (-gross_loss_r / len(losses)) if losses else 0.0,
        "max_dd_r": max_dd_r,
        "since": str(rows[0].get("started_at", "")) or None,
        "currency": None,
    }

    if risk_cash:
        code = str(currency or "USD")
        stats["currency"] = {
            "code": code,
            "risk_cash": risk_cash,
            "net": net_r * risk_cash,
            "gross_win": gross_win_r * risk_cash,
            "gross_loss": gross_loss_r * risk_cash,
            "max_dd": max_dd_r * risk_cash,
        }
    return stats


def risk_cash_from_config(pnl_cfg: Optional[dict]) -> Optional[float]:
    """Fixed per-trade cash at risk (1R) from config, or None to stay R-only.

    balance * risk_per_trade_pct/100. Any missing/zero/garbage balance -> None
    (currency estimate simply omitted, never a crash in the alert path)."""
    pnl_cfg = pnl_cfg or {}
    bal = pnl_cfg.get("account_balance")
    if bal in (None, "", 0):
        return None
    try:
        balance = float(bal)
        pct = float(pnl_cfg.get("risk_per_trade_pct", 1.0))
    except (TypeError, ValueError):
        return None
    if balance <= 0 or pct <= 0:
        return None
    return balance * pct / 100.0


def running_stats(data_dir: str, symbol: str, timeframe: str, platform: str,
                  pnl_cfg: Optional[dict] = None) -> Optional[Dict]:
    """Full running stats for the schedule that produced this verdict. None when
    there are no closed trades yet (caller then shows no footer)."""
    rows = [o for o in load_outcomes(data_dir)
            if _matches(o, symbol, timeframe, platform)]
    rows = select_since_start(rows)
    risk_cash = risk_cash_from_config(pnl_cfg)
    return compute(rows, risk_cash=risk_cash,
                   currency=(pnl_cfg or {}).get("currency", "USD"))
