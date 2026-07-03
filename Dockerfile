# TLC — Trading Legends Council · headless image · TRADINGVIEW DEPLOYMENT
#
# This is the TradingView lane (Linux/Docker). MT5 is NOT supported inside this
# container — MetaTrader5 is Windows-only. For MT5 either run TLC natively on your
# Windows host, or point `platforms.mt5.bridge_url` at a remote MT5 bridge on that
# host (advanced; see mt5-bridge/ + docs/docker.md, and the
# optional docker-compose.mt5-bridge.yml).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: build a TradingView market packet (needs TVR_API_KEY). Override for a
# full convene (also needs an LLM key) — see docker-compose.yml.
CMD ["python3", "-m", "tlc.data_desk", "BTCUSD", "1h", "--platform", "tv"]
