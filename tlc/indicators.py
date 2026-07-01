"""Deterministic indicator primitives (PRD §1.13).

Formulaic indicators and structural primitives that language models approximate
poorly (recursive smoothing, conditional counting) — computed here in exact,
reproducible Python so a legend reasons over real numbers, not a guess.

Contract, identical to `market_packet.atr()`:
  * input bars are the exact shape a provider returns —
    {"time", "open", "high", "low", "close", "volume"} — **NEWEST-FIRST**;
  * every function returns `None` on insufficient/partial data and **never raises**
    (a bad bar must not poison the convene);
  * no MT5 / LLM / network — fully testable offline against golden series.

Only the *deterministic* part lives here. Interpretation (Elliott counts, Wyckoff
phases, Gann squaring, O'Neil base shapes) stays with the legend — these functions
feed that judgment exact primitives, they do not replace it.

CLI (used by the on-demand agent flow so both runtimes compute identically):
    python3 -m tlc.indicators <packet.json> --needs rsi14,adx14[,...] [--text]
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any, Callable, Dict, List, Optional

# --- shared helpers -------------------------------------------------------


def _finite(x: Any) -> bool:
    """True iff x is a real, finite number (not None / NaN / inf)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _chrono(bars: List[dict]) -> List[dict]:
    """Bars oldest-first (providers hand us newest-first)."""
    return list(reversed(bars))


def _col(chrono: List[dict], key: str) -> List[Optional[float]]:
    """One OHLCV column, oldest-first, non-finite values coerced to None."""
    out: List[Optional[float]] = []
    for b in chrono:
        v = b.get(key)
        out.append(float(v) if _finite(v) else None)
    return out


def _round_price(x: Optional[float]) -> Optional[float]:
    """Price levels: keep instrument precision (FX 5th decimal safe)."""
    return None if x is None else round(x, 8)


def _round_osc(x: Optional[float]) -> Optional[float]:
    """Oscillator readings (RSI/ADX/DI/ratios): two decimals is plenty."""
    return None if x is None else round(x, 2)


# --- Wilder: RSI ----------------------------------------------------------


def rsi(bars: List[dict], period: int = 14) -> Optional[float]:
    """Wilder RSI at the latest bar. None if < period+1 usable closes.

    Conventions: all-gains → 100, all-losses → 0 (avoids div-by-zero).
    """
    closes = [c for c in _col(_chrono(bars), "close") if c is not None]
    if len(closes) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    # Seed with the simple mean of the first `period`, then Wilder-smooth forward.
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0  # flat series → neutral
    rs = avg_gain / avg_loss
    return _round_osc(100.0 - 100.0 / (1.0 + rs))


# --- Wilder: ADX / +DI / -DI ---------------------------------------------


def adx(bars: List[dict], period: int = 14) -> Optional[dict]:
    """Wilder ADX with +DI/-DI at the latest bar. None if < 2*period+1 bars.

    Returns {"adx", "plus_di", "minus_di"} (all rounded), or None.
    """
    chrono = _chrono(bars)
    highs, lows, closes = _col(chrono, "high"), _col(chrono, "low"), _col(chrono, "close")
    n = len(chrono)
    if n < 2 * period + 1:
        return None
    trs: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    for i in range(1, n):
        h, low, ph, pl, pc = highs[i], lows[i], highs[i - 1], lows[i - 1], closes[i - 1]
        if None in (h, low, ph, pl, pc):
            return None  # a hole in the DM/TR chain corrupts the whole smoothing
        up, down = h - ph, pl - low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(h - low, abs(h - pc), abs(low - pc)))
    if len(trs) < 2 * period:
        return None

    # Wilder-smoothed running sums of TR / +DM / -DM.
    def _smooth(seq: List[float]) -> List[float]:
        out = [sum(seq[:period])]
        for i in range(period, len(seq)):
            out.append(out[-1] - out[-1] / period + seq[i])
        return out

    str_, sp, sm = _smooth(trs), _smooth(plus_dm), _smooth(minus_dm)
    dxs: List[float] = []
    for tr, p, m in zip(str_, sp, sm):
        if tr == 0:
            continue
        pdi, mdi = 100.0 * p / tr, 100.0 * m / tr
        denom = pdi + mdi
        dxs.append(0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom)
    if len(dxs) < period:
        return None
    adx_val = sum(dxs[:period]) / period
    for i in range(period, len(dxs)):
        adx_val = (adx_val * (period - 1) + dxs[i]) / period
    last_tr = str_[-1]
    if last_tr == 0:
        return None
    return {
        "adx": _round_osc(adx_val),
        "plus_di": _round_osc(100.0 * sp[-1] / last_tr),
        "minus_di": _round_osc(100.0 * sm[-1] / last_tr),
    }


