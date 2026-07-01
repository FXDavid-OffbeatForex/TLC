# TLC — Trading Legends Council · PRD (Public)

**Status:** Draft v2 (build-ordered)
**Last updated:** 2026-06-26
**Owner:** @FXDavid-OffbeatForex
**Codename:** TLC (Trading Legends Council) · CLI `tlc`

> Name note: "**Trading** Legends Council" (not "TA Legends") because the roster isn't pure
> technical analysis — O'Neil's CAN SLIM blends fundamentals, Livermore was a tape-reading
> speculator. The broader name survives that and leaves room for a macro/fundamentals legend later.

> Build order: **Part 1** (shared contracts) → **Part 2** (Public tier) → **Part 4** (cross-cutting).
> Premium-tier spec is in a separate private document.

---

# PART 0 — PRODUCT OVERVIEW

## 0.1 Vision
A **council of legendary traders & analysts**, each rebuilt as an independent AI agent, that analyzes
real market data — forex via **MT5/MBT**, or stocks/crypto/forex via **TradingView** (the tvremix
MCP) — and votes on a trade. A **Chairman** weighs the votes and
issues one risk-managed **verdict**. TLC scores every legend over time, letting you build a track
record and see which legends actually deliver.

Two tiers:
- **Public (open-core, this repo):** clone-and-run with your *own* coding agent **or** your own LLM
  API key — **no API key from us**. **On-demand** *and* **scheduled** (self-hosted cron) with
  **Telegram** alerts.
- **Premium (hosted):** *we* run it for you — managed continuous scanning, tuned weights, the
  distilled **verdict** feed to Discord, and a live **leaderboard**. See the premium roadmap for details.

The open-core line is **"you run it" vs "we host it"** — not a feature wall. Public can schedule and
alert; premium removes the ops (our VPS, our keys, our tuned edge, the leaderboard).

**North-star:** profitable signals — positive expectancy in R (per MBT `backtest`), enforced by the
discipline to issue **NO-TRADE** when the council disagrees.

## 0.2 Goals & non-goals
**Goals:** 10 independent legend agents → comparable ballots; a Chairman with conviction-weighted
aggregation + mandatory NO-TRADE on disagreement; on-demand mode; a feedback loop that scores every
call via MBT `backtest`; clean open-core split via the Sink interface.

**Non-goals (v1):** no automated order execution (signals only); no multi-position portfolio
optimization; no mobile app.

## 0.3 Success metrics
| Metric | Target (initial) | Source |
|---|---|---|
| Council expectancy | > 0 R, trending up | MBT `backtest` on verdicts |
| Profit factor (verdicts) | > 1.3 | MBT `backtest` |
| No-trade discipline | declines ≥ 30% of convenings | local logs |
| Legend differentiation | hit-rate spread across legends | Historian / score.py |

## 0.4 Tiering at a glance
| Capability | Public (this repo) | Premium |
|---|---|---|
| 10 legends + Chairman | ✅ | ✅ |
| Build-your-own council | ✅ (forge legends + custom rosters) | ✅ + shared/curated rosters |
| Data platforms | MT5/MBT + TradingView (tvremix) | same + hosted scanning |
| On-demand analysis | ✅ | ✅ |
| Scheduled scanning (cron) | ✅ self-hosted (`/schedule`) | ✅ managed/hosted |
| Alerts | ✅ Telegram | ✅ Discord + more |
| Execution engine | Your agent CLI **or** your own API key | Our hosted orchestrator |
| Adaptive weights | Neutral (1.0 each) | Tuned, private |
| Track record / leaderboard | Local, empty at clone | Full, hosted |
| LLM cost | **Your own agent / your own key** | Hosted |
| Discord signal feeds | ❌ | ✅ |

## 0.5 Glossary
- **Ballot** — one legend's structured vote.
- **Verdict** — the Chairman's final, risk-managed signal.
- **Convening** — one full-council run on one idea/symbol.
- **Scout** — cheap detector that triggers a convening (premium alert mode).
- **Sink** — pluggable output interface (the open-core seam).
- **R** — risk unit (reward/loss in multiples of initial risk).
- **Council** — a named roster of legends that votes together (default: the canonical 10).
- **Forge** — authoring a new legend spec from a name or a plain-English strategy (`/forge-legend`).
- **Audition** — the lint + live smoke-test a new legend must pass before it may vote.
- **Schedule** — a recurring convening installed as an OS cron job (`/schedule`); fires every
  `15m / 2h / 3d / …` and alerts on a trade verdict.
- **Engine** — what produces a verdict in a scheduled run: **agent** (your coding-agent CLI headless,
  on your subscription) or **api** (a pure-Python fan-out on your own LLM API key). Same verdict either way.
- **Alert sink** — a Sink that pushes the verdict outward; public ships **TelegramSink** (Discord is premium).

---

# PART 1 — SHARED FOUNDATIONS

Contracts used by both the public on-demand path and the premium orchestrator.
Coded once, reused everywhere.

## 1.1 Architecture (7 layers, two runtimes)
```
L0 DATA DESK     pluggable provider (MT5/MBT or TradingView) → identical "market packet" to every legend
L1 SCOUT         regime tag (+ premium: per-legend alert detectors)
L2 COUNCIL       council members (default 10), PARALLEL, BLIND → ballots
L3 THE FLOOR     optional 1-round deliberation (default OFF)
L4 CHAIRMAN      weighted aggregation → VERDICT or NO_TRADE
L5 RISK OVERLAY  size, stop, R:R, guards
L6 HISTORIAN     log → MBT backtest scores → track record
   SINK →        local JSON (public) / Discord + datastore (premium)
```

**Two runtimes, one set of brains.** A legend's persona + method + ballot contract is a single
spec file. Two runners execute it:
1. **On-demand (Public):** inside the user's coding agent (Claude Code), using the MBT MCP.
2. **Headless orchestrator (Premium):** Python service on a VPS with an LLM API.

Both load the **same specs** and emit the **same ballot schema**.

## 1.2 Market packet (input to every legend)
Built once per convening — every legend sees **identical** data (fairness).
```json
{
  "platform": "mt5",
  "symbol": "EURUSDzero",
  "anchor_timeframe": "1h",
  "as_of": "2026-06-26 07:00",
  "current_price": 1.14049,
  "atr": { "15m": 0.00069, "1h": 0.00110, "4h": 0.00258, "1d": 0.00626 },
  "frames": { "15m": [bars...], "1h": [bars...], "4h": [bars...], "1d": [bars...] }
}
```
Frames via the active provider's `fetch(symbol, tf, count)` (MT5/MBT or TradingView — see §1.10);
the packet is provider-agnostic. Single-TF legends use only the anchor frame; multi-TF legends
use the HTF frames. `atr` is a deterministic pre-computation over these same bars; legends whose
method is formulaic additionally receive exact indicator readings computed from the packet, injected
**per-legend** (never into this shared block, to keep voting blind) — see §1.13.

## 1.3 Ballot (output of every legend) — mapped 1:1 to MBT's signal schema
MBT's signal columns are `time, symbol, timeframe, direction, entry, sl, tp, regime`.
The ballot is a superset — down-projecting to those fields lets MBT's `backtest` score
every legend with zero extra plumbing.

