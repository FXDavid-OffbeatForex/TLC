"""TvRemixProvider — bars from TradingView via the tvremix remote MCP (PRD §1.10).

tvremix is a hosted MCP server over Streamable HTTP. We talk to it directly from
Python with a tiny stdlib JSON-RPC client (no extra deps), so this provider works
headlessly — no browser extension, no TradingView tab.

  endpoint : https://tvremix.xyz/api/mcp/v1
  auth     : Authorization: Bearer tvr_…   (from $TVR_API_KEY / .env)

In the PUBLIC on-demand path the coding agent may instead call the tvremix MCP
tool directly (`mcp__tvremix__…`); this Python client is the headless equivalent
and what the tests/scoring use.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ..normalize import canonical_symbol
from .base import DataProvider

DEFAULT_ENDPOINT = "https://tvremix.xyz/api/mcp/v1"

# tvremix `interval` tokens. Confirmed against the live get_ohlcv tool:
# accepts "1m","5m","15m","30m","1h","4h","1D","1W","1M" — note the upper D/W.
_TF_TO_TVR = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W",
}

# Default exchange prefixes when the user gives a bare symbol and no exchange_map
# entry exists. Heuristic — exchange_map overrides per symbol.
_FOREX_PREFIX = "FX_IDC"
_CRYPTO_PREFIX = "BINANCE"


class TvRemixError(RuntimeError):
    pass


class McpHttpClient:
    """Minimal MCP client over Streamable HTTP (JSON-RPC 2.0)."""

    def __init__(self, endpoint: str, api_key: str, timeout: int = 30):
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._id = 0
        self._initialized = False

    def _post(self, payload: dict) -> Optional[dict]:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                body = resp.read().decode("utf-8")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:  # surface server error bodies
            detail = exc.read().decode("utf-8", "replace")
            raise TvRemixError(f"HTTP {exc.code} from tvremix: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise TvRemixError(f"cannot reach tvremix at {self.endpoint}: {exc}") from exc
        return _parse_jsonrpc_body(body, ctype)

    def _rpc(self, method: str, params: Optional[dict] = None) -> dict:
        self._id += 1
        resp = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if not resp:
            raise TvRemixError(f"empty response to {method}")
        if "error" in resp:
            raise TvRemixError(f"{method} error: {resp['error']}")
        return resp.get("result", {})

    def _notify(self, method: str, params: Optional[dict] = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict:
        result = self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "tlc", "version": "0.1.0"},
        })
        self._notify("notifications/initialized")
        self._initialized = True
        return result

    def list_tools(self) -> List[dict]:
        if not self._initialized:
            self.initialize()
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        if not self._initialized:
            self.initialize()
        return self._rpc("tools/call", {"name": name, "arguments": arguments})


def _parse_jsonrpc_body(body: str, ctype: str) -> Optional[dict]:
    """Handle both plain JSON and SSE (text/event-stream) framing."""
    if not body or not body.strip():
        return None
    if "text/event-stream" in ctype or body.lstrip().startswith(("event:", "data:")):
        last: Optional[dict] = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    try:
                        last = json.loads(chunk)
                    except json.JSONDecodeError:
                        pass
        return last
    return json.loads(body)


def _content_to_obj(result: dict) -> Any:
    """tools/call returns {content:[{type:text,text:"..."}], ...}. Pull the payload."""
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
    return result


def _epoch(val: Any) -> Optional[float]:
    """Interpret a bar time as epoch seconds, if it looks numeric."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        ts = float(val)
    elif isinstance(val, str) and val.replace(".", "", 1).isdigit():
        ts = float(val)
    else:
        return None
    return ts / 1000.0 if ts > 1e12 else ts  # tolerate milliseconds


