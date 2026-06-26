# TLC — agent dispatch guide

This file is auto-loaded by Claude Code. It tells you (the agent) how to turn a
user's request — **slash command _or_ plain English** — into the right TLC flow on
the right data platform. The slash commands in `.claude/commands/` are shortcuts;
this guide is what makes natural language work the same way.

## What the user might ask for

| The user says… | Do this |
|---|---|
| `/convene EURUSD 1h` · "convene on EURUSD" · "what does the council think of AAPL?" | Full council → run `.claude/commands/convene.md` |
| "convene the orderflow council on EURUSD" · `/convene EURUSD 1h --council orderflow` | Custom roster → `convene.md` step 2 resolves it via `python3 -m tlc.council show NAME` |
| `/gann eurusd` · "give me a gann read on EURUSD" · "how would Wyckoff see BTC?" | Single legend → run that legend via `tlc/legends/_single_legend_flow.md` |
| "make a trader who buys liquidity sweeps" · "add an ICT legend" · `/forge-legend …` | Author a legend → `.claude/commands/forge-legend.md` |
| "build a council called scalp with wyckoff and ict_ob" · `/council new …` | Manage rosters → `.claude/commands/council.md` |
| "what councils do I have?" / "show me the orderflow council" | `python3 -m tlc.council list` / `show <name>` |
| "scan EURUSD every hour and alert me" · "run the council on BTC every 15m" · `/schedule …` | Set up a cron → `.claude/commands/schedule.md` |
| "what's scheduled?" / "stop the EURUSD schedule" | `python3 -m tlc.cron list` / `stop <name>` |
| "what VPS do I need?" / "size a server for 3 hourly jobs" | VPS calculator → `python3 -m tlc.vps_calc --jobs 3 --interval 1h --engine <agent\|api> --platform <tv\|mt5>` |
| "score my ballots" / "how is Gann doing?" | Local scoring → `tlc/scoring/score.py` (+ MBT backtest) |

Map legend names/nicknames to ids: dow, wyckoff, livermore, elliott, gann,
demark, wilder, hosoda (Ichimoku), weinstein, oneil (CAN SLIM). Custom legends live in
`my_legends/<id>.md` and are referenced by their id just like core ones.

**Building a council conversationally.** A user may forge legends and assemble a roster in
one flow ("build a council with X, plus a trader who does Y"). Forge each new member
(`forge-legend.md` — lint + audition before it's admitted), then write the roster
(`council.md`). When the user is clearly mid-"build a council", add each freshly forged
legend to that council; otherwise save it standalone and ask before adding.

## Step 0 — extract intent (before anything else)

From whatever the user wrote, pull out:
- **legend(s)** — one named legend, or "the council" / "convene" → all 10.
- **symbol** — e.g. EURUSD, AAPL, BTCUSD. Required.
- **timeframe** — if omitted, use the legend's `default_anchor` (else config `default_anchor_timeframe`, `1h`).
- **platform** — see below. If unstated, resolve automatically.

Never demand rigid syntax. "gann on eurusd 15m from tradingview" and
`/gann EURUSD 15m tv` mean the same thing.

## Platform resolution (PRD §1.10)

A platform decides **where bars come from and how the symbol is named**. Read
`config.yaml` → `enabled_platforms`, `routing`, `default_platform`. Resolve in
this order (most specific wins):

1. **Explicit** — the user named one. Words → platform:
   - `tv`, "tradingview", "on TV", "remix" → **tradingview**
   - `mt5`, "metatrader", "my broker", "broker" → **mt5**
2. **Auto-route by asset class** — forex/metals → usually mt5; stocks/crypto →
   tradingview (per the `routing` table). You can compute the class with
   `python3 -c "from tlc.providers.routing import classify_asset; print(classify_asset('AAPL'))"`.
3. **Default** — `default_platform`.

If only one platform is enabled, everything goes there — don't ask which.

**Session-sticky preference.** If the user says something like *"I only want
tradingview"* or *"use my broker from now on"*, treat that as the platform for
**every** later request this session until they change it. Confirm once briefly,
then stop re-asking.

## Which fetch tool to call, per platform

You resolve the platform, then fetch bars with the matching MCP tool. Only the
servers the user registered will be present:

- **mt5** → `mcp__MBT__get_ohlcv(symbol, timeframe, count)`. Apply the broker
  `symbol_suffix` (e.g. EURUSD → EURUSDzero) — or call
  `python3 -c "from tlc.providers import get_provider; from tlc.config import load_config; print(get_provider('mt5', load_config()).resolve_symbol('EURUSD'))"`.
- **tradingview** → `mcp__tvremix__get_ohlcv(symbol, interval, count)`. The symbol
  must be TradingView-native (`NASDAQ:AAPL`, `BINANCE:BTCUSDT`, `FX_IDC:EURUSD`);
  resolve it with `TvRemixProvider.resolve_symbol(...)`. Intervals: `1m 5m 15m
  30m 1h 4h 1D 1W`.

Either way, **tag the resulting market packet, ballots, and verdict with the
`platform`** so outcomes are scored on the same feed (§1.10).

### Headless shortcut

If neither MCP is registered but a `tvr_…` key is in `.env`, you can build a
TradingView packet directly in Python (no MCP needed):

```bash
python3 -m tlc.data_desk BTCUSD 1h --platform tv      # crypto, auto-resolves symbol
python3 -m tlc.data_desk AAPL 1D                       # stock → TradingView
```

## Scheduling, alerts & engines (PRD §2.13–2.17)

The user can run the council on a clock and get **Telegram** alerts — see
`.claude/commands/schedule.md`. Vocabulary:

- **Schedule intervals:** "every 15 minutes / 2 hours / 3 days" → `15m` / `2h` / `3d`.
  Install/list/stop with `python3 -m tlc.cron set|list|stop`.
- **Engine** (`config.yaml → engine`): how a *scheduled* fire runs the council —
  **agent** (your CLI headless, e.g. `claude -p`; your subscription) or **api**
  (`python3 -m tlc.orchestrator`; your own OpenRouter/Anthropic key in `.env`). Same
  verdict either way. On-demand convening is unaffected — this only governs cron fires.
- **Alerts:** Telegram needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` and
  `alerts.enabled: [telegram]`. NO_TRADE is silent unless `quiet_no_trade: false`.
  `python3 -m tlc.notify <verdict.json>` sends a verdict to enabled channels.

**Per fire:** wake engine → fresh packet → council blind → Chairman → log to `data/`
→ push a trade verdict to Telegram.

**Always-on / VPS.** 24/7 schedules need a machine that stays up. Before installing a
schedule, run the calculator and show the recommendation + link:
`python3 -m tlc.vps_calc --jobs N --interval IV --engine E --platform P`.
- **TradingView** (api or agent) → **InterServer** Linux VPS (from $3/mo) — the calc picks a slice.
- **MT5** → **Windows** VPS (MetaTrader must run) — the calc deep-links our Windows calculator.

**TradingView caveats (MT5 is exempt).** Bars are cached (5m–1h by bar size) — don't
schedule faster than `tv_cache_seconds`. The key is capped 20/min · 200/hr · 1,500/day;
`tlc/providers/rate_limit.py` enforces it and the calculator checks the budget exactly.

## Golden rule

Same 10 legends, same ballots, same Chairman — the platform only changes the data
source. Resolve it, fetch, tag it, and run the normal flow.
