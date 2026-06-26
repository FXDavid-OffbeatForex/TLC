"""Tests for the deterministic core (no MT5 / no LLM needed)."""

import pytest

from tlc.normalize import canonical_timeframe, canonical_symbol
from tlc.market_packet import atr, build_packet
from tlc.ballot import validate_ballot, to_mbt_signal, is_directional
from tlc.chairman import aggregate


# ---- normalize ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("15m", "15m"), ("M15", "15m"), ("m15", "15m"), ("15", "15m"),
    ("H1", "1h"), ("1h", "1h"), ("D1", "1d"), ("W1", "1w"), ("240", "4h"),
])
def test_canonical_timeframe(raw, expected):
    assert canonical_timeframe(raw) == expected


def test_canonical_timeframe_invalid():
    with pytest.raises(ValueError):
        canonical_timeframe("3h")


def test_canonical_symbol():
    assert canonical_symbol(" eurusd ") == "EURUSD"
    with pytest.raises(ValueError):
        canonical_symbol("  ")


# ---- ATR / packet -------------------------------------------------------

def _bars(closes):
    # newest-first bars with simple H/L around close
    out = []
    for c in closes:
        out.append({"time": "2026-06-26 14:00", "open": c, "high": c + 1,
                    "low": c - 1, "close": c, "volume": 100})
    return out


def test_atr_basic():
    bars = _bars([110, 109, 108, 107, 106])  # newest-first
    val = atr(bars, period=14)
    assert val is not None and val > 0


def test_atr_too_few():
    assert atr([], 14) is None
    assert atr(_bars([100]), 14) is None


def test_build_packet():
    frames = {"1h": _bars([110, 109, 108]), "4h": _bars([110, 108, 106])}
    p = build_packet("EURUSD", "1h", frames)
    assert p["symbol"] == "EURUSD"
    assert p["current_price"] == 110          # newest close
    assert set(p["atr"]) == {"1h", "4h"}
    with pytest.raises(ValueError):
        build_packet("EURUSD", "15m", frames)  # anchor not present


# ---- ballot -------------------------------------------------------------

def _long_ballot(legend="wyckoff", conviction=0.8):
    return {
        "legend": legend, "symbol": "EURUSD", "timeframe": "1h",
        "direction": "LONG", "conviction": conviction,
        "entry": 1.0840, "invalidation": 1.0790, "target": 1.0960,
        "regime_assumption": "range-to-markup", "created_at": "2026-06-26 14:00",
    }


def test_valid_long_ballot():
    assert validate_ballot(_long_ballot()) == []


def test_flat_ballot_ok_without_levels():
    b = {"legend": "gann", "symbol": "EURUSD", "timeframe": "1h",
         "direction": "FLAT", "conviction": 0.0}
    assert validate_ballot(b) == []
    assert not is_directional(b)
    assert to_mbt_signal(b) is None


def test_bad_geometry_long():
    b = _long_ballot()
    b["invalidation"] = 1.0900  # above entry — invalid for LONG
    errs = validate_ballot(b)
    assert any("LONG requires" in e for e in errs)


def test_conviction_range():
    b = _long_ballot(conviction=1.5)
    assert any("conviction" in e for e in validate_ballot(b))


def test_to_mbt_signal_mapping():
    sig = to_mbt_signal(_long_ballot())
    assert sig["sl"] == 1.0790 and sig["tp"] == 1.0960
    assert sig["direction"] == "LONG" and sig["regime"] == "range-to-markup"
    assert set(sig) == {"time", "symbol", "timeframe", "direction", "entry", "sl", "tp", "regime"}


# ---- chairman -----------------------------------------------------------

def _short_ballot(legend, conviction=0.8):
    return {
        "legend": legend, "symbol": "EURUSD", "timeframe": "1h",
        "direction": "SHORT", "conviction": conviction,
        "entry": 1.0840, "invalidation": 1.0900, "target": 1.0720,
        "regime_assumption": "distribution", "created_at": "2026-06-26 14:00",
    }


def _flat(legend):
    return {"legend": legend, "symbol": "EURUSD", "timeframe": "1h",
            "direction": "FLAT", "conviction": 0.0}


def test_consensus_trade():
    ballots = [_long_ballot(f"L{i}", 0.8) for i in range(7)] + [_short_ballot("S1", 0.5)]
    v = aggregate(ballots, threshold=0.65)
    assert v["decision"] == "LONG"
    assert v["consensus"] > 0.65
    assert v["stop"] == 1.0790 and v["target"] == 1.0960
    assert v["rr"] and v["rr"] > 0
    assert "S1" in v["against"] and len(v["for"]) == 7


def test_split_is_no_trade():
    ballots = [_long_ballot("L1"), _long_ballot("L2"),
               _short_ballot("S1"), _short_ballot("S2")]
    v = aggregate(ballots, threshold=0.65)
    assert v["decision"] == "NO_TRADE"


def test_below_threshold_no_trade():
    # 3 long vs 2 short, equal conviction → consensus 0.6 < 0.65
    ballots = [_long_ballot(f"L{i}") for i in range(3)] + [_short_ballot(f"S{i}") for i in range(2)]
    v = aggregate(ballots, threshold=0.65)
    assert v["decision"] == "NO_TRADE"
    assert v["consensus"] == pytest.approx(0.6)


def test_abstain_listed():
    ballots = [_long_ballot(f"L{i}", 0.9) for i in range(6)] + [_flat("gann")]
    v = aggregate(ballots, threshold=0.65)
    assert v["decision"] == "LONG"
    assert "gann" in v["abstain"]


def test_weights_swing_outcome():
    # 2 short vs 3 long by count, but short legends weighted 3x → short wins
    ballots = [_long_ballot(f"L{i}", 0.8) for i in range(3)] + \
              [_short_ballot("S1", 0.8), _short_ballot("S2", 0.8)]
    weights = {"S1": 3.0, "S2": 3.0}
    v = aggregate(ballots, weights=weights, threshold=0.6)
    assert v["decision"] == "SHORT"
