# Single-legend analysis flow (shared)

This file is the shared procedure for running ONE legend. It is used by:
- the per-legend slash commands (`/gann`, `/wyckoff`, …), and
- the `/convene` command, which runs this once per legend (blind, in parallel).

You are given a request (slash command **or** plain English). Extract: a **legend
id**, a **symbol**, an optional **timeframe**, and an optional **platform**.

## 1. Parse intent + normalize inputs
- Symbol → UPPER (e.g. `eurusd` → `EURUSD`).
- Timeframe: accept `M15`/`15m`/`15`, `H1`/`1h`, `D1`, `W1`, etc. Canonical set is
  `1m 5m 15m 30m 1h 4h 1d 1w`. If none given, use the legend's default anchor
  (`1h` unless the legend spec says otherwise).
- Platform: resolve via `CLAUDE.md` (explicit token like `tv`/`mt5` → asset-class
  auto-route → config default). Honor a session-sticky preference if the user set one.
- You may sanity-check with: `python3 -c "from tlc.normalize import canonical_timeframe,canonical_symbol; print(canonical_symbol('$SYM'), canonical_timeframe('$TF'))"`

## 2. Load the legend's method
Read `tlc/legends/<id>.md`. Use ONLY that method. Do not borrow other schools.

## 3. Pull data (platform-aware)
Resolve the native symbol for the platform, then fetch ≈200 bars per frame:
- **mt5** → `mcp__MBT__get_ohlcv(symbol, timeframe, count)` (apply the broker
  `symbol_suffix`, e.g. `EURUSDzero`).
- **tradingview** → `mcp__tvremix__get_ohlcv(symbol, interval, count)` with a
  TradingView-native symbol (`NASDAQ:AAPL`, `BINANCE:BTCUSDT`, `FX_IDC:EURUSD`);
  intervals use `1D`/`1W` for daily/weekly.
  Resolve with `python3 -c "from tlc.providers import get_provider; from tlc.config import load_config; print(get_provider('<platform>', load_config()).resolve_symbol('<SYM>'))"`.
- Always fetch the **anchor timeframe**. If `tf_scope: multi`, also fetch the
  higher timeframes the method needs and form an `htf_bias`. If `tf_scope:
  single`, fetch the anchor only.

## 3b. Compute deterministic indicators (if the spec declares `needs:`)
If the legend's frontmatter has a `needs:` list (e.g. `needs: [rsi14, adx14]`),
do NOT eyeball those readings from the bars — compute them exactly, the same way
the `api` engine does, so both runtimes give the same ballot (§1.13):
- **Compute them with one direct call — do NOT hand-assemble a packet JSON.**
  `tlc.indicators` needs the exact in-memory packet (`frames`, a dict keyed by
  timeframe, from `build_market_packet`). A hand-written file with a flat `bars`
  array is the wrong shape and returns `null` for everything; and
  `tlc.data_desk … --json` prints only a *summary* (no `frames`), so it can't feed
  the indicators either. The robust path (same one the `api` engine and the cron
  helper use) skips the JSON round-trip entirely — build the packet and compute in
  one command, e.g. for `needs: [swings, fib]`:
  ```bash
  python3 -c "from tlc.data_desk import build_market_packet; from tlc.indicators import compute, render_block; from tlc.normalize import canonical_symbol as S, canonical_timeframe as T; p=build_market_packet(S('EURUSD'), T('1h'), explicit_platform='mt5'); print(render_block(compute(['swings','fib'], p['frames'], T('1h'))))"
  ```
  (swap in the symbol, anchor timeframe, `explicit_platform`, and the spec's
  `needs:` list).
- Read the printed block into your reasoning. **`null` = not enough data /
  unavailable — treat it as absent, never infer a value.** But if *every* declared
  `needs:` indicator is `null`, suspect a bad packet (wrong schema / empty bars) or
  a failed fetch — **not** a real data gap: re-run the one-liner above and retry
  before concluding the indicators are unavailable. Base your read of any `needs:`
  indicator on these exact numbers, not a visual estimate.

## 4. Analyze in character
Reason strictly through the legend's lens (their patterns, signals, philosophy,
era). Be honest: if the legend's setup is NOT present, the correct vote is FLAT.
Never force a trade.

## 5. Produce output — narrative + ballot
First write a short analysis **in the legend's voice**. Then output the ballot as
a single fenced ```json block, exactly this schema:

```json
{
  "legend": "<id>",
  "platform": "mt5 | tradingview",
  "symbol": "EURUSD",
  "timeframe": "1h",
  "direction": "LONG | SHORT | FLAT",
  "conviction": 0.0,
  "entry": 0.0,
  "invalidation": 0.0,
  "target": 0.0,
  "regime_assumption": "",
  "htf_bias": "up | down | neutral | ''",
  "thesis": "one or two sentences",
  "created_at": "YYYY-MM-DD HH:MM"
}
```

Rules:
- `direction: FLAT` ⇒ omit/zero entry, invalidation, target. Conviction 0.
- A directional vote MUST include positive `entry`, `invalidation`, `target`.
  - LONG: `invalidation < entry < target`. SHORT: `target < entry < invalidation`.
- `invalidation` = the price that proves this legend wrong (it is also the stop).
- `conviction` ∈ [0,1] reflects how textbook the setup is for THIS legend.
- Single-TF legends set `htf_bias: ""`.
- `platform` = the resolved data source (`mt5` | `tradingview`) — so the outcome
  is scored on the same feed it was generated on.

## 6. Persist (optional, on by default for /convene)
Append the ballot via the local sink:
`python3 -c "from tlc.sinks import LocalJsonSink; import json,sys; LocalJsonSink('data').emit_ballot(json.load(sys.stdin))" < ballot.json`
You may validate first with `tlc.ballot.validate_ballot`.
