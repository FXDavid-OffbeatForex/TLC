# TLC — Claude Code dispatch guide

This file is auto-loaded by Claude Code and extends `AGENTS.md` with
Claude-specific behaviour: in-chat setup, slash commands, and MCP tool calls.
Read `AGENTS.md` for the universal dispatch table and council flow.

## Session-start banner — print this on the first reply

On the **first turn of a new session only**, before anything else (the first-run
check below, any greeting, the setup flow), print the TLC banner verbatim inside
a fenced code block so it renders monospaced:

```
████████ ██       ██████
   ██    ██      ██        TRADING LEGENDS COUNCIL
   ██    ██      ██        ten legends · one verdict
   ██    ███████  ██████
```

Print it once — on your first reply of the session, not on every message. After
the banner, continue with the first-run check and the user's request as normal.
(There is no terminal animation; an agent hook can't render one — see the `tlc`
launcher in the README for the optional animated splash.)

## First-run check — do this before anything else

**On every new session, before responding to any message (including greetings),
run this check:**

```bash
ls .env config.yaml 2>/dev/null
```

- If **both exist** → proceed normally. No mention of setup needed.
- If **either is missing** → run the setup flow below. Do not attempt to convene
  or fetch data until setup is complete.

### Golden rule for setup: never handle secrets in the chat

**You must NEVER ask the user to paste an API key, token, or any secret into this
conversation, and you must NEVER write a secret value into `.env` yourself.**
Anything typed in the chat is sent to Anthropic and stored in the transcript — a
credential must never go that route. Secrets are entered by the user **privately in their own editor** — you create a
blank `.env` scaffold and offer to open it; they paste their keys there, and the
values never pass through this conversation.

What you *may* do in the chat: ask the non-secret choices (which platform, which
engine, alerts yes/no), and write the **non-secret** files (`config.yaml`, and a
placeholder `.env` with blank values).

### Setup flow

Greet the user, then ask these three non-secret questions one at a time (a brief
confirmation after each). **Do not ask for any key or token.**

**Q1 — Data platform**
1. TradingView — stocks, crypto, forex (needs a free TVRemix key)
2. MT5 / MetaTrader — forex, metals (no key, runs from their broker terminal)
3. Both

**Q2 — Scheduled engine** (optional — only for cron jobs later)
1. agent — uses their Claude Code subscription (default, no key)
2. api — uses their own OpenRouter / Anthropic key
3. Skip for now

**Q3 — Telegram alerts** (optional)
Just ask yes / no — do **not** ask for the token here.

Then write both files yourself — no terminal, no wizard.

**1. Write `config.yaml`** — copy `config.example.yaml` (read it first), then set:
- `enabled_platforms` / `default_platform` from Q1
- `engine: api`, `orchestrator.provider`, and `models` if Q2 is api
- `alerts.enabled: [telegram]` if Q3 is yes

**1b. MT5 data bridge — only if Q1 is MT5 or Both.** MT5 bars come through **MBT**
(`github.com/FXDavid-OffbeatForex/MBT`), an MCP server. Do **all** of this yourself
with your tools — clone, register, edit configs. **Never tell the user to open a
terminal or run a command** (assume they don't have one and wouldn't know how). The
only thing they do is restart Claude Code at the end.

- **i. Already working?** If the `mcp__MBT__get_ohlcv` tool is already in your
  toolset, MBT is registered — skip straight to (v) the suffix step.
- **ii. Get MBT.** MBT is gitignored, so a fresh TLC clone won't have it. If `./MBT`
  is absent, clone it yourself: `git clone https://github.com/FXDavid-OffbeatForex/MBT.git MBT`.
  Install its deps yourself: `pip install -r MBT/requirements.txt`. If
  `MBT/config.yaml` is missing, create it from `MBT/config.example.yaml`. (Skip
  MBT's MQL5 / indicator install steps — TLC only needs `get_ohlcv`.)
- **iii. Register the server — write `.mcp.json`** at the TLC repo root (create it,
  or merge into an existing one). `get_ohlcv` does `import MetaTrader5` (a
  Windows-only package), so the launch command depends on the OS:
  - **Windows:** `{"command": "python", "args": ["<abs>/MBT/mcp_server.py"]}`
  - **Linux/macOS (MT5 under Wine):** must run under Wine-Python —
    `{"command": "wine", "args": ["<wine-python.exe>", "<abs>/MBT/mcp_server.py"]}`.
    Find the Wine python.exe in the user's prefix (e.g.
    `~/.wine/drive_c/.../Python/*/python.exe`); if you can't locate it, ask the
    user once for that path.

    Shape: `{"mcpServers": {"mbt": {"command": "...", "args": ["..."]}}}`