```json
{
  "legend": "wyckoff",
  "platform": "mt5",
  "symbol": "EURUSDzero",
  "timeframe": "1h",
  "direction": "LONG",
  "conviction": 0.80,
  "entry": 1.13850,
  "invalidation": 1.13420,
  "target": 1.14800,
  "regime_assumption": "range-to-markup",
  "htf_bias": "up",
  "thesis": "Spring off the weekly accumulation low on expanding volume; SOS forming.",
  "created_at": "2026-06-26 07:00"
}
```
- `direction: FLAT` = abstain (no entry/invalidation/target required).
- `invalidation` = level that proves the legend wrong. It becomes MBT's `sl` for scoring.
- `conviction` ∈ [0,1]: how textbook the setup is for THIS legend's method.
- `platform` tags the data source (`mt5` | `tradingview`) so the outcome is scored on the same
  feed it was generated on (§1.10).

## 1.4 Verdict (output of the Chairman)
```json
{
  "platform": "mt5",
  "symbol": "EURUSDzero",
  "decision": "LONG",
  "consensus": 0.87,
  "entry": 1.13870,
  "stop": 1.13440,
  "target": 1.14750,
  "rr": 2.06,
  "size_fraction": 0.58,
  "regime": "trending_up",
  "for": ["wyckoff", "dow", "livermore", "weinstein", "oneil", "elliott", "hosoda"],
  "against": ["demark"],
  "abstain": ["gann", "wilder"],
  "rationale": "7/10 legends weighted LONG (consensus 87%); DeMark warns exhaustion; Gann/Wilder abstain — no setup in their method.",
  "created_at": "2026-06-26 07:00"
}
```

## 1.5 Roster + timeframe policy (locked)
| # | Legend | School | TF scope | Regime edge |
|---|---|---|---|---|
| 1 | Charles Dow | Dow Theory | Multi (primary/secondary/minor) | Trending |
| 2 | Richard Wyckoff | Supply/Demand, Composite Man | Multi (HTF + anchor) | Range→breakout |
| 3 | Jesse Livermore | Tape reading / pivotal points | Single (anchor) | Trending/momentum |
| 4 | Ralph N. Elliott | Wave Theory (fractal) | Multi (nested degrees) | Trending/impulsive |
| 5 | W.D. Gann | Geometry & time cycles | Multi (time + anchor) | Turning points |
| 6 | Thomas DeMark | Counter-trend (TD Sequential) | Single (anchor) | Range/exhaustion |
| 7 | J. Welles Wilder | Momentum/volatility (RSI/ADX/ATR) | Single (anchor) | Range/momentum shifts |
| 8 | Goichi Hosoda (Ichimoku) | Eastern equilibrium / time theory | Multi (cloud + anchor) | Trending/balance |
| 9 | Stan Weinstein | Stage analysis (30-wk MA) | Multi (weekly-primary) | Stage transitions |
| 10 | William O'Neil | CAN SLIM (breakouts + volume) | Multi (anchor + HTF) | Breakout/momentum |

- **Single-TF** (Livermore, DeMark, Wilder): anchor TF only. `htf_bias: ""`.
- **Multi-TF** (rest): consume HTF frames; must report `htf_bias`. HTF/LTF conflict is
  **surfaced** in the verdict, never averaged.

## 1.6 Legend ballot signatures
| Legend | Direction trigger | invalidation anchor | conviction driver |
|---|---|---|---|
| Dow | HH/HL confirmed across TFs | last secondary swing | cross-frame confirmation |
| Wyckoff | Spring/SOS (long) · UTAD/SOW (short) on volume | range floor/ceiling | volume + HTF alignment |
| Livermore | clears a pivotal point with momentum | below pivotal point | breakout strength |
| Elliott | impulse wave 3/5 · end of corrective | wave invalidation level | wave-count clarity |
| Gann | price at angle/time-square turn | beyond the angle | time+price confluence |
| DeMark | TD Sequential 9/13 exhaustion (counter-trend) | beyond exhaustion extreme | countdown completeness |
| Wilder | RSI reversal + ADX agree | ATR-based stop (1.5×ATR) | RSI/ADX agreement |
| Hosoda | Tenkan/Kijun + cloud breakout aligned | opposite cloud edge | multi-TF cloud alignment |
| Weinstein | Stage-2 breakout (long) · Stage-4 (short) >30MA | below breakout/MA | stage clarity + volume |
| O'Neil | base breakout on volume surge | below pivot/base | volume vs. average |

## 1.7 Legend spec format (single source of truth)
One file per legend at `tlc/legends/<id>.md`, loaded by **both** runtimes:
```
---
id: wyckoff
display_name: Richard Wyckoff
tf_scope: multi          # single | multi
default_anchor: 1h
regime_strengths: [range_to_breakout, accumulation, distribution]
needs: [swings, vol_avg]  # optional — deterministic indicator ids to pre-compute (§1.13)
scout_model: cheap       # OpenRouter tier (premium only — ignored in public)
council_model: mid
---
# Identity   — who they are, how they see markets
# Method     — what they compute / look for
# Timeframe rules
# Vote rules — LONG/SHORT/FLAT conditions, invalidation, conviction drivers
# Scout rule — cheap detector trigger (premium)
# Output     — return ONLY ballot JSON per §1.3
```

## 1.8 Universal council prompt (wraps each spec at runtime)
```
You are {display_name}, voting in the Trading Legends Council on {symbol} ({anchor_timeframe}).
Use ONLY your own method (below). Do not adopt other schools. You vote BLIND.

Market packet: {market_packet}
Your method: {legend_spec_body}
{indicators_block}   # per-legend, only if the spec declares `needs:` — exact readings; null = unavailable, do not infer (§1.13)

Rules:
- Output ONE ballot JSON (schema §1.3). Nothing else.
- If your setup is absent, vote FLAT — never force a trade.
- A directional vote MUST include positive entry, invalidation, target.
  LONG: invalidation < entry < target. SHORT: target < entry < invalidation.
- Stay true to your philosophy; ignore indicators outside your method.
```

## 1.9 Sink interface (the open-core seam)
```python
class Sink:
    def emit_ballot(self, ballot: dict): ...
    def emit_verdict(self, verdict: dict): ...
    def emit_outcome(self, outcome: dict): ...

class LocalJsonSink(Sink): ...      # ships in this repo (default)
class TelegramSink(Sink): ...       # ships in this repo (public alerts — §2.15)
# DiscordSink / DbSink / WebsiteSink  — premium only, not in this repo
```
`TelegramSink` is the public **alert** path: it pushes the verdict (and, optionally, nothing on
NO_TRADE) to a user's Telegram via the Bot API — stdlib `urllib`, **no new dependency**. Discord
stays premium (the community/leaderboard feed). Both implement the same three methods, so a scheduled
run can fan out to local JSON **and** Telegram with no special-casing.

## 1.10 Data providers & platforms (the data-source seam)
A **platform** governs only *where bars come from and how symbols are named*. Everything above
the bars — legends, ballots, Chairman — is identical regardless of platform. This mirrors the
Sink seam (§1.9): one interface, swappable implementations.