# --- Wilder: Parabolic SAR ------------------------------------------------


def sar(bars: List[dict], af_step: float = 0.02, af_max: float = 0.2) -> Optional[dict]:
    """Parabolic SAR at the latest bar → {"sar", "trend": "long"|"short"}.

    None if < 3 clean bars. Standard Wilder iteration over oldest-first bars.
    """
    chrono = _chrono(bars)
    highs, lows = _col(chrono, "high"), _col(chrono, "low")
    if any(h is None for h in highs) or any(low is None for low in lows):
        return None
    if len(chrono) < 3:
        return None
    # Seed direction from the first two bars.
    up = highs[1] >= highs[0]
    sar_v = lows[0] if up else highs[0]
    ep = highs[1] if up else lows[1]
    af = af_step
    for i in range(2, len(chrono)):
        sar_v = sar_v + af * (ep - sar_v)
        if up:
            sar_v = min(sar_v, lows[i - 1], lows[i - 2])
            if lows[i] < sar_v:  # flip to down
                up = False
                sar_v, ep, af = ep, lows[i], af_step
            elif highs[i] > ep:
                ep, af = highs[i], min(af + af_step, af_max)
        else:
            sar_v = max(sar_v, highs[i - 1], highs[i - 2])
            if highs[i] > sar_v:  # flip to up
                up = True
                sar_v, ep, af = ep, highs[i], af_step
            elif lows[i] < ep:
                ep, af = lows[i], min(af + af_step, af_max)
    return {"sar": _round_price(sar_v), "trend": "long" if up else "short"}


# --- Hosoda: Ichimoku -----------------------------------------------------


def _mid_hl(highs: List[float], lows: List[float]) -> Optional[float]:
    if not highs or not lows:
        return None
    return (max(highs) + min(lows)) / 2.0


def ichimoku(
    bars: List[dict], tenkan: int = 9, kijun: int = 26, senkou_b: int = 52
) -> Optional[dict]:
    """Ichimoku lines at the latest bar. None if < senkou_b clean bars.

    Reports the raw line values plus `price_vs_cloud` (above|below|inside), the
    single-glance equilibrium read. Chikou is the current close (plotted 26 back);
    `chikou_vs_price` compares it to price `kijun` bars ago.
    """
    chrono = _chrono(bars)
    highs, lows, closes = _col(chrono, "high"), _col(chrono, "low"), _col(chrono, "close")
    n = len(chrono)
    if n < senkou_b or None in highs[-senkou_b:] or None in lows[-senkou_b:]:
        return None
    tk = _mid_hl(highs[-tenkan:], lows[-tenkan:])
    kj = _mid_hl(highs[-kijun:], lows[-kijun:])
    sa = None if (tk is None or kj is None) else (tk + kj) / 2.0
    sb = _mid_hl(highs[-senkou_b:], lows[-senkou_b:])
    price = closes[-1]
    vs = ""
    if price is not None and sa is not None and sb is not None:
        top, bot = max(sa, sb), min(sa, sb)
        vs = "above" if price > top else "below" if price < bot else "inside"
    chikou_vs = ""
    if n > kijun and price is not None and closes[-1 - kijun] is not None:
        chikou_vs = "above" if price > closes[-1 - kijun] else "below"
    return {
        "tenkan": _round_price(tk),
        "kijun": _round_price(kj),
        "senkou_a": _round_price(sa),
        "senkou_b": _round_price(sb),
        "chikou": _round_price(price),
        "price_vs_cloud": vs,
        "chikou_vs_price": chikou_vs,
    }


