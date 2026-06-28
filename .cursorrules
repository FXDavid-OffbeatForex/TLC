# TLC — Trading Legends Council · Agent Guide

This file is auto-loaded by AI coding assistants (OpenAI Codex, Claude Code,
Cursor, Windsurf, etc.). It tells the agent how to run the council and handle
setup for a new user.

---

## First-run check — do this before anything else

**On every new session, before responding to any message (including greetings),
run this check:**

```bash
ls .env config.yaml 2>/dev/null
```

- If **both exist** → proceed normally. No mention of setup needed.
- If **either is missing** → run the setup flow below **directly in this
  conversation** — no terminal commands handed to the user. Do not attempt to
  convene or fetch data until setup is complete.

### Golden rule for setup: never handle secrets in the chat

**You must NEVER ask the user to paste an API key, token, or any secret into
this conversation, and you must NEVER write a secret value into `.env` yourself.**
Keys/tokens entered in chat are visible in the transcript — a credential must
never go that route. Secrets are entered by the user **privately in their own
editor**, into the blank `.env` scaffold that the agent creates.

What you *may* do in the chat: ask the non-secret choices (which platform, which
engine, alerts yes/no), and write the **non-secret** files (`config.yaml`, and a
placeholder `.env` with blank values).

### Setup flow — the agent runs all of this, in chat

Greet the user, then work through these questions one at a time. Give a brief
confirmation after each answer before moving on. When all answers are collected,
write the files yourself.

**Q1 — Data platform**
Ask which platform they want:
1. TradingView — stocks, crypto, forex (needs a free TVRemix key)
2. MT5 / MetaTrader — forex, metals (no key, runs from their broker terminal)
3. Both

**Q2 — Scheduled engine** (optional — only needed if they want cron jobs later)
Ask if they want scheduled alerts:
1. agent — uses their AI coding assistant subscription (default, no extra key)
2. api — uses their own OpenRouter or Anthropic API key
3. Skip for now

If they choose api: ask which provider, then ask which model — show these
options and let them pick by number:
  1. anthropic/claude-haiku-4.5 (fast, cheap)
  2. anthropic/claude-sonnet-4.6 (balanced — default)
  3. anthropic/claude-opus-4.8 (most capable)
  4. openai/gpt-4o-mini
  5. openai/gpt-4.1
  6. google/gemini-2.5-flash

**Q3 — Telegram alerts** (optional)
Ask yes or no. **Do not ask for any token here.**
If yes: tell the user where to get the values (get a bot token from @BotFather →
/newbot; get the chat ID by messaging the bot then visiting
`https://api.telegram.org/bot<TOKEN>/getUpdates` and copying the `id` field) —
they will paste these into `.env` later.

Then write all files yourself — no terminal, no wizard.

**Step A — Write `config.yaml`**
Read `config.example.yaml` first, then copy it and set:
- `enabled_platforms` and `default_platform` from Q1
- `engine: api`, `orchestrator.provider`, and `models` if Q2 is api
- `alerts.enabled: [telegram]` if Q3 is yes

**Step B — MT5 data bridge — only if Q1 is MT5 or Both**

MT5 bars come through **MBT** (`github.com/FXDavid-OffbeatForex/MBT`), an MCP
server. Do **all** of this yourself with your tools — clone, register, edit
configs. Never tell the user to open a terminal or run a command. The only
action they take is restarting their agent when told.

- **i. Already working?** If the `mcp__MBT__get_ohlcv` tool is already in your
  toolset, MBT is registered — skip to step (v).
- **ii. Get MBT.** MBT is gitignored, so a fresh TLC clone won't have it. If
  `./MBT` is absent, clone it yourself:
  `git clone https://github.com/FXDavid-OffbeatForex/MBT.git MBT`
  Install its deps: `pip install -r MBT/requirements.txt`.
  If `MBT/config.yaml` is missing, create it from `MBT/config.example.yaml`.
  (Skip MBT's MQL5 / indicator install steps — TLC only needs `get_ohlcv`.)
- **iii. Register the server — write `.mcp.json`** at the TLC repo root (create
  it, or merge into an existing one). `get_ohlcv` does `import MetaTrader5` (a
  Windows-only package), so the launch command depends on the OS:
  - **Windows:** `{"command": "python", "args": ["<abs>/MBT/mcp_server.py"]}`
  - **Linux/macOS (MT5 under Wine):** must run under Wine-Python —
    `{"command": "wine", "args": ["<wine-python.exe>", "<abs>/MBT/mcp_server.py"]}`.
    Find the Wine python.exe in the user's prefix (e.g.
    `~/.wine/drive_c/.../Python/*/python.exe`); if you can't locate it, ask the
    user once for that path.

  Full shape: `{"mcpServers": {"mbt": {"command": "...", "args": ["..."]}}}`