- **iv. Set the MT5 terminal path** (`mt5_path` in `MBT/config.yaml`). Offer two
  ways — you do the writing either way:
  - **A — they paste it:** "Right-click your MT5 shortcut → Properties → Target"
    (that's the `terminal64.exe` path).
  - **B — they name the broker, you find it:** search common locations
    (`~/.wine/drive_c/Program Files*/**/terminal64.exe`, or `C:\Program Files\...`)
    and propose the matches.
- **v. Broker symbol suffix.** Ask if their broker appends one (e.g. `EURUSD` shows
  as `EURUSDzero`). If yes, set `platforms.mt5.symbol_suffix` in TLC's `config.yaml`
  (e.g. `zero`) and align `default_symbol` in `MBT/config.yaml`.
- **vi. Restart.** Tell the user to **restart Claude Code** so the new `mbt` server
  loads (approve it if prompted) — the only step they perform, no terminal. After
  restart, confirm by fetching a few bars with `mcp__MBT__get_ohlcv`.

**2. Write `.env`** — copy `.env.example` (read it first) with **every value left
blank**. You are only scaffolding the file; never put a real secret in it and
never ask the user for one in the chat. It should look like:
```
TVR_API_KEY=

# --- Telegram alerts (optional; for scheduled mode) ---
# 1. Message @BotFather on Telegram → /newbot → copy the token here.
# 2. Send your new bot any message, then open:
#    https://api.telegram.org/bot<TOKEN>/getUpdates  → copy "chat":{"id":...} here.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# --- engine=api only (optional) ---
# Needed only if you run scheduled mode with engine: api (your own LLM key).
# Pick the one matching config.yaml orchestrator.provider.
OPENROUTER_API_KEY=
ANTHROPIC_API_KEY=
```
(keep whatever comments `.env.example` actually has).

**3. Tell them which blanks to fill**, based on their answers:
- TradingView / Both → `TVR_API_KEY` (free at https://tvremix.xyz → account → API keys)
- Telegram yes → `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- api engine → `OPENROUTER_API_KEY` **or** `ANTHROPIC_API_KEY`
- MT5 + agent + no Telegram → **nothing to fill — they're done, skip to the smoke-test.**

**4. Offer to open the file** so they fill it in their editor (never the chat):
> I've created your `.env`. Want me to open it so you can paste your key(s) in?
> Your keys go straight into the file — they never pass through this chat. (yes / no)
- **yes** → open it with `code .env` (or surface the clickable link [.env](.env)),
  then: "Saved your key(s)? Tell me and I'll verify them."
- **no** → "No problem — open [.env](.env) whenever you're ready."

**5. Verify (optional, once they say they've filled it in).** Don't read any key
from the chat — it's already in `.env`. Run the matching live test yourself
(these load `.env` via `load_config`/`load_dotenv`, so a bare `python3 -c` that
imports the provider directly will NOT see the key — use these exact forms):
- `TVR_API_KEY` → `python3 -m tlc.data_desk BTCUSD 1h --platform tv` (fetches a real packet; errors if the key is missing/bad)
- Telegram → `python3 -c "import os,json,urllib.request as R; from tlc.config import load_dotenv; load_dotenv(); t=os.environ.get('TELEGRAM_BOT_TOKEN'); c=os.environ.get('TELEGRAM_CHAT_ID'); print(R.urlopen(R.Request(f'https://api.telegram.org/bot{t}/sendMessage', data=json.dumps({'chat_id':c,'text':'TLC setup test'}).encode(), headers={'Content-Type':'application/json'})).read().decode())"` (sends a test message)

Then smoke-test the config:
```bash
python3 -c "from tlc.config import load_config; c=load_config(); print('config OK, platform:', c['default_platform'])"
```
Finally: "Ready! Try: **convene BTCUSD** or **what does Wyckoff think of EURUSD?**"

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
| "what VPS do I need?" / "size a server for 3 hourly jobs" | VPS calculator → `python3 -m tlc.vps_calc --jobs 3 --interval 1h --engine <agent\|api> --platform <tv\|mt5>`. For a non-technical user, offer the interactive web sizer instead: <https://fxdavid-offbeatforex.github.io/TLC/> |
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
`python3 -m tlc.vps_calc --jobs N --interval IV --engine E --platform P`. For a
non-technical user, point them at the **interactive web sizer** instead —
<https://fxdavid-offbeatforex.github.io/TLC/> (same math, one-click order button, no terminal).
- **TradingView** (api or agent) → **InterServer** Linux VPS (from $3/mo) — the calc picks a slice.
- **MT5** → **Windows** VPS (MetaTrader must run) — the calc deep-links our Windows calculator.

**TradingView caveats (MT5 is exempt).** Bars are cached (5m–1h by bar size) — don't
schedule faster than `tv_cache_seconds`. The key is capped 20/min · 200/hr · 1,500/day;
`tlc/providers/rate_limit.py` enforces it and the calculator checks the budget exactly.

## Golden rule

Same 10 legends, same ballots, same Chairman — the platform only changes the data
source. Resolve it, fetch, tag it, and run the normal flow.
