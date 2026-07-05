"""Mt5Provider — bars from MetaTrader 5 via the MBT toolkit (PRD §1.10).

Symbol resolution applies the broker's suffix quirk (EURUSD → EURUSDzero).

`fetch` has three paths, tried in order:
  - **Bridge mode (`bridge_url` set)** — POST to a remote MT5 HTTP bridge (PRD §8b).
    This is what lets TLC run in a Linux/Docker container while MT5 lives on a
    separate Windows/Wine host. When configured it is used exclusively; the local
    paths below are never touched.
  - In the PUBLIC on-demand path, the coding agent fetches bars itself by calling
    the MBT MCP tool `mcp__MBT__get_ohlcv` — Python cannot call an MCP tool, so
    this method is not used there.
  - On a VPS / headless run, MBT's own core (`core.ohlcv.fetch_recent`) is used,
    which needs the MetaTrader5 package (the embedded pyembed Python under Wine).
"""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..normalize import canonical_symbol
from .base import DataProvider


class Mt5BridgeError(RuntimeError):
    pass


class Mt5Provider(DataProvider):
    name = "mt5"

    def __init__(self, suffix: str = "", config: Optional[Dict[str, Any]] = None):
        self.suffix = suffix or ""
        self.config = config or {}
        # Bridge mode (PRD §8b): when set, bars come over HTTP from a remote MT5
        # bridge instead of the local MetaTrader5 package. Trailing slash trimmed
        # so f"{url}/ohlc" is always well-formed.
        self.bridge_url = (self.config.get("bridge_url") or "").rstrip("/")
        self.bridge_api_key = self.config.get("bridge_api_key") or ""

    def resolve_symbol(self, user_symbol: str) -> str:
        s = canonical_symbol(user_symbol)
        if ":" in s:                       # tolerate a TV-style prefix, strip it
            s = s.split(":")[-1]
        if self.suffix and not s.lower().endswith(self.suffix.lower()):
            return s + self.suffix
        return s

    def fetch(self, symbol: str, timeframe: str, count: int = 200) -> List[dict]:
        if self.bridge_url:
            return self._fetch_bridge(symbol, timeframe, count)
        # Headless path: defer to MBT core (needs the MetaTrader5 package).
        # MBT lives at <repo_root>/MBT by convention (CLAUDE.md/AGENTS.md Step B)
        # but is not pip-installed, so `core` is not importable until that dir is
        # on sys.path. Add it here so a LOCAL MT5 install (MBT cloned + the
        # MetaTrader5 package present) works natively — no HTTP bridge required.
        # This keeps `bridge_url` as the Docker/remote option only, matching how
        # native TLC is documented. No-op when MBT is absent (Docker/Linux), so
        # that case still falls through to the loud error below.
        import os
        import sys
        _mbt_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "MBT",
        )
        if os.path.isdir(_mbt_dir) and _mbt_dir not in sys.path:
            sys.path.insert(0, _mbt_dir)
        try:
            from core.ohlcv import fetch_recent  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on MBT + MT5 env
            # Fail LOUD and human-readable — this is what a user hits when they run
            # `platform: mt5` inside a Linux/Docker container (where MetaTrader5, a
            # Windows-only package, can never be present). Point them at the two
            # real options instead of leaking a raw import error.
            raise NotImplementedError(
                "MT5 data isn't available here: the MetaTrader5 package / MBT core "
                "could not be imported. MetaTrader5 is Windows-only and needs a "
                "running MT5 terminal, so it will never be present in a Linux/Docker "
                "container.\n"
                "Choose one:\n"
                "  • Use TradingView instead — set the platform to `tradingview` "
                "(this is the Docker/Linux lane), or\n"
                "  • keep MT5 by pointing `platforms.mt5.bridge_url` at a remote MT5 "
                "bridge running on your Windows/MT5 host — see mt5-bridge/ and "
                "docs/docker.md.\n"
                f"(underlying import error: {exc})"
            ) from exc
        return fetch_recent(symbol, timeframe, count)  # pragma: no cover

    # --- bridge mode (PRD §8b) --------------------------------------------
    def _fetch_bridge(self, symbol: str, timeframe: str, count: int) -> List[dict]:
        """POST to the remote MT5 bridge's /ohlc and adapt to canonical bars."""
        payload = json.dumps(
            {"symbol": symbol, "timeframe": timeframe, "count": count}
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.bridge_api_key:
            headers["X-API-Key"] = self.bridge_api_key
        req = urllib.request.Request(
            f"{self.bridge_url}/ohlc", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise Mt5BridgeError(
                f"MT5 bridge HTTP {exc.code} at {self.bridge_url}/ohlc: {detail[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise Mt5BridgeError(
                f"cannot reach MT5 bridge at {self.bridge_url}: {exc}"
            ) from exc
        return _normalize_bridge_bars(body)


def _normalize_bridge_bars(body: Any) -> List[dict]:
    """Bridge OHLC → canonical newest-first {time,open,high,low,close,volume}.

    The bridge returns {"data":[{timestamp(ms),open,high,low,close,volume}, ...]}
    oldest-first (MT5 copy_rates order); TLC wants newest-first with a UTC string.
    """
    rows = body.get("data") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        raise Mt5BridgeError(f"unexpected bridge payload shape: {type(body).__name__}")
    out: List[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({
            "time": _fmt_ms(r.get("timestamp")),
            "open": _num(r.get("open")),
            "high": _num(r.get("high")),
            "low": _num(r.get("low")),
            "close": _num(r.get("close")),
            "volume": _num(r.get("volume")) or 0,
        })
    out.reverse()  # oldest-first in → newest-first out (canonical)
    return out


def _fmt_ms(ms: Any) -> str:
    """Epoch milliseconds → 'YYYY-MM-DD HH:MM' UTC, matching the rest of TLC."""
    try:
        ts = float(ms) / 1000.0
    except (TypeError, ValueError):
        return str(ms) if ms is not None else ""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def _num(val: Any) -> Optional[float]:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    import math
    return f if math.isfinite(f) else None
