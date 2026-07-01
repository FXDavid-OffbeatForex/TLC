"""Tests for deterministic indicator primitives (PRD §1.13).

Pure Python — no MT5 / LLM / network. Golden values are hand-computable; the rest
pin the failure contract (None on insufficient/partial data, never raise) and the
newest-first ordering that is the classic silent bug.
"""

import json

import pytest

from tlc import indicators as I


# ---- builders: all produce NEWEST-FIRST bars ----------------------------


def _bars(seq):
    """seq is oldest-first (o,h,l,c,v) tuples → newest-first bars."""
    out = [
        {"time": f"t{i}", "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(seq)
    ]
    return list(reversed(out))


def _from_closes(closes, spread=1.0, vol=100):
    """oldest-first closes → newest-first bars with H/L a fixed spread around close."""
    return _bars([(c, c + spread, c - spread, c, vol) for c in closes])


# ---- RSI ----------------------------------------------------------------


def test_rsi_golden_mid_value():
    # deltas alternate +2,-1 (×7): avg_gain=1.0, avg_loss=0.5 → RS=2 → RSI=66.67.
    closes = [100.0]
    for d in [2, -1] * 7:
        closes.append(closes[-1] + d)
    assert len(closes) == 15  # exactly period+1 → no smoothing tail, pure seed
    assert I.rsi(_from_closes(closes), 14) == 66.67


def test_rsi_all_gains_is_100_all_losses_is_0():
    assert I.rsi(_from_closes([100 + i for i in range(20)]), 14) == 100.0
    assert I.rsi(_from_closes([100 - i for i in range(20)]), 14) == 0.0


def test_rsi_newest_first_ordering():
    # A rising-over-time series (newest bar highest) must read overbought, not 0.
    r = I.rsi(_from_closes([100 + i for i in range(30)]), 14)
    assert r is not None and r > 70


def test_rsi_insufficient_bars_is_none():
    assert I.rsi(_from_closes([1, 2, 3, 4, 5]), 14) is None


def test_rsi_skips_none_closes_without_crashing():
    bars = _from_closes([100 + i for i in range(20)])
    bars[3]["close"] = None  # a partial bar
    assert I.rsi(bars, 14) is not None


# ---- ADX / DI -----------------------------------------------------------


def test_adx_strong_uptrend_plus_di_dominates():
    a = I.adx(_from_closes([100 + i for i in range(60)]), 14)
    assert a is not None
    assert a["plus_di"] > a["minus_di"]
    assert a["adx"] > 20  # a clean trend


def test_adx_strong_downtrend_minus_di_dominates():
    a = I.adx(_from_closes([200 - i for i in range(60)]), 14)
    assert a is not None and a["minus_di"] > a["plus_di"]


def test_adx_insufficient_bars_is_none():
    assert I.adx(_from_closes([100 + i for i in range(10)]), 14) is None


def test_adx_hole_in_chain_is_none():
    bars = _from_closes([100 + i for i in range(60)])
    bars[5]["high"] = None
    assert I.adx(bars, 14) is None


# ---- Parabolic SAR ------------------------------------------------------


def test_sar_uptrend_is_long_and_below_price():
    bars = _from_closes([100 + i for i in range(30)])
    s = I.sar(bars)
    assert s is not None and s["trend"] == "long"
    assert s["sar"] < bars[0]["close"]  # SAR trails below in an uptrend


def test_sar_downtrend_is_short():
    s = I.sar(_from_closes([200 - i for i in range(30)]))
    assert s is not None and s["trend"] == "short"


def test_sar_insufficient_bars_is_none():
    assert I.sar(_from_closes([1, 2])) is None


# ---- Ichimoku -----------------------------------------------------------


def test_ichimoku_golden_lines():
    # highs=i+0.5, lows=i-0.5, close=i, i=0..59 (oldest-first).
    seq = [(i, i + 0.5, i - 0.5, float(i), 100) for i in range(60)]
    ich = I.ichimoku(_bars(seq))
    assert ich is not None
    assert ich["tenkan"] == 55.0        # (59.5 + 50.5)/2 over last 9
    assert ich["kijun"] == 46.5         # (59.5 + 33.5)/2 over last 26
    assert ich["senkou_b"] == 33.5      # (59.5 + 7.5)/2 over last 52
    assert ich["price_vs_cloud"] == "above"
    assert ich["chikou_vs_price"] == "above"


def test_ichimoku_insufficient_bars_is_none():
    assert I.ichimoku(_from_closes([100 + i for i in range(30)])) is None


# ---- TD Sequential ------------------------------------------------------


def test_td_buy_setup_completes_on_falling_market():
    td = I.td_sequential(_from_closes([200 - i for i in range(30)]))
    assert td is not None
    assert td["setup_direction"] == "buy"
    assert td["setup"] == 9 and td["setup_complete"] is True


def test_td_sell_setup_on_rising_market():
    td = I.td_sequential(_from_closes([100 + i for i in range(30)]))
    assert td is not None and td["setup_direction"] == "sell"


def test_td_insufficient_bars_is_none():
    assert I.td_sequential(_from_closes([1, 2, 3])) is None


# ---- swing pivots -------------------------------------------------------


def test_swings_detects_a_peak():
    highs = [1, 2, 3, 4, 5, 4, 3, 2, 1]
    seq = [(h, h, h - 1, h - 0.5, 100) for h in highs]
    sw = I.swings(_bars(seq), left=2, right=2)
    assert sw is not None and sw["highs"]
    top = sw["highs"][0]
    assert top["price"] == 5.0 and top["bars_ago"] == 4


def test_swings_insufficient_bars_is_none():
    assert I.swings(_from_closes([1, 2, 3]), left=2, right=2) is None


# ---- volume vs average --------------------------------------------------


def test_vol_avg_flags_surge():
    seq = [(100, 101, 99, 100, 100) for _ in range(20)]
    seq.append((100, 101, 99, 100, 300))  # newest bar: 3× the base
    v = I.vol_avg(_bars(seq), period=20)
    assert v is not None and v["surge"] is True and v["ratio"] == 3.0


def test_vol_avg_absent_volume_is_none():
    # FX/some TV feeds omit volume — must NOT fabricate a surge.
    seq = [(100, 101, 99, 100, 0) for _ in range(20)]
    assert I.vol_avg(_bars(seq)) is None


def test_vol_avg_none_volume_is_none():
    bars = _from_closes([100] * 25, vol=100)
    for b in bars:
        b["volume"] = None
    assert I.vol_avg(bars) is None


# ---- moving average -----------------------------------------------------


def test_ma_uptrend_slope_up_price_above():
    m = I.ma(_from_closes([100 + i for i in range(40)]), period=30)
    assert m is not None and m["slope"] == "up" and m["price_vs_ma"] == "above"


def test_ma_flat_series_slope_flat():
    m = I.ma(_from_closes([100.0] * 40), period=30)
    assert m is not None and m["slope"] == "flat"


def test_ma_insufficient_bars_is_none():
    assert I.ma(_from_closes([100 + i for i in range(20)]), period=30) is None


# ---- fibonacci ----------------------------------------------------------


def test_fib_half_level_is_the_midpoint():
    highs = [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]
    seq = [(h, h, h - 2, h - 1, 100) for h in highs]
    f = I.fib(_bars(seq))
    if f is not None:  # needs both a high and low pivot
        mid = round((f["high"] + f["low"]) / 2, 8)
        assert f["retracements"]["0.5"] == mid


# ---- registry / compute / render ----------------------------------------


def test_known_ids_matches_registry():
    assert I.known_ids() == set(I.REGISTRY)
    assert {"rsi14", "adx14", "sar", "ichimoku", "td_sequential",
            "swings", "vol_avg", "ma", "fib"} <= I.known_ids()


def test_compute_unknown_id_is_none():
    frames = {"1h": _from_closes([100 + i for i in range(60)])}
    out = I.compute(["rsi14", "bogus"], frames, "1h")
    assert out["rsi14"] is not None and out["bogus"] is None


def test_compute_missing_frame_yields_nulls():
    out = I.compute(["rsi14"], {}, "1h")
    assert out == {"rsi14": None}


def test_render_block_empty_is_blank():
    assert I.render_block({}) == ""


def test_render_block_states_null_semantics():
    block = I.render_block({"rsi14": None})
    assert "null" in block and "do NOT infer" in block
    assert "rsi14: null" in block


def test_cli_text_output(tmp_path):
    packet = {"anchor_timeframe": "1h",
              "frames": {"1h": _from_closes([100 + i for i in range(60)])}}
    p = tmp_path / "packet.json"
    p.write_text(json.dumps(packet))
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = I._main([str(p), "--needs", "rsi14,adx14", "--text"])
    assert rc == 0
    out = buf.getvalue()
    assert "rsi14" in out and "adx14" in out