def _fmt_time(val: Any) -> str:
    """tvremix returns epoch seconds → 'YYYY-MM-DD HH:MM' (UTC) like the rest of TLC."""
    ts = _epoch(val)
    if ts is None:
        return str(val) if val is not None else ""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def _normalize_bars(raw: Any) -> List[dict]:
    """Map tvremix bars → canonical newest-first {time,open,high,low,close,volume}."""
    rows = raw
    if isinstance(raw, dict):
        for key in ("bars", "ohlcv", "candles", "data", "results"):
            if isinstance(raw.get(key), list):
                rows = raw[key]
                break
    if not isinstance(rows, list):
        raise TvRemixError(f"unexpected bar payload shape: {type(raw).__name__}")

    parsed: List[Tuple[Optional[float], dict]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rawtime = r.get("time", r.get("timestamp", r.get("datetime", r.get("t"))))
        parsed.append((_epoch(rawtime), {
            "time": _fmt_time(rawtime),
            "open": _num(r, "open", "o"),
            "high": _num(r, "high", "h"),
            "low": _num(r, "low", "l"),
            "close": _num(r, "close", "c"),
            "volume": _num(r, "volume", "v") or 0,
        }))

    # Canonical order is newest-first. Sort by epoch when present (tvremix returns
    # oldest-first); otherwise assume oldest-first input and reverse.
    if parsed and all(p[0] is not None for p in parsed):
        parsed.sort(key=lambda p: p[0], reverse=True)
        return [b for _, b in parsed]
    return [b for _, b in reversed(parsed)]


def _num(row: dict, *keys: str) -> Optional[float]:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return None
    return None


class TvRemixProvider(DataProvider):
    name = "tradingview"

    # The live OHLCV tool name on tvremix. Verified via tools/list.
    BAR_TOOL = "get_ohlcv"

    def __init__(self, config: Optional[Dict[str, Any]] = None, api_key: Optional[str] = None,
                 rate_limiter: Optional["object"] = None):
        self.config = config or {}
        self.endpoint = self.config.get("endpoint", DEFAULT_ENDPOINT)
        self.exchange_map = {k.upper(): v for k, v in (self.config.get("exchange_map") or {}).items()}
        self.api_key = api_key or os.environ.get("TVR_API_KEY", "")
        self._client: Optional[McpHttpClient] = None
        # Budget guard (§2.16). Built lazily from config if not injected; tvremix-only.
        self._rate_limiter = rate_limiter
        self._rate_limits = self.config.get("rate_limits")

    # --- symbol resolution ------------------------------------------------
    def resolve_symbol(self, user_symbol: str) -> str:
        s = canonical_symbol(user_symbol)
        if ":" in s:                                  # already exchange-qualified
            return s
        if s in self.exchange_map:
            return self.exchange_map[s]
        from .routing import classify_asset
        asset = classify_asset(s)
        if asset == "crypto":
            base = s
            for q in ("USDT", "USDC", "USD"):
                if s.endswith(q):
                    base = s[: -len(q)]
                    break
            return f"{_CRYPTO_PREFIX}:{base}USDT"
        if asset in ("forex", "metals"):
            return f"{_FOREX_PREFIX}:{s}"
        return s                                      # stock: let tvremix resolve

    # --- fetching ---------------------------------------------------------
    def _get_client(self) -> McpHttpClient:
        if not self.api_key:
            raise TvRemixError("TVR_API_KEY is not set (see .env / .env.example)")
        if self._client is None:
            self._client = McpHttpClient(self.endpoint, self.api_key)
        return self._client

    def _limiter(self):
        """Lazy rate limiter (§2.16). Disabled when rate_limits config is absent
        or explicitly false — so existing tests/headless use stay unaffected."""
        if self._rate_limiter is not None:
            return self._rate_limiter
        if not self._rate_limits:
            return None
        from .rate_limit import RateLimiter
        data_dir = self.config.get("data_dir", "data")
        self._rate_limiter = RateLimiter(
            path=os.path.join(data_dir, "tvr_ratelimit.json"),
            limits=self._rate_limits if isinstance(self._rate_limits, dict) else None,
        )
        return self._rate_limiter

    def fetch(self, symbol: str, timeframe: str, count: int = 200) -> List[dict]:
        limiter = self._limiter()
        if limiter is not None:
            limiter.check_and_record()
        interval = _TF_TO_TVR.get(timeframe, timeframe)
        result = self._get_client().call_tool(self.BAR_TOOL, {
            "symbol": symbol,
            "interval": interval,
            "count": count,
        })
        return _normalize_bars(_content_to_obj(result))
