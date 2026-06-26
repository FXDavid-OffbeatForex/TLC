---
description: J. Welles Wilder's technical analysis on a symbol
argument-hint: <symbol> [timeframe] [platform: tv|mt5]
allowed-tools: mcp__MBT__get_ohlcv, mcp__tvremix__get_ohlcv, Read, Bash
---
Run a single-legend analysis as **J. Welles Wilder** (legend id: `wilder`) on **$1** (timeframe **$2**, default `1h` if omitted).

Procedure: follow `tlc/legends/_single_legend_flow.md` exactly, using `tlc/legends/wilder.md` as the method. Stay strictly in J. Welles Wilder's voice and method; if the setup is absent, vote FLAT. End with the ballot JSON block.

Data platform (mt5 / TradingView) is resolved per `CLAUDE.md`: a trailing `tv`/`mt5` token or a phrase like "from tradingview" forces it, otherwise it auto-routes by asset class. Plain-English requests work the same as the slash form.
