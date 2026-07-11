"""Tests for the running-PnL footer (tlc/pnl.py + the Telegram wiring).

Pure-Python: outcomes.jsonl is written by hand (the same shape trade_gate emits)
and aggregated; the Telegram send is faked so the footer is asserted as text.
"""

import json
import os

import pytest

from tlc import pnl
from tlc.sinks.telegram import TelegramSink, format_pnl_footer


def _o(outcome, r, symbol="EURUSD", tf="4h", platform="mt5",
       started_at="2026-07-11 00:00"):
    return {"name": f"{symbol}_{tf}", "symbol": symbol, "timeframe": tf,
            "platform": platform, "outcome": outcome, "r": r,
            "started_at": started_at}


def _write(data_dir, *rows):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "outcomes.jsonl"), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


# ---- compute() --------------------------------------------------------------

def test_compute_empty_is_none():
    assert pnl.compute([]) is None


def test_compute_core_stats():
    rows = [_o("WIN", 2.0), _o("LOSS", -1.0), _o("LOSS", -1.0), _o("WIN", 2.0)]
    s = pnl.compute(rows)
    assert s["closed"] == 4 and s["decisive"] == 4
    assert s["wins"] == 2 and s["losses"] == 2 and s["expired"] == 0
    assert s["win_rate"] == pytest.approx(0.5)
    assert s["net_r"] == pytest.approx(2.0)
    assert s["gross_win_r"] == pytest.approx(4.0)
    assert s["gross_loss_r"] == pytest.approx(2.0)
    assert s["profit_factor"] == pytest.approx(2.0)
    assert s["expectancy_r"] == pytest.approx(0.5)
    assert s["avg_win_r"] == pytest.approx(2.0)
    assert s["avg_loss_r"] == pytest.approx(-1.0)
    assert s["max_dd_r"] == pytest.approx(-2.0)   # peak +2 → trough 0
    assert s["since"] == "2026-07-11 00:00"


def test_expired_excluded_from_ratios_but_counted():
    rows = [_o("WIN", 2.0), _o("LOSS", -1.0), _o("EXPIRED", 0.0)]
    s = pnl.compute(rows)
    assert s["closed"] == 3 and s["decisive"] == 2 and s["expired"] == 1
    assert s["win_rate"] == pytest.approx(0.5)      # 1 of 2 decisive, not 1 of 3
    assert s["expectancy_r"] == pytest.approx(0.5)  # net 1.0 / 2 decisive


def test_profit_factor_none_without_losses():
    s = pnl.compute([_o("WIN", 2.0), _o("WIN", 1.5)])
    assert s["profit_factor"] is None
    assert format_pnl_footer(s).count("∞") == 1     # rendered as infinity glyph


def test_currency_layer_from_config():
    rows = [_o("WIN", 2.0), _o("LOSS", -1.0)]
    risk = pnl.risk_cash_from_config({"account_balance": 10000, "risk_per_trade_pct": 1.0})
    assert risk == pytest.approx(100.0)
    s = pnl.compute(rows, risk_cash=risk, currency="USD")
    assert s["currency"]["net"] == pytest.approx(100.0)   # net +1.0R * $100
    assert s["currency"]["code"] == "USD"


def test_risk_cash_none_when_no_balance():
    assert pnl.risk_cash_from_config({}) is None
    assert pnl.risk_cash_from_config({"account_balance": None}) is None
    assert pnl.risk_cash_from_config({"account_balance": 0}) is None


# ---- running_stats(): scoping ----------------------------------------------

def test_running_stats_filters_by_identity(tmp_path):
    data = str(tmp_path / "data")
    _write(data,
           _o("WIN", 2.0, symbol="EURUSD", tf="4h"),
           _o("LOSS", -1.0, symbol="GBPUSD", tf="4h"),   # different symbol
           _o("WIN", 2.0, symbol="EURUSD", tf="1h"))     # different tf
    s = pnl.running_stats(data, "EURUSD", "4h", "mt5")
    assert s["closed"] == 1 and s["wins"] == 1


def test_running_stats_scopes_to_latest_start(tmp_path):
    data = str(tmp_path / "data")
    _write(data,
           _o("LOSS", -1.0, started_at="2026-06-01 00:00"),   # a prior, cleared run
           _o("WIN", 2.0, started_at="2026-07-11 00:00"),     # current run
           _o("WIN", 2.0, started_at="2026-07-11 00:00"))
    s = pnl.running_stats(data, "EURUSD", "4h", "mt5")
    assert s["closed"] == 2 and s["losses"] == 0    # old run dropped
    assert s["since"] == "2026-07-11 00:00"


def test_running_stats_none_when_no_outcomes(tmp_path):
    assert pnl.running_stats(str(tmp_path / "data"), "EURUSD", "4h", "mt5") is None


# ---- footer rendering & sink integration -----------------------------------

def test_format_footer_none_when_empty():
    assert format_pnl_footer(None) is None
    assert format_pnl_footer({"closed": 0}) is None


def test_telegram_sink_appends_footer(tmp_path, monkeypatch):
    data = str(tmp_path / "data")
    _write(data, _o("WIN", 2.0), _o("LOSS", -1.0), _o("WIN", 2.0))
    sent = []
    monkeypatch.setattr(TelegramSink, "send", lambda self, text: sent.append(text))

    sink = TelegramSink(token="t", chat_id="c", show_pnl=True, data_dir=data,
                        pnl_cfg={"account_balance": 10000, "risk_per_trade_pct": 1.0})
    ok = sink.emit_verdict({"decision": "LONG", "symbol": "EURUSD",
                            "timeframe": "4h", "platform": "mt5",
                            "entry": 1.085, "stop": 1.08, "target": 1.095})
    assert ok is True and len(sent) == 1
    msg = sent[0]
    assert "Track record" in msg
    assert "3 closed" in msg and "2W / 1L" in msg
    assert "USD" in msg                          # currency estimate present


def test_footer_omitted_when_show_pnl_off(tmp_path, monkeypatch):
    data = str(tmp_path / "data")
    _write(data, _o("WIN", 2.0))
    sent = []
    monkeypatch.setattr(TelegramSink, "send", lambda self, text: sent.append(text))
    sink = TelegramSink(token="t", chat_id="c", show_pnl=False, data_dir=data)
    sink.emit_verdict({"decision": "LONG", "symbol": "EURUSD", "timeframe": "4h",
                       "platform": "mt5", "entry": 1.085, "stop": 1.08, "target": 1.095})
    assert "Track record" not in sent[0]
