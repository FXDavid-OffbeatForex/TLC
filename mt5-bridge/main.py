"""TLC MT5 Bridge — a tiny FastAPI service that exposes MetaTrader 5 OHLC over HTTP.

Runs on the Windows / Wine host where MT5 lives (imports the Windows-only
`MetaTrader5` package). TLC — running anywhere, including a Linux Docker container
— fetches bars from it by setting `platforms.mt5.bridge_url` in config.yaml
(PRD §8b). This is what lets the containerized TLC use MT5 without MT5 being in the
container.

Forked from astracharts-ai/mt5-bridge with an added API-key guard: any request to a
data endpoint must carry `X-API-Key: <BRIDGE_API_KEY>` when that env var is set.
Set it before exposing the bridge on the internet — otherwise it's an open
broker-data endpoint.
"""

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import MetaTrader5 as mt5
from typing import List, Optional
import hmac
import os
from dotenv import load_dotenv
import logging
from datetime import datetime

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TLC — MT5 Bridge",
    description="MetaTrader 5 OHLC over HTTP for the Trading Legends Council",
    version="1.0.0",
)

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API-key guard --------------------------------------------------------
BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "")
if not BRIDGE_API_KEY:
    logger.warning(
        "BRIDGE_API_KEY is not set — the bridge is UNAUTHENTICATED. Set it before "
        "exposing this service on any network you do not fully control."
    )


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Enforce X-API-Key when BRIDGE_API_KEY is configured (no-op if unset)."""
    # Constant-time compare so a wrong key can't be recovered via response timing.
    if BRIDGE_API_KEY and not hmac.compare_digest(x_api_key or "", BRIDGE_API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


mt5_initialized = False

TIMEFRAME_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "30m": mt5.TIMEFRAME_M30,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "1d": mt5.TIMEFRAME_D1,
    "1w": mt5.TIMEFRAME_W1,
}


class OHLCRequest(BaseModel):
    symbol: str
    timeframe: str
    count: int = 100


class OHLCBar(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class OHLCResponse(BaseModel):
    symbol: str
    timeframe: str
    data: List[OHLCBar]
    count: int


def initialize_mt5():
    global mt5_initialized
    if not mt5_initialized:
        # Attach to a specific terminal when MT5_PATH is set — essential on a box
        # running several MT5 terminals, so the bridge can't grab the wrong one.
        mt5_path = os.getenv("MT5_PATH", "").strip()
        initialized = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
        if not initialized:
            logger.error("MT5 initialization failed")
            return False
        # os.getenv's default only applies when the var is ABSENT; a present-but-
        # blank MT5_LOGIN (the recommended form when the terminal is already logged
        # in) would make int('') raise — strip to "0" so a blank never crashes.
        login = int(os.getenv("MT5_LOGIN", "0").strip() or "0")
        password = os.getenv("MT5_PASSWORD", "")
        server = os.getenv("MT5_SERVER", "")
        if login and password and server:
            if not mt5.login(login, password, server):
                logger.error(f"MT5 login failed: {mt5.last_error()}")
                return False
            logger.info(f"MT5 connected to {server} as {login}")
        else:
            logger.warning("MT5 credentials not provided, using existing connection")
        mt5_initialized = True
    return True


@app.on_event("startup")
async def startup_event():
    if initialize_mt5():
        logger.info("MT5 Bridge started successfully")
    else:
        logger.warning("MT5 Bridge started without MT5 connection")


@app.on_event("shutdown")
async def shutdown_event():
    if mt5_initialized:
        mt5.shutdown()
        logger.info("MT5 connection closed")


@app.get("/health")
async def health_check():
    """Unauthenticated liveness probe (no market data returned)."""
    return {
        "status": "ok",
        "mt5_connected": mt5_initialized,
        "auth": "enabled" if BRIDGE_API_KEY else "disabled",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/ohlc", response_model=OHLCResponse, dependencies=[Depends(require_api_key)])
async def get_ohlc_data(request: OHLCRequest):
    """Retrieve OHLC data from MT5. This is the endpoint TLC's mt5 provider calls."""
    try:
        if not initialize_mt5():
            raise HTTPException(status_code=503, detail="MT5 not available")
        if request.timeframe not in TIMEFRAME_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timeframe. Allowed: {list(TIMEFRAME_MAP.keys())}",
            )
        mt5_timeframe = TIMEFRAME_MAP[request.timeframe]
        symbol_info = mt5.symbol_info(request.symbol)
        if symbol_info is None:
            raise HTTPException(status_code=404, detail=f"Symbol {request.symbol} not found")
        if not symbol_info.visible:
            if not mt5.symbol_select(request.symbol, True):
                raise HTTPException(status_code=500, detail=f"Failed to enable symbol {request.symbol}")
        rates = mt5.copy_rates_from_pos(request.symbol, mt5_timeframe, 0, request.count)
        if rates is None or len(rates) == 0:
            raise HTTPException(status_code=404, detail=f"No data for {request.symbol} {request.timeframe}")
        ohlc_bars = [
            OHLCBar(
                timestamp=int(rate[0]) * 1000,  # seconds → milliseconds
                open=float(rate[1]),
                high=float(rate[2]),
                low=float(rate[3]),
                close=float(rate[4]),
                volume=int(rate[5]),
            )
            for rate in rates
        ]
        logger.info(f"Retrieved {len(ohlc_bars)} bars for {request.symbol} {request.timeframe}")
        return OHLCResponse(
            symbol=request.symbol, timeframe=request.timeframe,
            data=ohlc_bars, count=len(ohlc_bars),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving OHLC data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/symbols", dependencies=[Depends(require_api_key)])
async def get_symbols():
    try:
        if not initialize_mt5():
            raise HTTPException(status_code=503, detail="MT5 not available")
        symbols = mt5.symbols_get()
        if symbols is None:
            return {"symbols": [], "count": 0}
        symbol_list = [
            {"name": s.name, "description": s.description, "path": s.path, "visible": s.visible}
            for s in symbols
        ]
        return {"symbols": symbol_list, "count": len(symbol_list)}
    except Exception as e:
        logger.error(f"Error retrieving symbols: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, log_level="info")
