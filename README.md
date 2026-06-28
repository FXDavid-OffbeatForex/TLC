# TLC — Trading Legends Council

> Ten legendary traders and analysts — each rebuilt as an independent AI agent — read the same
> chart, vote blind, and a **Chairman** issues one risk-managed verdict.

Ask **one** master for their read, or convene the whole room.

**What TLC does:**
- Pulls live bar data from your MT5 broker or TradingView
- Runs each legend as a separate, isolated AI subagent — they cannot see each other's reasoning
- Every legend produces a structured ballot: direction, entry, stop, target, conviction, thesis
- The Chairman aggregates all ballots under a strict consensus rule and issues a single verdict (`LONG / SHORT / NO_TRADE`) with position sizing
- Verdicts are logged, scored, and optionally pushed to Telegram on a schedule
- You can forge your own legends from famous names or plain-English strategies, and assemble custom councils

---

## Usage

### One legend: `/<legend> <symbol> [timeframe]`

```
/wyckoff EURUSDzero 1h
```

The legend analyzes the chart strictly through their own lens and returns a narrative
in their voice, followed by a structured ballot.

**Example output:**

```
Richard Wyckoff — EURUSDzero 1h  |  2026-06-26 07:00

The Composite Operator has been busy. Looking at the weekly structure, I see a
clear accumulation phase that began in early May — a wide trading range with
repeated tests of the lower boundary near 1.1200. The Selling Climax was evident:
high-volume downside rejection, followed by an Automatic Rally and a Secondary Test
on lighter volume. The Spring came last week: price swept below 1.1185 intraday
then closed back inside the range — classic false break to shake out weak hands.

On the 1h anchor, I'm watching for the Sign of Strength now. We have an upthrust
through range midpoint on expanding volume. The Last Point of Support has held
twice at 1.1380. Volume is drying up on the pullbacks — the Composite Operator
is not distributing, he's absorbing.

The cause is built. The effect is a move toward 1.1560 at minimum.

{
  "legend": "wyckoff",
  "symbol": "EURUSDzero",
  "timeframe": "1h",
  "direction": "LONG",
  "conviction": 0.82,
  "entry": 1.13850,
  "invalidation": 1.13200,
  "target": 1.14800,
  "regime_assumption": "range-to-markup",
  "htf_bias": "up",
  "thesis": "Spring confirmed on weekly range; SOS on 1h; LPS holding at 1.1380.",
  "created_at": "2026-06-26 07:00"
}
```

---

### Full council: `/convene <symbol> [timeframe]`

```
/convene EURUSDzero 1h
```

All 10 legends analyze the **same market packet** independently and blind — they
cannot see each other's votes. The Chairman then aggregates and issues a single verdict.

**Example output:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TRADING LEGENDS COUNCIL  ·  EURUSDzero 1h  ·  2026-06-26 07:00
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BALLOTS

 Legend       Direction  Conv.  Entry     Stop      Target    Thesis
 ─────────    ─────────  ─────  ────────  ────────  ────────  ──────────────────────────────────
 Wyckoff      LONG       0.82   1.13850   1.13200   1.14800   Spring + SOS; LPS holding at 1.1380
 Dow          LONG       0.74   1.13870   1.13350   1.14700   HTF HH/HL confirmed; secondaries rising
 Livermore    LONG       0.71   1.13900   1.13450   1.14650   Pivotal point at 1.1390 cleared on volume
 Elliott      LONG       0.60   1.13840   1.13100   1.15200   Wave 3 of (3) after completed ABC low
 Hosoda       LONG       0.68   1.13880   1.13500   1.14600   Price above cloud; Tenkan/Kijun cross; Chikou clear
 Weinstein    LONG       0.76   1.13920   1.13500   1.14800   Stage 2 breakout from 6-week base; MA rising
 O'Neil       LONG       0.65   1.13910   1.13520   1.14750   Flat-base pivot cleared; volume 60% above avg
 DeMark       SHORT      0.72   1.13890   1.14250   1.12900   Sell Setup-9 completed; exhaustion of buyers
 Gann         FLAT       0.00   —         —         —         No time/price square active; standing aside
 Wilder       FLAT       0.00   —         —         —         ADX < 20; RSI 58 — no confirmed signal in either direction

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CHAIRMAN'S VERDICT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 Decision:    ✅ LONG
 Consensus:   87%  (7 directional for / 1 against / 2 abstain)
 Entry:       1.13870
 Stop:        1.13420  (median of LONG invalidations)
 Target:      1.14757  (median of LONG targets)
 R:R:         2.06
 Size:        0.58 of normal risk

 FOR:     Wyckoff · Dow · Livermore · Elliott · Hosoda · Weinstein · O'Neil
 AGAINST: DeMark
 ABSTAIN: Gann · Wilder

 Rationale: Strong LONG consensus (87%) across trend-following, supply/demand and
 breakout methods. DeMark's counter-trend warning is noted — a TD-9 at this level
 means the move may pause before extending; tighten exit at first DeMark target.
 Gann and Wilder abstain: no setup in their method, which is honest. Absence of
 their vote reduces total conviction; size 0.58 reflects that.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Ballots saved → data/ballots.jsonl
 Verdict saved → data/verdicts.jsonl
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