```python
class DataProvider:
    name: str                                          # "mt5" | "tradingview"
    def resolve_symbol(self, user_symbol: str) -> str  # EURUSD → EURUSDzero | NASDAQ:AAPL
    def fetch(self, symbol, timeframe, count) -> list   # canonical newest-first bars
    def supports(self, symbol) -> bool

class Mt5Provider(DataProvider): ...      # wraps MBT get_ohlcv (requires a running MT5 terminal)
class TvRemixProvider(DataProvider): ...  # wraps the tvremix remote MCP (requires only an API key)
```

`build_packet()` already takes `frames` as `tf → bars`; it does not care who fetched them. A
provider's only jobs are **symbol resolution** and **bar fetching**, both returning the canonical
bar shape `{time, open, high, low, close, volume}` newest-first.

**The two providers are fully independent.** MBT is the bridge to MT5 and nothing else; tvremix is
a standalone remote MCP. A user installs whichever they want:

| Want to trade… | MT5 terminal | MBT MCP | tvremix key |
|---|---|---|---|
| Forex on your broker (native feed) | ✅ | ✅ | — |
| Stocks / crypto / forex via TradingView | — | — | ✅ |
| Both | ✅ | ✅ | ✅ |

**`enabled_platforms` drives switching.** Config declares which platforms exist; the router only
routes among the enabled ones:
- **One platform enabled** → router collapses; every symbol goes there (a TV-only user fetches even
  forex from TradingView, e.g. `FX_IDC:EURUSD` — no MT5/MBT/Wine/broker needed).
- **Both enabled** → auto-route by asset class, with a per-call override.
- **Symbol routes to a non-enabled platform** → fall back to an enabled one and say so.

**Resolution order (most specific wins):**
1. **Explicit override** — a platform token/phrase on the request (`… tv` / "from tradingview").
2. **Auto-route by asset class** — a small classifier (6-letter FX pairs → forex; `USDT/USD/BTC`
   quote → crypto; else stock) maps through the `routing` table.
3. **Config default** — `default_platform` + `routing`; also the fallback when (2) is unavailable.

**Symbol namespaces.** MT5 uses broker symbols (`EURUSDzero`); TradingView uses exchange-prefixed
symbols (`NASDAQ:AAPL`, `BINANCE:BTCUSDT`, `FX_IDC:EURUSD`). Each provider's `resolve_symbol` owns
its mapping; `exchange_map` in config handles per-symbol overrides.

**Platform tagging (required for the Historian).** Every market packet, ballot, and verdict carries
`platform`. A signal generated on one feed MUST be scored on the same feed — TV bars and broker bars
differ. This also lets the leaderboard split per platform (stock-native legends vs FX). On the
TV path, where MBT's `backtest` isn't present, scoring is a small pure-Python bar replay over the
tvremix bars (same invalidation/target geometry) — so the Historian still works without MBT.

**Config shape:**
```yaml
enabled_platforms: [mt5, tradingview]   # one or both
default_platform: mt5

platforms:
  mt5:
    provider: mt5
    symbol_suffix: "zero"               # broker quirk: EURUSD → EURUSDzero
    asset_classes: [forex, metals, indices]
  tradingview:
    provider: tvremix
    endpoint: https://tvremix.xyz/api/mcp/v1   # tvr_… key from .env (TVR_API_KEY)
    asset_classes: [stocks, crypto]
    exchange_map: { AAPL: "NASDAQ:AAPL", BTCUSD: "BINANCE:BTCUSDT" }

routing:                  # asset class → platform (first match among enabled)
  forex:  mt5
  metals: mt5
  stocks: tradingview
  crypto: tradingview
```

**tvremix facts (public beta).** Remote MCP at `https://tvremix.xyz/api/mcp/v1` (Streamable HTTP),
API-key auth (`Authorization: Bearer tvr_…`), **free during beta**, rate limits **20/min · 200/hr ·
1,500/day**. OHLCV from TradingView's own feed (cached 30s–6h by interval). Headless — no browser
extension, no TradingView tab. We use **only its bar tool**; its fundamentals/options/screener are
out of scope (legends compute their own indicators from raw bars).

## 1.11 Council definitions (custom rosters)
A **council** is a named roster — which legends vote, plus optional per-council Chairman
settings. The canonical 10 are the default council; users assemble their own from core
legends, custom legends, or both.

```yaml
# councils/orderflow.yaml
name: orderflow
description: Modern orderflow + classic structure.
members: [wyckoff, livermore, ict_ob, my_breakout]
chairman:
  consensus_threshold: 0.60      # optional; else config default (0.65)
weights: {}                      # optional per-council multipliers (public default neutral)
```

- **Member resolution:** each id resolves `my_legends/<id>.md` first, then
  `tlc/legends/<id>.md`. A custom id may shadow a core legend (warned, not blocked).
- **Default council:** the canonical 10, used when none is named.
- **Shareable by design:** a council is a tiny list of ids — safe to commit and pass
  around. The *legend specs* may be a user's edge, so those live gitignored (§2.11).
  Public ships a few starter councils in `councils/`.
- Loaded by `tlc/council.py` (resolve members + settings); consumed by `/convene`.

## 1.12 Legend spec validation (the admission gate)
Any legend — core or custom — must pass a lint before it can vote, so the ballot contract
and the Historian stay intact. `tlc/spec_lint.py` checks (pure Python, testable):

- **Frontmatter:** `id` (lowercase, unique), `display_name`, `tf_scope ∈ {single, multi}`,
  `default_anchor` (canonical TF), non-empty `regime_strengths`.
- **Body sections:** Method, Vote rules (LONG/SHORT/FLAT conditions), an **invalidation
  rule**, conviction drivers, and an Output section pointing at the §1.3 ballot.
- **Scoreability:** a defined invalidation is mandatory — without it the Chairman can't set
  a stop and MBT/TV can't score the call.
- **Indicator needs (§1.13):** if `needs:` is present, each id must exist in the indicator
  registry (else a warning — a typo silently computes nothing).

A spec that lints then faces a **live audition** (§2.11) before admission to a council.

## 1.13 Indicator primitives (deterministic pre-computation)
**Problem.** Several legends' methods are *formulaic or mechanical* — RSI, ADX/DMI, the
Ichimoku lines, a TD Sequential count. An LLM asked to derive these by eyeballing 200
newest-first bars **approximates and often gets them wrong** (recursive smoothing and
conditional counting are exactly what language models are worst at). Worse, the
approximation is **non-reproducible**, so the Historian/scoring (§2.6, MBT backtest) can't
compare like-for-like across runs or engines.

**Principle — compute the deterministic part, leave interpretation to the legend.** A tool
computes RSI(14) or detects swing pivots; the legend still decides what it *means*, in
character. Interpretive cores — Elliott wave counts, Wyckoff phase/spring calls, Gann
squaring, O'Neil base *shapes* — are **never** reduced to a function (that would freeze one
rigid reading and gut the differentiated reasoning that is the product). They instead
receive exact **primitives** (pivots, fib levels, volume-vs-average) so their judgment rests
on real numbers rather than a guess.

