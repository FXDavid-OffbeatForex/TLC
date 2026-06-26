---
description: Convene the full Trading Legends Council on a symbol and issue a verdict
argument-hint: <symbol> [timeframe] [platform: tv|mt5] [--council NAME]
allowed-tools: mcp__MBT__get_ohlcv, mcp__tvremix__get_ohlcv, Read, Bash
---
Convene the **Trading Legends Council** on **$1** (timeframe **$2**, default `1h`).
Accepts plain English too ("convene on AAPL from tradingview"); see `CLAUDE.md`.

## 1. Build the market packet (once, shared by all legends — fairness)
- Parse intent + normalize the symbol/timeframe (see `tlc/normalize.py`).
- **Resolve the platform** (explicit `tv`/`mt5` token → asset-class auto-route →
  config default; see `CLAUDE.md` §Platform resolution) and the native symbol.
- Pull bars for the frames `15m, 1h, 4h, 1d` (≈200 bars each) with the matching
  tool: **mt5** → `mcp__MBT__get_ohlcv`, **tradingview** → `mcp__tvremix__get_ohlcv`
  (TV-native symbol; daily/weekly intervals are `1D`/`1W`).
- Build the packet (this also computes ATR per timeframe and tags `platform`):
  write `{platform, symbol, anchor_timeframe, frames}` to a temp JSON and run
  `python3 -m tlc.market_packet <frames.json> <packet.json>`.
  Every legend MUST receive this identical packet — no legend gets extra data.

## 2. Determine the council, then collect ballots (BLIND, in parallel)
Pick the roster:
- **Default** (no council named): the canonical 10 — dow, wyckoff, livermore, elliott,
  gann, demark, wilder, hosoda, weinstein, oneil.
- **Custom** (`--council NAME`, or NL "convene the NAME council"): resolve members with
  `python3 -m tlc.council show NAME` — each member's spec path is `my_legends/<id>.md`
  first, then `tlc/legends/<id>.md`.

For each member, run the single-legend flow (`tlc/legends/_single_legend_flow.md`)
against the **same packet**, using that legend's spec. Each returns one ballot JSON.

Legends vote **independently** — do not let one legend see another's vote.
Run them as parallel subagents where possible so the reads stay isolated.

## 3. Validate, persist, aggregate
- Validate each ballot (`tlc.ballot.validate_ballot`); drop invalid ones, noting why.
- Save all ballots to the local sink (`data/ballots.jsonl`).
- Run the Chairman to produce the verdict. Use the council's threshold/weights for a
  custom roster (`tlc.council.council_settings`); default threshold is `0.65`. Write the
  ballots to a JSON array and run `python3 -m tlc.run_council <ballots.json>`, or call
  `tlc.chairman.aggregate(ballots, threshold=…, weights=…)` directly.

## 4. Present
Show a table of the 10 ballots (legend · direction · conviction · entry · stop ·
target · one-line thesis), then the **Chairman's verdict**: decision (LONG /
SHORT / **NO_TRADE**), consensus %, entry, stop, target, R:R, and which legends
were for / against / abstaining. Remember: a split council is NO_TRADE — standing
aside is a valid, often correct, outcome.