> **What NO-TRADE looks like:** if DeMark and Gann were directional in the other direction and
> consensus dropped below 65%, the Chairman would output `NO_TRADE` with the reason. A split
> council is information — it means the chart is genuinely ambiguous and the correct trade is flat.

---

## The council

| Legend | School | Timeframe |
|---|---|---|
| Charles Dow | Dow Theory (trend + confirmation) | multi |
| Richard Wyckoff | Supply/Demand, the Composite Operator | multi |
| Jesse Livermore | Tape reading / pivotal points | single |
| Ralph N. Elliott | Wave Theory (fractal) | multi |
| W.D. Gann | Geometry & time cycles | multi |
| Thomas DeMark | Counter-trend exhaustion (TD Sequential) | single |
| J. Welles Wilder | Momentum/volatility (RSI / ADX / ATR) | single |
| Goichi Hosoda | Ichimoku equilibrium | multi |
| Stan Weinstein | Stage analysis (30-MA) | multi |
| William O'Neil | CAN SLIM breakouts on volume | multi |

Single-TF legends (Livermore, DeMark, Wilder) analyze only the timeframe you give them.
Multi-TF legends pull higher timeframes automatically and report their bias.

---

## Build your own council

The 10 above are the **default** council. You can forge new legends — from a famous
name, or by *describing a strategy in plain English* (even your own) — and group any
mix of them into a custom council. It's all conversational; `/forge-legend` and
`/council` are just shortcuts.

```
You: i want to build a council called "orderflow" with wyckoff and livermore,
     plus an ICT order-block trader, plus my own strategy

TLC: Wyckoff and Livermore are in. Two to forge.

     "ICT order-block" → drafted `ict_ob` (multi-TF; entry = mitigation of a
     bullish order block in a killzone). One gap: what invalidates the trade?

You: a candle close back through the order block

TLC: Locked.  ✅ lint passed   ✅ audition on EURUSD 15m → valid ballot
     Saved → my_legends/ict_ob.md

     Now your own strategy — describe how you trade it.

You: buy when price sweeps the prior day's low then reclaims it on the 5m,
     stop under the sweep, target the prior day high

TLC: Drafted `my_sweep` (single-TF 5m; invalidation = below the sweep low;
     target = prior-day high). No gaps.
       ✅ lint passed   ✅ audition on EURUSD 5m → valid ballot
     Saved → my_legends/my_sweep.md

     Council "orderflow": wyckoff, livermore, ict_ob, my_sweep. Threshold 0.65 —
     keep it?

You: make it 60

TLC: Saved → councils/orderflow.yaml (4 members, threshold 0.60).
     Run it: "convene the orderflow council on <symbol>".
```

Then run it like any other convening:

```
/convene EURUSD 15m --council orderflow      # or: "convene the orderflow council on EURUSD"
```