# --- DeMark: TD Sequential ------------------------------------------------


def td_sequential(bars: List[dict]) -> Optional[dict]:
    """TD Sequential setup/countdown at the latest bar. None if < 6 clean closes.

    Mechanical, deterministic — exactly what an LLM miscounts:
      * Setup: consecutive closes < close 4 bars earlier (buy) / > (sell); 9 = complete.
      * Countdown: after a completed setup, closes <= low (buy) / >= high (sell)
        2 bars earlier, counted (non-consecutive) toward 13.
      * TDST: the setup's extreme (support for a buy setup, resistance for a sell).
    Returns the run active at the latest bar.
    """
    chrono = _chrono(bars)
    closes, highs, lows = _col(chrono, "close"), _col(chrono, "high"), _col(chrono, "low")
    n = len(chrono)
    if n < 6 or None in closes:
        return None

    # Setup run ending at the latest bar.
    buy = sell = 0
    for i in range(4, n):
        if closes[i] < closes[i - 4]:
            buy, sell = buy + 1, 0
        elif closes[i] > closes[i - 4]:
            sell, buy = sell + 1, 0
        else:
            buy = sell = 0
    if buy == 0 and sell == 0:
        direction, count = "", 0
    elif buy >= sell:
        direction, count = "buy", buy
    else:
        direction, count = "sell", sell

    # Find the most recent completed setup (reach 9) to anchor countdown + TDST.
    def _completed_setups() -> List[dict]:
        runs: List[dict] = []
        b = s = 0
        start_b = start_s = None
        for i in range(4, n):
            if closes[i] < closes[i - 4]:
                if b == 0:
                    start_b = i
                b, s = b + 1, 0
                if b == 9:
                    runs.append({"dir": "buy", "start": start_b, "end": i})
                    b = 0
            elif closes[i] > closes[i - 4]:
                if s == 0:
                    start_s = i
                s, b = s + 1, 0
                if s == 9:
                    runs.append({"dir": "sell", "start": start_s, "end": i})
                    s = 0
            else:
                b = s = 0
        return runs

    countdown = 0
    tdst_support = tdst_resistance = None
    runs = _completed_setups()
    if runs:
        last = runs[-1]
        seg_h = [h for h in highs[last["start"]: last["end"] + 1] if h is not None]
        seg_l = [low for low in lows[last["start"]: last["end"] + 1] if low is not None]
        if last["dir"] == "buy" and seg_l:
            tdst_support = min(seg_l)
            for i in range(last["end"] + 1, n):
                if lows[i - 2] is not None and closes[i] <= lows[i - 2] and countdown < 13:
                    countdown += 1
        elif last["dir"] == "sell" and seg_h:
            tdst_resistance = max(seg_h)
            for i in range(last["end"] + 1, n):
                if highs[i - 2] is not None and closes[i] >= highs[i - 2] and countdown < 13:
                    countdown += 1

    return {
        "setup": min(count, 9),
        "setup_direction": direction,
        "setup_complete": count >= 9,
        "countdown": countdown,
        "tdst_support": _round_price(tdst_support),
        "tdst_resistance": _round_price(tdst_resistance),
    }


# --- structural primitive: swing pivots -----------------------------------