**`tlc/indicators.py` — pure functions, same contract as `atr()` (§1.2):** newest-first bars
in, a reading out, **`None` on insufficient/partial data, never raises.** No MT5/LLM/network
— fully testable offline against golden series. The whole council is covered by ~4 formulaic
indicators + ~4 structural primitives (`atr()` already ships):

| Kind | id | Consumed by |
|---|---|---|
| formulaic | `rsi14`, `adx14` (+`di`), `sar` | Wilder |
| formulaic | `ichimoku` (Tenkan/Kijun/Senkou A·B/Chikou) | Hosoda |
| mechanical | `td_sequential` (Setup-9 / Countdown-13, TDST) | DeMark |
| primitive | `swings` (fractal pivot highs/lows) | Livermore, Dow, Gann, Wyckoff, Elliott, O'Neil |
| primitive | `vol_avg` (volume vs rolling average) | Livermore, O'Neil, Dow, Wyckoff, Weinstein |
| primitive | `ma` (SMA/EMA + slope) | Weinstein (30-MA), general |
| primitive | `fib` (retracement/extension levels between two pivots) | Gann, Elliott |

**`needs:` — per-legend declaration (§1.7).** Each spec's frontmatter lists the registry ids
it consumes, **inline form** (`needs: [rsi14, adx14, sar]`; the `_mini_yaml` fallback parses
only inline lists). Absent = compute nothing (backward-compatible; every current spec is
unchanged). Custom legends in `my_legends/` may declare `needs:` too.

**Placement — per-legend, NOT in the shared packet.** The values are injected into the
**per-legend prompt tail** (§1.8 body), computed from that legend's `needs:`. They are
deliberately *not* attached to the shared market packet (§1.2): the packet is byte-identical
across the convene and visible to every legend, so putting Wilder's RSI where Gann can read
it would break **blind, single-method voting** (§1.8, §2.4). The packet stays fair and
identical; each legend sees only its own school's numbers. (Cost is a handful of tokens per
legend; the §2.19 packet cache is untouched — the shared prefix does not change.)

**One code path, both runtimes (same-verdict guarantee).** A shared CLI —
`python3 -m tlc.indicators <packet.json> --needs rsi14,adx14` — is called by **both** the
`api` orchestrator (§2.14) and the on-demand agent flow (`_single_legend_flow.md`, §2.4).
Without this, `engine=agent` (eyeballed) and `engine=api` (exact) would produce
systematically different ballots and scoring couldn't tell them apart. The agent flow already
writes a `packet.json` temp file (§2.4) — the CLI reads it.

**Error-handling contract** (every failure → `None`, surfaced to the legend as `null`):

| Failure | Handling |
|---|---|
| Insufficient bars (RSI≥15, ADX≥~28, Ichimoku Senkou-B≥52, TD setup+13) | return `None` — mirror `atr()` |
| Partial/None OHLC bar (incomplete forming bar) | skip the bar (as `atr()` does) |
| Division by zero (RSI zero-loss → 100 by convention; ADX zero range) | explicit convention; never `x/0` |
| Volume absent/0 (FX = tick volume; some TV feeds omit it) | volume signal → `null`; do **not** fabricate a surge |
| NaN/inf input | `isfinite`-guard; emit `None`, never propagate |
| Newest-first ordering | one shared `_chrono()` helper; golden-value tests lock direction |