Every new legend must pass a **lint** (valid schema + a defined invalidation rule, so
it's scoreable) and a **live audition** (it actually produces a valid ballot) before it
can vote — so a custom council is just as rigorous as the default one. Your authored
legends live in `my_legends/` (gitignored — your strategy stays yours); council files
are small shareable lists.

---

## Setup — no API key required

**Your coding agent is the LLM.** The council runs as subagents on your own plan
(Claude Code, Codex, Cursor, Windsurf, etc.) — no key from us needed.

("No API key required" means *from TLC* — the council runs on your own agent subscription. The
TradingView platform uses a free third-party key from tvremix.xyz; the MT5 platform uses none.)

**Setup is done by the agent, in chat — no terminal needed.**

```bash
git clone <this repo>
cd TA-Legends-Council
pip install -r requirements.txt
```

Then open the folder in your AI agent (Claude Code, Cursor, Windsurf, Codex…) and
say anything — "hi", "convene EURUSD", whatever. The agent detects missing config
files and walks you through setup conversationally:

- Asks which data platform (MT5, TradingView, or both) and which optional features
  (scheduled engine, Telegram alerts).
- **MT5 path:** clones [MBT](https://github.com/FXDavid-OffbeatForex/MBT) if it isn't
  already present, installs its deps, writes `.mcp.json` to register it as an MCP
  server, and asks for your `mt5_path` (right-click your MT5 shortcut → Properties →
  Target) or finds it for you if you name your broker.
- **TradingView path:** writes a blank `.env` scaffold and offers to open it so you
  can paste your free `tvr_…` key (from [tvremix.xyz](https://tvremix.xyz)) — the key
  never passes through the chat.
- Writes `config.yaml` and optionally verifies the connection.

After the one-time setup, restart your agent (so the MBT MCP loads) and start:
`/convene EURUSDzero 1h` or `/wyckoff EURUSDzero 15m`.

**Timeframe formats accepted:** `M15`, `15m`, `15` → `15m` · `H1`, `1h` → `1h` ·
`D1` → `1d` · `W1` → `1w`. Symbol is uppercased automatically.

Every agent greets a new session by printing the **TLC banner** (works in any
client — terminal, IDE panel, or web).

### Optional: the `tlc` launcher — an animated intro

Purely for terminal die-hards. Instead of `claude`, start your session with the
bundled launcher and you'll get a 3.5s "Thunderclap" intro before Claude Code
takes over:

```bash
./tlc.sh                      # plays the splash, then runs `claude`
./tlc.sh convene EURUSD 1h    # args pass straight through

# or alias it so plain `tlc` works from the repo:
alias tlc='/path/to/TA-Legends-Council/tlc.sh'
```

It's Claude-Code-specific and terminal-only — the splash no-ops in non-interactive
contexts (cron, `claude -p`, piped output, IDE panels) and respects `NO_COLOR`.
Running `claude` directly is identical minus the animation.

---

## Data platforms — MT5 *or* TradingView

The council reads the same way regardless of where bars come from. You pick the
**platform** per request (or let it auto-route):

| Platform | Best for | What you install |
|---|---|---|
| **MT5** (via MBT) | broker-native forex/metals + local backtest loop | MT5 terminal + MBT MCP |
| **TradingView** (via [tvremix](https://tvremix.xyz)) | stocks, crypto, *and* forex — **no install** | a free `tvr_…` API key |

A **TradingView-only** user needs no MT5, no MBT, no Wine, no broker — just the key.
Open the repo in your agent, say hi, pick TradingView during setup, and paste your free
`tvr_…` key (from [tvremix.xyz](https://tvremix.xyz)) into the `.env` file the agent
creates. The agent registers the tvremix MCP server via `.mcp.json` automatically.

With **both** enabled, symbols auto-route by asset class (forex → MT5, stocks/crypto
→ TradingView) and a trailing token overrides:

```
/convene AAPL 1h              # stock → TradingView automatically
/convene EURUSD 1h            # forex → your broker (MT5)
/convene EURUSD 1h tv         # force TradingView for this call
/gann BTCUSD 4h               # crypto → TradingView
```

Plain English works the same — *"give me a gann read on eurusd from tradingview"*,
or set it once with *"I only want tradingview"* and it sticks for the session
(see [CLAUDE.md](CLAUDE.md)). Headless check without any agent:

```bash
python3 -m tlc.data_desk BTCUSD 1h        # builds a TradingView packet directly
```

Every ballot and verdict is tagged with its `platform`, so outcomes are always
scored against the same feed they were generated on.

---

## Schedule & alerts — 24/7 signals to Telegram

Beyond asking on demand, you can run the council **on a clock** and get a **Telegram**
ping when it issues a trade. Per minute, hour, or day — `15m`, `2h`, `3d`, …

```
scan EURUSD every hour and alert me          # plain English
/schedule set EURUSD 1h --every 1h           # or the command
python3 -m tlc.cron list                      # what's scheduled
python3 -m tlc.cron stop EURUSD_1h            # remove it
```

**On each fire:** build a fresh packet → council votes blind → Chairman verdict →
logged to `data/` → a trade verdict is pushed to Telegram (NO_TRADE stays silent
by default).

### Telegram in 2 minutes
1. Message **[@BotFather](https://t.me/BotFather)** → `/newbot` → copy the **bot token**.
2. Send your new bot any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `"chat":{"id":…}` number.
3. Put both in `.env`, and enable it in `config.yaml`:

```bash
# .env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
```
```yaml
# config.yaml
alerts:
  enabled: [telegram]
```

### Two engines — your subscription, or your own key
A scheduled fire is LLM-driven, so it runs through an **engine** (`config.yaml → engine`):

| | `engine: agent` (default) | `engine: api` |
|---|---|---|
| Runs | your coding-agent CLI headless (`claude -p …`) | `python3 -m tlc.orchestrator …` |
| LLM billed to | your **subscription** (cheapest) | your own **API key** (OpenRouter/Anthropic in `.env`) |
| Best for | light/medium schedules | heavy 24/7, many symbols |

Either way the verdict and alerts are identical — `api` just swaps the brain for your own key.

### Where to run it 24/7 (and how big)
The machine must stay on. Size it first — the calculator does the exact feed/cost math and
recommends a plan:

```bash
python3 -m tlc.vps_calc --jobs 3 --interval 1h --engine api --platform tv
# → Feed budget ✅ · ~vCPU/RAM · Recommended: InterServer 1-slice ($3/mo) + link
```

| Data | Where | Why |
|---|---|---|
| **TradingView** (api or agent) | **[InterServer](https://www.interserver.net/vps/?id=579551)** Linux VPS — from **$3/mo** | cheap Linux; no MetaTrader |
| **MT5** | **Windows VPS** — [size it here](https://offbeatforex.com/best-forex-vps/) | MetaTrader must run 24/7 |

> **TradingView caveats** (MT5 is exempt): bars are cached 5m–1h by bar size, so don't
> schedule faster than that, and the free key is capped **20/min · 200/hr · 1,500/day** —
> TLC enforces the budget for you and the calculator flags a schedule that would exceed it.

---

## How it works

```
get_ohlcv (MBT MCP)
  → market packet built once, handed identically to all legends     tlc/market_packet.py
  → 10 legend subagents run BLIND in parallel                       tlc/legends/*.md
  → ballots validated + persisted                                   tlc/ballot.py · tlc/sinks/
  → Chairman aggregates → VERDICT or NO_TRADE                       tlc/chairman.py
  → (optional) score ballot history vs. real bars                   tlc/scoring/score.py + MBT
```

**The Chairman's rule:** `consensus = winner_weight / all_directional_weight`.
A split or sub-65% result is `NO_TRADE`. Abstentions reduce total conviction but don't
count against the majority. This forces the system to sit on its hands at least 30% of
the time — the single most profitable discipline any signal system can have.

---

## Local scoring

Every ballot and verdict is logged to `data/`. Turn them into an MBT-compatible signal
CSV (filterable per legend) and score them when MT5 is running:

```bash
# All legends
python3 -m tlc.scoring.score data/ballots.jsonl signals_all.csv

# One legend (for a per-legend track record)
python3 -m tlc.scoring.score data/ballots.jsonl signals_wyckoff.csv --legend wyckoff

# Then run MBT's backtest tool on the CSV (needs MT5)
```

---

## Develop / test

The deterministic core (packet building, ballot validation, Chairman aggregation) is
pure Python — no MT5 or LLM needed to run the tests:

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q   # 113 tests, ~0.3s
```

---

## More from FXDavid

- **YouTube:** [youtube.com/@fxdavid9392](https://www.youtube.com/@fxdavid9392) — TA education through the lens of the legends on this council
- **MT5 data bridge:** [MBT](https://github.com/FXDavid-OffbeatForex/MBT) — the MCP server TLC uses to pull live broker bars

---

*TLC outputs signals, not orders. Nothing here is financial advice.*