def swings(bars: List[dict], left: int = 2, right: int = 2, max_points: int = 6) -> Optional[dict]:
    """Fractal swing pivots. None if < left+right+1 clean bars.

    A pivot high/low is strictly higher/lower than `left` bars before and `right`
    after. Returns up to `max_points` most-recent of each, newest-first, with
    `bars_ago` (0 = latest bar).
    """
    chrono = _chrono(bars)
    highs, lows = _col(chrono, "high"), _col(chrono, "low")
    n = len(chrono)
    if n < left + right + 1 or None in highs or None in lows:
        return None
    piv_h: List[dict] = []
    piv_l: List[dict] = []
    for i in range(left, n - right):
        window = range(i - left, i + right + 1)
        if all(highs[i] >= highs[j] for j in window) and any(highs[i] > highs[j] for j in window):
            piv_h.append({"price": _round_price(highs[i]), "bars_ago": (n - 1) - i})
        if all(lows[i] <= lows[j] for j in window) and any(lows[i] < lows[j] for j in window):
            piv_l.append({"price": _round_price(lows[i]), "bars_ago": (n - 1) - i})
    piv_h.sort(key=lambda p: p["bars_ago"])
    piv_l.sort(key=lambda p: p["bars_ago"])
    return {"highs": piv_h[:max_points], "lows": piv_l[:max_points]}


# --- structural primitive: volume vs average ------------------------------


def vol_avg(bars: List[dict], period: int = 20, surge: float = 1.4) -> Optional[dict]:
    """Latest volume vs its rolling average. None if volume is unavailable.

    FX volume is *tick* volume and some TV feeds omit it entirely — when the
    window has no usable, non-zero volume we return None rather than fabricate a
    surge (PRD §1.13). `surge` ~ O'Neil's +40% breakout threshold.
    """
    vols = [v for v in _col(_chrono(bars), "volume")]
    recent = [v for v in vols[-(period + 1):] if v is not None]
    if len(recent) < 2 or all(v == 0 for v in recent):
        return None
    current = recent[-1]
    base = recent[-(period + 1):-1] or recent[:-1]
    if not base:
        return None
    average = sum(base) / len(base)
    if average == 0:
        return None
    ratio = current / average
    return {
        "current": _round_price(current),
        "average": _round_price(average),
        "ratio": _round_osc(ratio),
        "surge": ratio >= surge,
    }


# --- structural primitive: moving average + slope -------------------------


def ma(bars: List[dict], period: int = 30, kind: str = "sma", slope_lookback: int = 3) -> Optional[dict]:
    """SMA/EMA of close with a slope read. None if < period+slope_lookback closes.

    Returns {"value", "slope": up|down|flat, "price_vs_ma": above|below}.
    """
    closes = [c for c in _col(_chrono(bars), "close") if c is not None]
    if len(closes) < period + slope_lookback:
        return None

    def _sma(series: List[float]) -> float:
        return sum(series[-period:]) / period

    if kind == "ema":
        k = 2.0 / (period + 1)
        e = sum(closes[:period]) / period
        vals = [e]
        for j in range(period, len(closes)):
            e = closes[j] * k + e * (1 - k)
            vals.append(e)
        now = vals[-1]
        prev = vals[-1 - slope_lookback] if len(vals) > slope_lookback else vals[0]
    else:
        now = _sma(closes)
        prev = sum(closes[-period - slope_lookback: -slope_lookback]) / period
    delta = now - prev
    eps = abs(now) * 1e-6
    slope = "up" if delta > eps else "down" if delta < -eps else "flat"
    price = closes[-1]
    return {
        "value": _round_price(now),
        "slope": slope,
        "price_vs_ma": "above" if price >= now else "below",
    }


# --- structural primitive: fibonacci levels -------------------------------


_FIB_RETR = (0.236, 0.382, 0.5, 0.618, 0.786)
_FIB_EXT = (1.272, 1.618)


