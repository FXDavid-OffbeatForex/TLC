---
description: Schedule a recurring convening (cron) and alert on a trade via Telegram
argument-hint: set <symbol> <tf> --every <15m|1h|3d> [tv|mt5] [--council N] | list | stop <name>
allowed-tools: Read, Write, Bash
---
Manage **scheduled convenings** from **$ARGUMENTS**. A schedule is an OS cron job that
re-runs the council every interval and pushes a trade verdict to Telegram. Plain English
works too ("scan EURUSD every hour and alert me", "stop the BTC schedule"); see `CLAUDE.md`.

A scheduled fire is LLM-driven, so it runs through an **engine** (`config.yaml → engine`):
- **agent** (default) → your coding-agent CLI headless (`claude -p …`) — uses your subscription.
- **api** → `python3 -m tlc.orchestrator …` — uses your own LLM key (OpenRouter/Anthropic in `.env`).

## Before setting one up — check alerts + platform caveats
1. **Telegram:** alerts need `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` and
   `alerts.enabled: [telegram]` in `config.yaml`. If unset, tell the user the 2-minute
   BotFather setup (see README) — the schedule still installs, it just won't alert yet.
2. **TradingView only:** warn that bars are cached (5m–1h by bar size) — **don't schedule
   faster than `tv_cache_seconds`** or you re-read stale data. The tvremix budget is
   **20/min · 200/hr · 1,500/day**; the calculator (below) checks it exactly. **MT5 has
   neither** — skip these warnings for the broker feed.

## Set — `set <symbol> <tf> --every <interval>`
1. Parse interval (`15m / 30m / 1h / 2h / 3d`), symbol, tf, platform (`tv`/`mt5`), `--council`.
2. **Run the calculator and show it** (resource + budget + plan, with the affiliate link):
   `python3 -m tlc.vps_calc --jobs <N> --interval <iv> --engine <agent|api> --platform <tv|mt5>`
   - TV → recommends an InterServer slice (Linux); MT5 → deep-links the Windows VPS calculator.
   - For a non-technical user, also point them at the **interactive web sizer** —
     <https://fxdavid-offbeatforex.github.io/TLC/> — same math, with a one-click order
     button (no terminal needed).
3. Install the cron (idempotent per name; crontab on Linux/macOS, schtasks on Windows):
   `python3 -m tlc.cron set <symbol> <tf> --every <iv> [--platform tv|mt5] [--council N] [--engine api]`
   - **Auto-staggered:** jobs sharing an interval are spread across the cycle (1st at the
     tick, then +30m, +15m, +45m, …) so they don't all fire at once — this smooths the RAM
     spike and the tvremix per-minute peak. Override with `--offset <minutes>` if needed.
4. Confirm the cron expression + the exact command, and how to stop it. If the user is adding
   several symbols, mention they'll fire on different minutes (shown as `@+Nm` in `list`).

## List — `list`
`python3 -m tlc.cron list` — every installed schedule (symbol, tf, interval, platform, engine,
plus `@+Nm` stagger offset when non-zero).

## Stop — `stop <name>`
`python3 -m tlc.cron stop <name>` — removes the cron entry (and registry row). On Windows it
prints the `schtasks /delete` line to run.

## What happens on each fire
Cron wakes the engine → fresh market packet → council votes blind → Chairman verdict →
logged to `data/` → **trade verdict pushed to Telegram** (NO_TRADE stays silent unless
`quiet_no_trade: false`). For 24/7 the machine must stay on: **TV → InterServer Linux VPS**,
**MT5 → Windows VPS** (MetaTrader must run).
