"""L0 Data Desk — resolve platform, fetch frames, build the market packet.

One entry point above the provider seam (PRD §1.10). Given a symbol it:
  1. resolves the platform (explicit → asset-class auto-route → default),
  2. builds the matching provider and resolves the native symbol,
  3. fetches each frame's bars, and
  4. returns the platform-tagged market packet.

The TradingView path runs fully headlessly here (tvremix over HTTP). The MT5 path
fetches via MBT core only on a VPS with the MetaTrader5 package — in the public
on-demand path the coding agent builds the packet via the MBT MCP instead.

CLI:  python3 -m tlc.data_desk <symbol> [anchor_tf] [--platform tv|mt5]
e.g.  python3 -m tlc.data_desk BTCUSD 1h
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from .config import load_config
from .market_packet import build_packet
from .normalize import canonical_symbol, canonical_timeframe
from .providers import get_provider, resolve_platform


def build_market_packet(
    symbol: str,
    anchor_timeframe: Optional[str] = None,
    frames: Optional[List[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    explicit_platform: Optional[str] = None,
) -> dict:
    """Resolve a platform, fetch all frames, and return the tagged market packet."""
    config = config if config is not None else load_config()
    anchor = canonical_timeframe(anchor_timeframe or config.get("default_anchor_timeframe", "1h"))
    frame_tfs = [canonical_timeframe(t) for t in (frames or config.get("frames", [anchor]))]
    if anchor not in frame_tfs:
        frame_tfs.append(anchor)

    user_symbol = canonical_symbol(symbol)
    platform = resolve_platform(user_symbol, config, explicit=explicit_platform)
    provider = get_provider(platform, config)
    native_symbol = provider.resolve_symbol(user_symbol)

    count = config.get("bars_per_frame", 200)
    frame_bars: Dict[str, List[dict]] = {
        tf: provider.fetch(native_symbol, tf, count) for tf in frame_tfs
    }
    return build_packet(
        native_symbol, anchor, frame_bars,
        atr_period=config.get("atr_period", 14),
        platform=platform,
    )


def _main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    explicit = None
    for a in argv:
        if a.startswith("--platform"):
            explicit = a.split("=", 1)[1] if "=" in a else (argv[argv.index(a) + 1] if argv.index(a) + 1 < len(argv) else None)
    if not args:
        print("usage: python3 -m tlc.data_desk <symbol> [anchor_tf] [--platform tv|mt5]", file=sys.stderr)
        return 2
    symbol = args[0]
    anchor = args[1] if len(args) > 1 else None
    packet = build_market_packet(symbol, anchor, explicit_platform=explicit)
    # Trim bars for a readable summary; keep counts + ATR + the newest bar.
    summary = {
        "platform": packet["platform"],
        "symbol": packet["symbol"],
        "anchor_timeframe": packet["anchor_timeframe"],
        "as_of": packet["as_of"],
        "current_price": packet["current_price"],
        "atr": packet["atr"],
        "bars_per_frame": {tf: len(bars) for tf, bars in packet["frames"].items()},
        "newest_anchor_bar": packet["frames"][packet["anchor_timeframe"]][0],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
