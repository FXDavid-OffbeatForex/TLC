"""Mock MT5 bridge — stdlib only, no MetaTrader5, no FastAPI, no broker.

Serves synthetic OHLC in the exact same shape as the real bridge's `/ohlc`, so the
full TLC flow (container → bridge_url → mt5 provider → market packet) can be tested
on Linux with zero external dependencies or keys (PRD §8b, "Testing without MT5").

Run:  python3 mock_bridge.py            # listens on :8000
Env:  PORT (default 8000), BRIDGE_API_KEY (optional; if set, X-API-Key enforced)
"""

from __future__ import annotations

import hmac
import json
import math
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}
_TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}
API_KEY = os.getenv("BRIDGE_API_KEY", "")


def _synth_bars(symbol: str, timeframe: str, count: int) -> list:
    """Deterministic-ish sine-wave candles, oldest-first (like MT5 copy_rates)."""
    step = _TF_SECONDS.get(timeframe, 3600)
    now = int(time.time())
    now -= now % step
    base = 100.0 + (sum(ord(c) for c in symbol) % 50)  # per-symbol price level
    bars = []
    for i in range(count):
        idx = count - 1 - i                      # oldest first
        ts = (now - idx * step) * 1000           # milliseconds
        wave = math.sin(idx / 6.0) * 2.0
        o = base + wave
        c = base + math.sin((idx + 1) / 6.0) * 2.0
        h = max(o, c) + 0.5
        low = min(o, c) - 0.5
        bars.append({
            "timestamp": ts,
            "open": round(o, 5), "high": round(h, 5),
            "low": round(low, 5), "close": round(c, 5),
            "volume": 1000 + idx,
        })
    return bars


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quieter
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "mock": True,
                             "auth": "enabled" if API_KEY else "disabled"})
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        if self.path != "/ohlc":
            self._send(404, {"detail": "not found"})
            return
        if API_KEY and not hmac.compare_digest(self.headers.get("X-API-Key", ""), API_KEY):
            self._send(401, {"detail": "invalid or missing X-API-Key"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"detail": "bad json"})
            return
        symbol = req.get("symbol", "EURUSD")
        timeframe = req.get("timeframe", "1h")
        count = int(req.get("count", 100))
        if timeframe not in TIMEFRAMES:
            self._send(400, {"detail": f"invalid timeframe; allowed {sorted(TIMEFRAMES)}"})
            return
        bars = _synth_bars(symbol, timeframe, count)
        self._send(200, {"symbol": symbol, "timeframe": timeframe,
                         "data": bars, "count": len(bars)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"mock MT5 bridge on :{port} (auth {'on' if API_KEY else 'off'})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