**`null` means "unavailable — do not infer."** The injected block states this explicitly, so a
legend treats a missing reading as absent rather than hallucinating a number (which would be
worse than today's honest eyeballing).

**Validation (§1.12).** `spec_lint` gains a check: each `needs:` entry must exist in the
registry, else a **warning** — typos (`rsii14`) become visible instead of silently no-op'ing.

**Open-core.** Public. Like packet caching (§2.19 #1) this is zero-risk and
verdict-*improving* for any self-run user — exactness and reproducibility, not a hosted-scale
cost lever.

---

# PART 2 — PUBLIC TIER

On-demand only. Runs on the **user's own agent**. No API key from us.

## 2.1 Scope
- Default council (10 legends) **or a user-built custom roster** + Chairman, equal weights (1.0 each).
- **Build-your-own council:** forge new legends (`/forge-legend`) and assemble rosters (`/council`).
- **On-demand** (`/convene SYMBOL TF [--council NAME]` or `/<legend> SYMBOL TF`).
- **Scheduled** (`/schedule`): a self-hosted cron that re-convenes every `15m / 2h / 3d / …` and
  alerts on a trade — driven by your **agent CLI** or your **own API key** (§2.14).
- Alerts to **Telegram** (§2.15); rate-limit + cache guards on the TradingView path (§2.16).
- Output: ballots + verdict printed to user, appended to local JSONL via `LocalJsonSink`,
  pushed to Telegram when scheduled.
- Optional local scoring via MBT `backtest`.

## 2.2 Public user setup — no API key required
The user's **coding agent is the LLM**:
- **Claude Code** → legends run as subagents on the user's own Claude plan.
- **Codex / Cursor / other** → runs on the user's subscription.

What a public user needs:
1. **Their own agent** (Claude Code / Codex / …)
2. **At least one data platform** (see §1.10) — either path, or both:
   - **MT5 / forex broker:** **[MBT](https://github.com/FXDavid-OffbeatForex/MBT) + a running MT5
     terminal** (broker demo is fine), registered as an MCP server exposing `get_ohlcv`. Best for
     broker-native forex and the local MBT backtest loop.
   - **TradingView (no install):** a free tvremix `tvr_…` API key, tvremix registered as a remote
     MCP. No MT5, no MBT, no Wine, no broker — covers stocks, crypto, **and** forex. Ideal for
     non-forex traders and anyone who doesn't want to install MetaTrader.

**Setup is agent-driven — no terminal wizard.** On first session (missing `.env` /
`config.yaml`), the agent detects the gap and conducts the entire setup in-chat: asks
which platform(s), clones and registers MBT via `.mcp.json` if needed, writes
`config.yaml`, creates a blank `.env` scaffold and offers to open it so the user can
paste their credentials privately in the editor (keys never pass through the chat).

Without any MCP the user can still run the council by pasting OHLCV data manually — the legend specs
are plain text and the ballot schema is JSON. MCP is the first-class experience.

## 2.3 Public repo layout
```
tlc/                      # pure-Python deterministic core (testable without MT5)
  normalize.py            # symbol/TF canonicalization (M15→15m, H1→1h, …)
  market_packet.py        # build packet + ATR from raw bars
  ballot.py               # schema + validation + MBT down-projection
  chairman.py             # weighted aggregation, NO_TRADE
  run_council.py          # CLI: ballots.json → verdict
  data_desk.py            # L0: resolve platform → fetch frames → tagged packet (CLI)
  council.py              # load council rosters + resolve members (my_legends → tlc/legends)
  spec_lint.py            # validate a legend spec (frontmatter + sections + invalidation)
  cron.py                 # /schedule engine: parse interval → cron expr → install/list/remove (§2.13)
  orchestrator.py         # engine=api: pure-Python council fan-out on your own LLM key (§2.14)
  notify.py               # format verdict → alert message → enabled alert sinks (CLI) (§2.15)
  vps_calc.py             # resource + budget + plan calculator (InterServer / Windows) (§2.17)
  config.py               # load config.yaml + .env (defaults neutral, weights=1.0)
  providers/
    base.py               # DataProvider interface (the data-source seam, §1.10)
    mt5.py                # Mt5Provider — wraps MBT get_ohlcv
    tvremix.py            # TvRemixProvider — wraps the tvremix remote MCP (+ rate-limit guard)
    rate_limit.py         # disk-persisted sliding-window limiter for tvremix (§2.16)
    routing.py            # asset-class classifier + platform resolution
  legends/
    dow.md  wyckoff.md  livermore.md  elliott.md  gann.md
    demark.md  wilder.md  hosoda.md  weinstein.md  oneil.md
    _single_legend_flow.md
  sinks/
    base.py               # Sink interface
    local_json.py         # LocalJsonSink (public default)
    telegram.py           # TelegramSink (public alerts — §2.15)
  scoring/
    score.py              # down-project ballots → MBT signal CSV
.claude/commands/
  convene.md              # /convene SYMBOL [TF] [--council NAME]
  forge-legend.md         # /forge-legend NAME|DESCRIPTION — author a new legend
  council.md              # /council new|list|show — manage custom rosters
  schedule.md             # /schedule — set up | list | stop a cron; runs the VPS calculator
  dow.md  wyckoff.md … oneil.md   # /<legend> SYMBOL [TF]
my_legends/               # user-authored legend specs (gitignored — may be your edge)
councils/                 # rosters; starter councils ship here, user councils are shareable
tests/
  test_core.py            # core: no MT5 / no LLM needed
  test_providers.py       # platform layer
  test_council.py         # spec lint + council resolution
  test_cron.py            # interval parse, cron expr, rate limiter, telegram payload, vps_calc
CLAUDE.md                 # first-run setup + dispatch (auto-loaded by Claude Code)
AGENTS.md                 # same setup flow for Codex / Cursor / Windsurf / other agents
.cursorrules              # Cursor alias of AGENTS.md
.windsurfrules            # Windsurf alias of AGENTS.md
config.example.yaml
.env.example              # TVR_API_KEY (TV) + TELEGRAM_BOT_TOKEN/CHAT_ID + OPENROUTER/ANTHROPIC key
requirements.txt
README.md
```

## 2.4 On-demand flow
```
/convene EURUSDzero 1h
  → parse intent (legend(s) / symbol / TF / platform) + normalize
  → resolve platform (explicit → auto-route by asset class → default) → pick provider
  → build market packet (provider.fetch ×{15m,1h,4h,1d}, 200 bars each)
  → council members (default 10) run BLIND in parallel — each reads its spec + shared flow
  → collect + validate ballots
  → chairman.py: conviction-weighted aggregation → VERDICT or NO_TRADE
  → display ballot table + verdict; LocalJsonSink appends to data/
```

## 2.5 The Chairman (public — equal multipliers)
- `vote_weight = self_conviction` (multipliers all 1.0; premium adds regime_fit × track_record).
- `consensus = winner_weight / (long_weight + short_weight)`.
- Consensus ≥ 0.65 → trade; else **NO_TRADE**. FLAT votes abstain (don't count in denominator).
- `stop` = median of winning-side `invalidation`s.
- `target` = median of winning-side `target`s.
- `size_fraction = min(1.0, consensus × avg_conviction)` — the risk overlay signal.

## 2.6 Public Historian (local only)
`scoring/score.py` down-projects saved ballots to MBT's signal CSV (`time,symbol,timeframe,
direction,entry,sl,tp,regime`). Run `backtest` in MBT on that CSV to get expectancy, PF, drawdown
per legend. No hosted leaderboard; no automatic weight adaptation — those are premium.

## 2.7 Phase A1 milestones ✅ (complete)
- **A1.0** Contracts: market_packet, ballot, Sink, LocalJsonSink.
- **A1.1** Wyckoff spec → ballot → MBT signal down-projection verified.
- **A1.2** Chairman + 3 legends; aggregation + NO_TRADE; verdict.
- **A1.3** All 10 legend specs; `/convene` + 10 `/<legend>` commands; README.
- **A1.4** `score.py`; live MT5 data verified via Wine/pyembed on Linux.

## 2.8 Per-legend slash commands (`/<legend> <symbol> [timeframe]`)
- **Format:** `/<legend> SYMBOL [TF]` — e.g. `/gann EURUSDzero 15m`.
- TF accepts MT5 style (M15, H1, D1) or suffix style (15m, 1h, 1d) — canonicalized internally.
- 10 thin `.claude/commands/<id>.md` files; each loads the same `tlc/legends/<id>.md`
  plus `_single_legend_flow.md` (one source of truth — no methodology duplicated).
- Output: narrative **in the legend's voice** + a ballot JSON footer.
  The ballot flows through the same Sink as `/convene`.

## 2.9 Natural-language dispatch + platform switching
In the public tier Claude Code *is* the engine, so the slash commands are **shortcuts, not the only
entry point**. The methodology lives in the legend specs + shared flow; commands and plain English
both route into the same flow. Two additions make natural-language driving robust:

**1. Intent extraction (front-step of every flow).** Step 1 becomes "parse intent," not "read
$1/$2/$3": extract **legend(s)**, **symbol**, **timeframe** (anchor default if unspecified), and
**platform** from whatever the user said — slash command *or* sentence. So *"give me a gann read on
eurusd"* runs the Gann flow exactly as `/gann eurusd` does.

**2. Dispatch doc (`CLAUDE.md`, auto-loaded).** Teaches Claude the vocabulary once:
- *"gann analysis on X"* → Gann flow · *"convene / what does the council think of X"* → `/convene`
- platform words: *"from tradingview / on TV"* → tv · *"my broker / mt5 / metatrader"* → mt5
- apply the §1.10 resolution order (explicit → auto-route → default)

**Session-sticky platform.** A stated preference persists for the conversation, not one command:
*"I only want tradingview"* sets platform = tv for every later request that turn, until the user
changes it. A durable preference is one line — `default_platform: tradingview` in config — after
which even forex goes to TradingView without saying so.

Terse override syntax stays available:
```
/convene EURUSD 1h tv      # force TradingView for this call
/gann AAPL 1h              # auto-routes to TradingView (stock)
i only want tradingview    # session-sticky; subsequent calls use TV
give me a gann read on eurusd   # natural language → Gann flow, current platform
```

Commands list **both** fetch tools in `allowed-tools` (`mcp__MBT__get_ohlcv`, `mcp__tvremix__…`).
Only the MCP servers a user actually registered are present, and the router only points at platforms
they enabled — so a TV-only user never references MBT, and an MT5-only user never references tvremix.

## 2.10 Phase A2 milestones (platforms & NL dispatch)
- **A2.0** ✅ `DataProvider` seam + `Mt5Provider` (`tlc/providers/`); `platform` added to packet
  (and flows onto ballot/verdict via the flow + Chairman).
- **A2.1** ✅ `TvRemixProvider`: stdlib MCP-over-HTTP client → live tvremix `get_ohlcv` + symbol
  resolution; `enabled_platforms` / `platforms` / `routing` config; `.env` `TVR_API_KEY`.
- **A2.2** ✅ Asset-class classifier + resolution order (explicit → auto-route → default) + alias
  parsing; single-platform collapse + fallback when a symbol routes to a non-enabled platform.
- **A2.3** ✅ `CLAUDE.md` dispatch doc + intent-extraction front-step wired into the shared flow
  and all commands (both fetch tools in `allowed-tools`; slash + NL reach the same flow).
- **A2.4** ✅ `tlc/data_desk.py` (headless packet build); platform-tagged packets; 24 new tests
  (routing, classifier, resolution order, provider symbol mapping, bar normalization). Verified
  live against tvremix for forex/stocks/crypto. *(TV-path pure-Python backtest replay: deferred to
  the Historian work.)*

## 2.11 The Council Builder (on-demand, public)
Users build their own council from the canonical 10, from new legends they author, or from
a plain-English description of a strategy (even their own). All on-demand, on the user's own
agent — no API key from us. Reuses every Part 1 contract; the only new code is authoring +
validation + roster loading.

### Authoring a legend — `/forge-legend NAME | DESCRIPTION`
**Infer-first** (the chosen UX): from a name (a documented public method) or a freeform
strategy description, draft the full §1.7 spec, then ask ONLY for fields that can't be
inferred — most often the **invalidation rule**. Flow:
1. Draft frontmatter + Method / Timeframe / Vote-rules / Output sections.
2. Fill gaps with the minimum number of questions (often zero for a known method).
3. **Lint** the draft (§1.12).
4. **Audition:** build a packet via `tlc/data_desk.py`, run the legend once on live data, and
   require a schema-valid ballot (`tlc.ballot.validate_ballot`). Where scoring is available,
   show a quick expectancy preview.
5. Save to `my_legends/<id>.md` (gitignored). Offer to add it to a council.

### Managing councils — `/council`
- `/council new <name> <id…>` or NL ("make a council 'scalp' with wyckoff, livermore,
  ict_ob") → writes `councils/<name>.yaml`.
- `/council list` · `/council show <name>` — resolve and display members + settings.

### Running a custom council
`/convene <symbol> [tf] --council <name>`, or NL ("convene the orderflow council on EURUSD").
Default stays the canonical 10. The Chairman uses the council's threshold/weights; validation,
persistence, and scoring are unchanged.

### Storage & open-core
- `my_legends/*.md` — user-authored specs, **gitignored** (a custom strategy may be your edge).
- `councils/*.yaml` — rosters: starter councils ship here; user councils are shareable plain lists.
- **Living people:** frame custom members as **strategy profiles from documented public
  methodology**, not impersonations — cleaner on branding, and users name them freely.

### Example shipped
One worked custom legend — an orderflow profile (`ict_ob`: order blocks, fair-value gaps,
liquidity sweeps, killzones, multi-TF) — plus an `orderflow` council, to prove the path
end-to-end and give users a template to copy.

## 2.12 Phase A3 milestones (Council Builder)
- **A3.0** ✅ `tlc/spec_lint.py` — legend spec validator (frontmatter + sections + invalidation),
  CLI + tests.
- **A3.1** ✅ `tlc/council.py` — council load + member resolution (my_legends → tlc/legends) +
  Chairman settings (`council_settings`); CLI list/show/new; tests.
- **A3.2** ✅ `/forge-legend` — infer-first authoring; lint + live audition; save to `my_legends/`.
- **A3.3** ✅ `/council` management + `/convene --council` + natural-language council selection
  (CLAUDE.md dispatch).
- **A3.4** ✅ Example `ict_ob` legend + `orderflow` council; README "Build your own council" +
  `.gitignore` (`my_legends/` private, example tracked). 21 new tests (lint + resolution).
- **A3.5** (stretch, deferred) Diversity advisor: warn on echo-chamber rosters by
  `regime_strengths` overlap (later: empirical vote correlation from history).

## 2.13 Scheduled mode — the public cron (`/schedule`)
On-demand answers "what does the council think *right now*." Scheduled mode runs that same convening
on a clock and **alerts you on a trade** — without leaving an agent open. Public, self-hosted, your
own compute.

**It's an OS-level cron, not a daemon.** The council is LLM-driven, so a fire must invoke an
**engine** (§2.14). `tlc/cron.py` only **generates and installs/removes** the schedule entry —
`crontab` on Linux/macOS, **Task Scheduler** (`schtasks`) on Windows — tagged with a TLC marker so we
only ever touch our own lines. A registry (`data/schedules.json`) tracks what's installed.

**Interval grammar (per minute / hour / day):** `15m`, `30m`, `1h`, `2h`, `3d`, … → cron expression:

| Interval | Cron expr | Fires |
|---|---|---|
| `15m` | `*/15 * * * *` | 96 / day |
| `1h`  | `0 * * * *`    | 24 / day |
| `2h`  | `0 */2 * * *`  | 12 / day |
| `3d`  | `0 0 */3 * *`  | ~10 / month |

**What happens on each fire (e.g. an hourly `EURUSD 1h`):**
1. Cron wakes the engine headless.
2. Resolve platform → build a fresh market packet (15m/1h/4h/1d).
3. Run the council blind → ballots → Chairman → verdict.
4. Log ballots + verdict to `data/` (same as on-demand).
5. **Trade verdict** (LONG/SHORT) → push to Telegram. **NO_TRADE** → silent by default
   (`quiet_no_trade: true`), toggleable.

`/schedule` subcommands (and natural language — "scan EURUSD every hour and alert me"):
`set <symbol> <tf> <interval> [--council N] [--platform tv|mt5]` · `list` · `stop <name>`.
At **set** time it runs the VPS calculator (§2.17) and surfaces the resource/budget/plan recommendation.

## 2.14 Execution engines — `agent` vs `api`
A scheduled fire produces a verdict one of two ways. One config knob (`engine`), identical output,
identical sinks — the same seam pattern as platforms (§1.10).

| | `engine: agent` (default) | `engine: api` |
|---|---|---|
| How | cron runs your coding-agent CLI headless (`agent_cmd: "claude -p"`, or `codex exec`, …) | cron runs `python3 -m tlc.orchestrator` |
| LLM billed to | **your subscription** (flat, cheapest) | **your own API key** (OpenRouter / Anthropic, in `.env`) |
| Best for | cost-sensitive, light/medium schedules | heavy 24/7, many symbols, guaranteed throughput |
| Models | whatever your plan gives | **per-legend tiers** (`scout_model`/`council_model` in spec frontmatter) — cheap legends, better Chairman |
| Caveat | rolling plan usage caps; CLI must be authenticated & resident | per-token cost (use cheap models to control it) |

- **`tlc/orchestrator.py`** is a basic pure-Python council fan-out: load specs → wrap each in the
  §1.8 prompt → call the LLM (concurrent) → validate ballots → Chairman → emit through the sinks.
  It is the **public, self-run** sibling of the premium hosted orchestrator — fine to ship open,
  because premium's moat is **hosting + tuned weights + leaderboard**, not the fan-out code.
- Both engines emit the **same verdict** to the **same sinks** (LocalJson + Telegram). Nothing above
  the engine changes.

## 2.15 Alerts — the Telegram sink
`TelegramSink` (§1.9) pushes a verdict to a user's Telegram. Stdlib `urllib` POST to the Bot API;
**no new dependency**.

- **Setup (free, ~2 min):** `@BotFather` → `/newbot` → **bot token**; message the bot, then read the
  **chat id** from `…/getUpdates`. Both live in `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
- **Routing:** `tlc/notify.py` formats the verdict (decision, consensus %, entry/stop/target, R:R,
  for/against legends, platform) and sends to every channel in `alerts.enabled`. CLI:
  `python3 -m tlc.notify <verdict.json>` — so the on-demand flow and both engines reach alerts the same way.
- **Noise control:** `quiet_no_trade` (default on) suppresses NO_TRADE pings.
- **Why Telegram public, Discord premium:** Telegram = *your private* alerts; Discord = the
  *community / leaderboard* feed (the premium brand surface). A generic-webhook seam (ntfy/Slack/custom)
  is an easy later add.

## 2.16 Rate-limit & cache guards (TradingView only)
MT5 (your broker feed) has neither limit nor cache — these guards apply to the tvremix path only.

- **Rate limiter** (`tlc/providers/rate_limit.py`): a disk-persisted sliding-window counter
  (`data/tvr_ratelimit.json`, shared across separate cron processes) enforcing **20/min · 200/hr ·
  1,500/day**. `TvRemixProvider.fetch` checks budget *before* a call and refuses (clear message +
  seconds-to-reset) rather than risk a key suspension. One convening = 4 frame fetches, so the math
  is exact: `calls/day = jobs × fires/day × 4`.
- **Cache awareness:** tvremix serves "Live (5m–1h cache, varies by bar size)." `/schedule` **warns**
  if a TV interval is faster than the bar's cache (a 1-minute TV cron just re-reads stale bars) and
  suggests the smallest sane interval.

## 2.17 Deployment lanes + the VPS calculator
24/7 scheduling needs an always-on machine. Two lanes, no decision paralysis:

| Data | Engine | Where | Sizing |
|---|---|---|---|
| TradingView | agent or api | **InterServer** Linux VPS (from **$3/mo**) | `tlc/vps_calc.py` (below) |
| MT5 | agent or api | **Windows** VPS (MetaTrader must run) | our website calculator |

**`tlc/vps_calc.py`** — from `#jobs · interval · engine · platform · council size` it returns:
1. **Feed budget (exact):** TV `calls/day` vs 20/min·200/hr·1,500/day; warns if over.
2. **LLM cost (api engine, est.):** `tokens/day = jobs × fires/day × legends × ~per-legend` → ~$/month.
3. **Resources (heuristic, labelled as such):** `api` ≈ 0.5 vCPU / 512 MB–1 GB; `agent` heavier (Node + CLI).
4. **Plan recommendation:** maps resources to an **InterServer slice** and the affiliate link.

**InterServer model (linear, encoded):** 1–32 slices, **$3/slice**, each slice = 2 GB RAM + 40 GB SSD
+ 2 TB transfer; cores = ⌈slices/2⌉. So slice *n* = (⌈n/2⌉ cores, 2n GB, 40n GB SSD, $3n). The
calculator picks the smallest slice meeting the RAM/CPU estimate. Plans + **affiliate links** live in a
config table (`vps_plans`) so prices/links stay correct without hardcoding; the **Windows/MT5** lane
just deep-links to `offbeatforex.com/best-forex-vps/`.

Surfaced in **two places** from one module: the README (static table + CLI snippet) **and** live in the
`/schedule` set-up step (prints the recommendation + link for the chosen engine/platform).

> Honesty note: feed-budget and API-cost math are **exact**; CPU/RAM sizing is a **heuristic** and is
> labelled so — it guides a plan choice, it doesn't promise precise utilization.

## 2.18 Phase A4 milestones (scheduling, alerts, engines, deploy)
- **A4.0** `tlc/sinks/telegram.py` (`TelegramSink`) + `tlc/notify.py` (format + route + CLI). Tests: payload formatting (mocked POST), NO_TRADE suppression.
- **A4.1** `tlc/cron.py` — interval parse → cron expr; install/list/remove (crontab + schtasks) with a TLC marker; `data/schedules.json` registry. Tests: parse + expr + registry roundtrip.
- **A4.2** `tlc/providers/rate_limit.py` + integrate into `TvRemixProvider.fetch`; cache-interval warning in `/schedule`. Tests: three windows with an injected clock; MT5 exempt.
- **A4.3** `engine: agent|api` switch; `tlc/orchestrator.py` pure-Python fan-out on the user's own key (uses `scout_model`/`council_model` tiers).
- **A4.4** `tlc/vps_calc.py` + `vps_plans` config table (InterServer linear model + affiliate link; Windows deep-link). Tests: budget math + slice selection.
- **A4.5** `.claude/commands/schedule.md` + CLAUDE.md vocabulary (schedule/alert/engine, per-fire lifecycle, deploy lanes); README: BotFather token steps, engines, two deploy lanes, calculator, rate/cache caveats. `.env.example` updated.

## 2.19 Token economics & cost controls (scheduled mode)
A scheduled convening is **token-bound**, not call-bound. The structure (§2.4, §1.8):

- Data fetch (§1.2) and the Chairman (§2.5) are **deterministic Python — zero tokens**.
- The cost is **10 LLM calls per convene** (one blind ballot per legend).
- The dominant input is the **market packet** (§1.2): `tlc/orchestrator.py` builds it **once** but
  embeds the *full* OHLCV frames into **all 10** prompts — so the packet is paid for 10× per convene.

**Baseline** (one pair, hourly, 24/7; packet ≈ 22k input tokens + ~1k spec/template per legend,
~500 output). The packet size is the swing factor — bar count and downsampling move everything.

| | Per convene | Per day (×24) | Per month (×720) |
|---|---|---|---|
| LLM calls | 10 | 240 | 7,200 |
| Input tokens | ~230k | ~5.5M | ~166M |
| Output tokens | ~5k | ~120k | ~3.6M |
| Cost — `api` Sonnet 4.6 ($3/$15) | ~$0.77 | ~$18 | ~$555 |
| Cost — `agent` (subscription) | $0 marginal — but burns rolling/weekly plan quota |||

**The lever menu.** Cumulative; ordered by risk. `api` = per-token dollars, `agent` = plan quota.

| # | Lever | Saves | Tradeoff | Engine |
|---|---|---|---|---|
| 1 | **Prompt-cache the packet** (shared prefix at ~0.1× for legends 2–10) | ~80% input | none (verdict-identical) | api (`anthropic`); auto on `agent` |
| 2 | No reasoning / strict ballot output | small $ / large quota | low | both |
| 3 | Cadence = anchor timeframe ✅ | up to ~96% fewer convenes | slower intrabar reaction (often correct) | both |
| 4 | Downsample packet (recent N bars + summary) | ~50–65% input | long-lookback legends may degrade — tune per spec | both |
| 5 | Per-legend model tiering (`scout_model`/`council_model`) | ~30–40% | cheaper models weaken interpretive methods | api |
| 6 | Change-detection skip (price unmoved vs ATR) | 30–60% of convenes | may miss a near-threshold break — always run on bar close | both |
| 7 | Cheap/deterministic pre-filter gate | ~50% of convenes | false negatives are invisible — keep the gate loose | both |
| 8 | Batch API (50% off, stacks with caching) | flat 50% | async ≤1h window — swing/position only, not intraday | api |
| 9 | Smaller council / quorum (`--council`) | linear in legends | thinner roster = weaker split detection | both |
| 10 | ~~Single merged call~~ | ~90% | **breaks blind-independent voting (§2.4) — rejected** | — |

**Stacked target** (Sonnet, one pair hourly): caching → ~$110/mo; + downsample → ~$55; + cadence
(4h anchor) → ~$14; + batch (swing) → ~$7. On `agent`, dollars are already $0 — optimize **quota** via
#2, #3, #6, #9 (#1/#8 don't apply: caching is automatic, batch isn't available on `claude -p`).

**Implementation status & open-core line.** Only the **zero-risk, universally-useful** levers ship public:
**#1 caching** (A4.6) and **#3 cadence guard** (A4.7) — both verdict-identical, both help any self-run user.
**#2, #4–#9 are deliberately NOT public** — they trade a little analysis quality or a lot of complexity for
token savings that only matter at **hosted scale** (managed scanning, a signal channel, a leaderboard,
backtesting). They live in the **premium tier and/or a private fork**, where burning fewer tokens across
many symbols 24/7 is the cost centre (reserved for the premium tier / a private fork). The menu above stays in the public PRD as the
*rationale of record*; the implementations do not. The VPS calculator's LLM-cost estimate (§2.17.2) is the
**pre-caching** figure — a safe upper bound; with #1 enabled the `anthropic` provider bills ~80% less input.

- **A4.6** ✅ Packet prompt caching (`api` engine, `anthropic` provider). `tlc/orchestrator.py` splits the
  §1.8 prompt into a **shared cacheable prefix** (framing + market packet — byte-identical across the
  convene) and a **per-legend tail** (identity + method + schema), with `cache_control: ephemeral` on the
  prefix. Verdict-identical (same tokens, reordered so the shared block leads). OpenRouter path
  concatenates unchanged (provider cache support varies). Tests: two-block content shape on `anthropic`,
  single-string parity on `openrouter`.
- **A4.7** ✅ Cadence guard. `tlc/cron.py` `cadence_warning()` compares the cron interval to the chart
  timeframe; `cron set` prints a `note:` when firing faster than a new bar prints and **still installs**
  (warn-and-allow — fast polling is valid for mid-bar alerts). Mirrors the §2.16 TV-cache guard, applied
  to the timeframe rather than the feed; verdict unaffected (changes *how often* the council convenes,
  not who votes). `/schedule` defaults the interval to the timeframe. Tests: `timeframe_seconds` parse,
  warn-when-faster, silent-when-sane, silent-on-unrecognised.

---

# PART 4 — CROSS-CUTTING

## 4.1 Open-core split
The split is **"you run it" vs "we host it"**, not a feature wall. The public repo ships every
**hook** — Sink interface (neutral default), all 10 legend specs, on-demand **and scheduled** paths,
both execution engines (your agent CLI / your own API key), the Telegram alert sink, the scoring
tool, the council builder, and the VPS calculator — and **none of the proprietary data** (track
record, tuned weights, Discord/hosted sinks). Tuned weights live in a gitignored file; public
defaults are neutral (1.0 each), so the repo runs correctly minus the earned edge.

Premium doesn't *unlock* these — it **removes the ops**: our VPS, our LLM keys, our tuned weights,
the managed scanning, the Discord feed, and the hosted leaderboard. (Affiliate VPS links in the
calculator are a public monetization seam that's orthogonal to the tier line.)

The same line governs **token cost-optimization** (§2.19). The two safe, verdict-identical levers ship
public (packet caching, cadence guard). The deeper levers — per-legend packet downsampling, model
tiering, change-detection skipping, pre-filter gating, batch submission, quorum — are a **hosted-scale**
concern (they shave token spend across many symbols running 24/7 for managed scanning, a signal channel,
a leaderboard, or backtesting) and stay **premium / private-fork**. A self-run public
user doesn't need them; they'd only add complexity and risk to the open path.

User-authored legends are theirs: `my_legends/` is gitignored so a custom strategy never leaks
into a fork. Councils (small id lists) are shareable; a curated/hosted marketplace + per-community
leaderboard is a premium extension of the same files.

## 4.2 Risks
- Legend correlation: some schools agree often → monitor, may down-weight clusters.
- Wave-count ambiguity (Elliott): counts can be subjective → conviction discount.
- Overfitting weights to short history (premium concern): use slow, robust update rule.
- TradingView via tvremix is a hosted **public beta** and rate-limited (1,500/day): treat as a
  dependency (uptime, possible future pricing); keep MT5 viable for self-hosters.
- Feed parity: TV bars ≠ broker bars — never score a signal on a different feed than it was
  generated on (enforced by the `platform` tag, §1.10).

## 4.3 Open questions (decide as we build)
- Cron watchlist + default anchor TF per symbol (basic public via `/schedule`; managed multi-symbol = premium).
- Subscription headless at 24/7 scale vs plan caps — document realistic limits per engine.
- Consensus threshold calibration (start 0.65; backtest to tune).
- Risk-overlay sizing formula (conviction → Kelly-fraction; cap needed).
- Outcome resolution cadence (how long a signal stays OPEN before scoring).
- When to enable The Floor / Devil's Advocate (cost vs. quality).
- **Entry typing & validity window.** `entry` (§1.3) is already a *price level* — MBT
  fills it when price touches it, so a resting/pending entry (breakout stop above, pullback
  limit below) is scoreable today. But the ballot has no explicit **order type**
  (market/stop/limit) — it's only implicit in entry-vs-current-price — and no **expiry**
  ("good for N bars"), so a pending entry can fill arbitrarily far in the future. Start with
  a **prompt-only** fix (legends set the method's true level and label market/stop/limit in
  the thesis; no schema change); consider an optional `entry_type` / `valid_until` later.

## 4.4 Roadmap
```
Phase A1 (PUBLIC) ✅:  contracts → legend specs → commands → live MT5 verified
Phase A2 (PUBLIC) ✅:  data-provider seam → TradingView (tvremix) → routing/switching
                       → natural-language dispatch
Phase A3 (PUBLIC) ✅:  council builder → spec lint + audition → /forge-legend
                       → custom rosters (/convene --council) → example orderflow legend
Phase A4 (PUBLIC) ⏳:  scheduled mode (/schedule cron) → Telegram alerts → engine agent|api
                       → tvremix rate-limit/cache guards → VPS calculator (InterServer/Windows)
                       → token cost controls (packet caching + cadence guard shipped; §2.19)
Phase A5 (PUBLIC) ⏳:  indicator primitives (§1.13) → tlc/indicators.py (RSI/ADX/SAR, Ichimoku,
                       TD Sequential, swings/vol_avg/ma/fib) → per-legend `needs:` injection
                       → shared CLI for both runtimes → spec-lint needs validation
Phase B  (PREMIUM):    hosted orchestrator → scouts → managed scanning → Historian/weights
                       → Discord feed → VPS/ops → website/leaderboard
                       → (custom-legend marketplace + community leaderboard)
```
