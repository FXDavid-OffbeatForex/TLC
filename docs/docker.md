# Docker deployment

Docker ships as the **TradingView deployment** — it matches TLC's existing
two-lane model (TradingView → Linux, MT5 → Windows), the image just embodies the
Linux/TradingView lane. See the README's "Run in Docker" section for the quick
start; this page covers the detail.

## Docker = the TradingView lane

- The default image/compose (`docker-compose.yml`, `docker/config.tradingview.yaml`)
  runs TradingView; it needs `TVR_API_KEY` (+ an LLM key in `.env` for a full
  convene).
- **MT5 is not in the image.** `MetaTrader5` is a Windows-only package that
  attaches to a running `terminal64.exe` via local IPC — it can never live in a
  Linux container.
- **Fail loud, not a crash:** running `platform: mt5` in the container with no
  bridge configured raises a plain-English error pointing you at the two real
  options (use TradingView, or set up the bridge below) — never a raw
  `MetaTrader5` import trace. Implemented in `Mt5Provider.fetch`
  (`tlc/providers/mt5.py`).

## MT5 in Docker — the networked bridge (advanced, opt-in)

**Problem:** since MT5 can't live in the container, running `platform: mt5`
there would otherwise just fail. This is the **opt-in escape hatch** for users
who genuinely need MT5 + containers — it is *not* the default lane.

**Solution:** decouple the Windows-bound part behind a small HTTP bridge. You
run MT5 + the bridge on your own Windows/Wine host; TLC (in Docker, anywhere)
fetches bars over HTTP:

```
[ Your Windows/MT5 host ]                      [ TLC in Docker, Linux ]
  MT5 terminal + mt5-bridge (FastAPI /ohlc)  ── HTTP ──▶  mt5 provider (bridge mode)
```

**Design:** the bridge is used *only when configured* — native installs are
untouched.
- New config: `platforms.mt5.bridge_url` (+ `bridge_api_key`).
- `Mt5Provider.fetch`: if `bridge_url` is set → `POST {bridge_url}/ohlc`; else →
  the existing local MBT / `MetaTrader5` path exactly as before.
- Same platform name (`mt5`), same routing, same symbol-suffix resolution
  (applied TLC-side before the call). Only the data-source transport changes.

**The bridge** (`mt5-bridge/`, forked from `astracharts-ai/mt5-bridge`): a small
FastAPI service — `POST /ohlc {symbol,timeframe,count}` → bars
`{timestamp(ms),open,high,low,close,volume}`; also `/health` and `/symbols`. It
runs on the Windows/MT5 host (it imports `MetaTrader5`).

**Testing without a real MT5:** a stdlib **mock bridge** (`mt5-bridge/mock/`)
serves synthetic OHLC in the same `/ohlc` shape, so the full
container → `bridge_url` → provider → packet flow is verifiable on Linux with no
MetaTrader5 and no keys — see `docker-compose.mt5-bridge.yml`.

## Recommended topology (two boxes)

```
Windows host (MT5, native)              Linux box (always-on)
  MT5 terminal + mt5-bridge  ── HTTP ──▶  TLC in Docker (bridge_url → Windows:8000)
```

Each piece on its natural host: MT5 native on Windows, TLC containerized on
Linux. The Windows side runs *only* the bridge (a 2-endpoint service:
`/health` + `/ohlc`) — no TLC, no Docker needed there.

## Security (bridge)

- **Transport:** `bridge_api_key` is sent as an `X-API-Key` header. Over plain
  HTTP it travels in cleartext, so once the bridge leaves `localhost`, **require
  a private network or TLS.** Ranked:
  1. **VPN / private network** (Tailscale, WireGuard) — the bridge is never
     reachable from the public internet at all. This is the recommended setup.
  2. Public port firewalled to the TLC box's IP + a TLS reverse proxy in front
     of the bridge.
  3. **Not recommended:** public port + API key only, with no TLS — the key
     still travels in cleartext.

  Securing the network the bridge runs on is an **operator responsibility** —
  TLC can't provision your network for you, so this is documented, not built.
- **Auth:** the guard (`require_api_key`) uses `hmac.compare_digest` — a
  constant-time comparison so a wrong key can't be recovered via response
  timing. Enforced only when `BRIDGE_API_KEY` is set; the bridge logs a warning
  on startup if it's left unset.
- **`/health` is intentionally unauthenticated** — it's a liveness probe only
  and returns no market data.
- **Not built yet** (fine for private/VPN use; needed only if you ever expose
  the bridge publicly): rate limiting, request-size caps, and binding to a
  private interface by default — the bridge binds `0.0.0.0` today.
