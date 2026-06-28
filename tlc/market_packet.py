"""Build the market packet handed identically to every legend (PRD §1.2).

Pure functions over raw bars (the exact shape MBT's get_ohlcv returns):
    {"time": "YYYY-MM-DD HH:MM", "open", "high", "low", "close", "volume"}
Bars are NEWEST-FIRST (as get_ohlcv returns them).

No MT5 dependency here — the agent fetches bars via the MBT MCP and passes them
in, so this module is fully testable offline.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Dict, List, Optional


def atr(bars: List[dict], period: int = 14) -> Optional[float]:
    """Average True Range over the most recent `period` bars.

    `bars` newest-first. Returns None if fewer than 2 bars.
    """
    if not bars or len(bars) < 2:
        return None
    chrono = list(reversed(bars))  # oldest-first for prev-close access
    trs: List[float] = []
    for i in range(1, len(chrono)):
        h = chrono[i].get("high")
        low = chrono[i].get("low")
        prev_close = chrono[i - 1].get("close")
        # A provider can return a partial bar (missing/None OHLC); skip it rather
        # than crash the whole packet build on `None - float`.
        if h is None or low is None or prev_close is None:
            continue
        trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    if not trs:
        return None
    period = min(period, len(trs))
    return round(sum(trs[-period:]) / period, 8)


def build_packet(
    symbol: str,
    anchor_timeframe: str,
    frames: Dict[str, List[dict]],
    atr_period: int = 14,
    platform: str = "",
) -> dict:
    """Assemble the market packet from per-timeframe bar lists.

    `platform` ("mt5" | "tradingview") tags the data source so the outcome is
    later scored on the same feed it was generated on (PRD §1.10).
    """
    if anchor_timeframe not in frames or not frames[anchor_timeframe]:
        raise ValueError(f"frames must include non-empty anchor timeframe '{anchor_timeframe}'")
    anchor_bars = frames[anchor_timeframe]
    newest = anchor_bars[0]  # newest-first
    price = newest.get("close")
    if price is None or (isinstance(price, float) and not math.isfinite(price)):
        # A missing/NaN/inf newest close would silently poison every legend's
        # math and the verdict; fail loud at the seam instead.
        raise ValueError(
            f"newest {anchor_timeframe} bar has no usable close ({price!r}); "
            "the data feed returned an incomplete bar"
        )
    return {
        "platform": platform,
        "symbol": symbol,
        "anchor_timeframe": anchor_timeframe,
        "as_of": newest["time"],
        "current_price": price,
        "atr": {tf: atr(bars, atr_period) for tf, bars in frames.items()},
        "frames": frames,
    }


def _main(argv: List[str]) -> int:
    """CLI: read a JSON file {symbol, anchor_timeframe, frames, [atr_period]} → packet on stdout.

    Usage: python -m tlc.market_packet <input.json> [output.json]
    """
    if not argv:
        print("usage: python -m tlc.market_packet <input.json> [output.json]", file=sys.stderr)
        return 2
    with open(argv[0]) as fh:
        spec = json.load(fh)
    packet = build_packet(
        spec["symbol"],
        spec["anchor_timeframe"],
        spec["frames"],
        spec.get("atr_period", 14),
        spec.get("platform", ""),
    )
    out = json.dumps(packet, indent=2)
    if len(argv) > 1:
        with open(argv[1], "w") as fh:
            fh.write(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