- **iv. Set the MT5 terminal path** (`mt5_path` in `MBT/config.yaml`). Offer
  two ways — you do the writing either way:
  - **A — they paste it:** "Right-click your MT5 shortcut → Properties →
    Target" (that's the `terminal64.exe` path).
  - **B — they name the broker, you find it:** search common locations
    (`~/.wine/drive_c/Program Files*/**/terminal64.exe`, or
    `C:\Program Files\...`) and propose the matches.
- **v. Broker symbol suffix.** Ask if their broker appends a suffix (e.g.
  `EURUSD` shows as `EURUSDzero`). If yes, set
  `platforms.mt5.symbol_suffix` in TLC's `config.yaml` (e.g. `zero`) and
  align `default_symbol` in `MBT/config.yaml`.
- **vi. Restart.** Tell the user to **restart their agent** so the new `mbt`
  MCP server loads (approve it if prompted) — the only step they perform, no
  terminal needed. After restart, confirm by fetching a few bars with
  `mcp__MBT__get_ohlcv`.

**Step C — Write `.env`**
Read `.env.example` first, then copy it with **every value left blank**. You are
only scaffolding the file; never put a real secret in it and never ask the user
for one in the chat. It should look like:
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

**Step D — Tell the user which blanks to fill**, based on their answers:
- TradingView or Both → `TVR_API_KEY` (free at https://tvremix.xyz → account → API keys)
- Telegram yes → `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
- api engine → `OPENROUTER_API_KEY` **or** `ANTHROPIC_API_KEY`
- MT5-only + agent engine + no Telegram → **nothing to fill — skip to smoke-test**

**Step E — Offer to open the file** so they fill it in their editor (never the
chat):
> I've created your `.env`. Want me to open it so you can paste your key(s) in?
> Your keys go straight into the file — they never pass through this chat. (yes / no)
- **yes** → open it (e.g. surface the clickable link [.env](.env) or use
  `code .env`), then: "Saved your key(s)? Tell me and I'll verify them."
- **no** → "No problem — open [.env](.env) whenever you're ready."

**Step F — Verify (optional, once they say they've filled it in).** Don't read
any key from the chat — it's already in `.env`. Run the matching live test
yourself (these load `.env` via `load_config`/`load_dotenv`, so a bare
`python3 -c` that imports the provider directly will NOT see the key — use these
exact forms):
- `TVR_API_KEY` → `python3 -m tlc.data_desk BTCUSD 1h --platform tv`
  (fetches a real packet; errors if the key is missing or bad)
- Telegram → `python3 -c "import os,json,urllib.request as R; from tlc.config import load_dotenv; load_dotenv(); t=os.environ.get('TELEGRAM_BOT_TOKEN'); c=os.environ.get('TELEGRAM_CHAT_ID'); print(R.urlopen(R.Request(f'https://api.telegram.org/bot{t}/sendMessage', data=json.dumps({'chat_id':c,'text':'TLC setup test'}).encode(), headers={'Content-Type':'application/json'})).read().decode())"`
  (sends a test message)

Then smoke-test the config:
```bash
python3 -c "from tlc.config import load_config; c=load_config(); print('config OK, platform:', c['default_platform'])"
```

Finally tell the user: "Ready! Try: **convene BTCUSD** or **what does Wyckoff
think of EURUSD?**"

---

## What the user might ask for

| The user says… | Do this |
|---|---|
| "convene on EURUSD" · "what does the council think of AAPL?" | Full council — run all 10 legends, aggregate via Chairman |
| "convene the orderflow council on EURUSD" | Custom roster — `python3 -m tlc.council show orderflow` to get members |
| "give me a gann read on EURUSD" · "how would Wyckoff see BTC?" | Single legend — run just that legend's analysis |
| "make a trader who buys liquidity sweeps" · "add an ICT legend" | Author a new legend spec in `my_legends/` |
| "build a council called scalp with wyckoff and ict_ob" | Create a roster — `python3 -m tlc.council new scalp --members wyckoff,ict_ob` |
| "what councils do I have?" / "show me the orderflow council" | `python3 -m tlc.council list` / `show <name>` |
| "scan EURUSD every hour and alert me" | Set up a cron — `python3 -m tlc.cron set EURUSD 1h --every 1h` |
| "what's scheduled?" / "stop the EURUSD schedule" | `python3 -m tlc.cron list` / `stop <name>` |
| "what VPS do I need?" | `python3 -m tlc.vps_calc --jobs 1 --interval 1h --engine api --platform tv` |
| "score my ballots" / "how is Gann doing?" | `python3 -m tlc.scoring.score data/ballots.jsonl signals.csv` |

Legend name → id map: `dow`, `wyckoff`, `livermore`, `elliott`, `gann`,
`demark`, `wilder`, `hosoda` (Ichimoku), `weinstein`, `oneil` (CAN SLIM).
Custom legends live in `my_legends/<id>.md`.

---

## Running the council

### Step 1 — Identify intent
Extract from the user's message:
- **legend(s)**: one named legend, or "the council" → all 10
- **symbol**: e.g. EURUSD, AAPL, BTCUSD (required)
- **timeframe**: default `1h` if omitted
- **platform**: see below

### Step 2 — Resolve platform

Read `config.yaml` → `enabled_platforms`, `default_platform`, `routing`.

Priority order:
1. **Explicit** — user said "tradingview"/"tv" or "mt5"/"broker"
2. **Auto-route by asset class**: forex/metals → mt5; stocks/crypto → tradingview
3. **Default** from config

If only one platform is enabled, always use it.

### Step 3 — Fetch market data

**MT5:** `mcp__MBT__get_ohlcv(symbol, timeframe, count)`
Apply `symbol_suffix` from config (e.g. EURUSD → EURUSDzero).

**TradingView:** `mcp__tvremix__get_ohlcv(symbol, interval, count)`
Symbol must be exchange-prefixed: `BINANCE:BTCUSDT`, `NASDAQ:AAPL`, `FX_IDC:EURUSD`.

**No MCP registered?** Use the headless fetcher:
```bash
python3 -m tlc.data_desk BTCUSD 1h --platform tv
```

Fetch these timeframes: `15m`, `1h`, `4h`, `1d` (200 bars each).

### Step 4 — Run legends

Each legend reads `tlc/legends/<id>.md`. Run all council members in parallel if
possible. Each legend produces a ballot:
```json
{
  "legend": "wyckoff",
  "symbol": "EURUSD",
  "timeframe": "1h",
  "direction": "LONG | SHORT | FLAT",
  "conviction": 0.75,
  "entry": 1.0840,
  "invalidation": 1.0790,
  "target": 1.0960,
  "platform": "mt5"
}
```
- `direction: FLAT` → set `conviction: 0.0`, omit levels
- `LONG`: `invalidation < entry < target`
- `SHORT`: `target < entry < invalidation`

### Step 5 — Chairman aggregates

```bash
python3 -c "
from tlc.chairman import aggregate
import json, sys
ballots = json.load(sys.stdin)
print(json.dumps(aggregate(ballots), indent=2))
" < ballots.json
```

Or use `python3 -m tlc.orchestrator` for a fully headless run.

### Step 6 — Save & alert

```bash
# Save ballots + verdict
python3 -c "from tlc.sinks import LocalJsonSink; ..."

# Send Telegram alert (if configured)
python3 -m tlc.notify data/verdicts/latest.json
```

---

## Key files

| File | Purpose |
|---|---|
| `tlc/legends/<id>.md` | Each legend's method and ballot rules |
| `tlc/legends/_single_legend_flow.md` | Step-by-step for running one legend |
| `config.yaml` | Platform, engine, alert settings (gitignored — created by setup) |
| `.env` | API keys: TVR_API_KEY, OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN (gitignored) |
| `config.example.yaml` | Template for config.yaml |
| `.env.example` | Template for .env |
| `councils/` | Named council rosters (YAML) |
| `my_legends/` | User-authored custom legends |
| `data/` | Ballots, verdicts, outcomes (gitignored) |