def fib(bars: List[dict], left: int = 2, right: int = 2) -> Optional[dict]:
    """Fib retracement/extension levels between the two most-recent swing pivots.

    None if swings can't be found. Direction is set by which pivot is more recent
    (up-leg: low→high; down-leg: high→low).
    """
    sw = swings(bars, left=left, right=right, max_points=1)
    if not sw or not sw["highs"] or not sw["lows"]:
        return None
    hi, lo = sw["highs"][0], sw["lows"][0]
    high, low = hi["price"], lo["price"]
    if high is None or low is None or high == low:
        return None
    up_leg = lo["bars_ago"] > hi["bars_ago"]  # low is older → most recent leg is up
    rng = high - low
    retr = {
        str(r): _round_price(high - rng * r if up_leg else low + rng * r) for r in _FIB_RETR
    }
    ext = {
        str(e): _round_price(low + rng * e if up_leg else high - rng * e) for e in _FIB_EXT
    }
    return {
        "high": _round_price(high),
        "low": _round_price(low),
        "direction": "up" if up_leg else "down",
        "retracements": retr,
        "extensions": ext,
    }


# --- registry + compute ---------------------------------------------------

# id → callable(anchor_bars) -> JSON-serializable value | None. Computed on the
# anchor frame (multi-TF legends still read the raw HTF frames in the packet).
REGISTRY: Dict[str, Callable[[List[dict]], Any]] = {
    "rsi14": lambda b: rsi(b, 14),
    "adx14": lambda b: adx(b, 14),
    "sar": lambda b: sar(b),
    "ichimoku": lambda b: ichimoku(b),
    "td_sequential": lambda b: td_sequential(b),
    "swings": lambda b: swings(b),
    "vol_avg": lambda b: vol_avg(b),
    "ma": lambda b: ma(b, 30),
    "fib": lambda b: fib(b),
}


def known_ids() -> set:
    """Registry ids — used by spec_lint to validate a spec's `needs:` (§1.12)."""
    return set(REGISTRY)


def compute(needs: List[str], frames: Dict[str, List[dict]], anchor: str) -> Dict[str, Any]:
    """Compute each requested indicator on the anchor frame.

    Unknown ids and any indicator that can't be computed map to None — the caller
    surfaces `null` to the legend as "unavailable, do not infer" (§1.13). Never
    raises: a buggy indicator must not take down the convene.
    """
    bars = frames.get(anchor) or []
    out: Dict[str, Any] = {}
    for nid in needs:
        fn = REGISTRY.get(nid)
        if fn is None:
            out[nid] = None
            continue
        try:
            out[nid] = fn(bars)
        except Exception:  # defensive: never let one indicator break the ballot
            out[nid] = None
    return out


def render_block(values: Dict[str, Any]) -> str:
    """Human/LLM-readable indicator block for the per-legend prompt tail (§1.8).

    Empty string when nothing was requested, so callers can append unconditionally.
    """
    if not values:
        return ""
    lines = [
        "Computed indicators (exact, on the anchor timeframe). "
        "null = not enough data / unavailable — treat as absent, do NOT infer a value:"
    ]
    for k, v in values.items():
        lines.append(f"- {k}: {json.dumps(v)}")
    return "\n".join(lines)


# --- CLI ------------------------------------------------------------------


def _main(argv: List[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    needs_csv = ""
    as_text = "--text" in argv
    for a in argv:
        if a.startswith("--needs"):
            needs_csv = a.split("=", 1)[1] if "=" in a else (
                argv[argv.index(a) + 1] if argv.index(a) + 1 < len(argv) else ""
            )
    if not args or not needs_csv:
        print("usage: python3 -m tlc.indicators <packet.json> --needs id1,id2 [--text]", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as fh:
        packet = json.load(fh)
    needs = [n.strip() for n in needs_csv.split(",") if n.strip()]
    values = compute(needs, packet.get("frames", {}), packet.get("anchor_timeframe", ""))
    print(render_block(values) if as_text else json.dumps(values, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
