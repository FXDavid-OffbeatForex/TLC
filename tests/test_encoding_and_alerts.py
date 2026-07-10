"""Regression tests for the Windows-encoding fixes and honest alert reporting.

Covers the gate-verification findings:
- Bug #4: LocalJsonSink must write JSONL as UTF-8 regardless of locale, and
  trade_gate's reader must survive a legacy locale-encoded line instead of
  breaking record's never-raises contract.
- Bug #5: a quiet_no_trade-suppressed NO_TRADE must not be reported as fired.
- Bug #3: `run_council --alert` pushes the verdict through notify (the
  on-demand alert path).
"""

import json
import sys

import pytest

from tlc import trade_gate
from tlc.notify import notify_verdict
from tlc.sinks import LocalJsonSink
from tlc.sinks.telegram import TelegramSink

EM_DASH_RATIONALE = "Consensus 40% below threshold 65% — council is split"


# ---- Bug #4: UTF-8 JSONL ----------------------------------------------------

def test_sink_writes_utf8_regardless_of_locale(tmp_path):
    sink = LocalJsonSink(str(tmp_path))
    sink.emit_verdict({"decision": "NO_TRADE", "rationale": EM_DASH_RATIONALE})
    raw = (tmp_path / "verdicts.jsonl").read_bytes()
    line = raw.decode("utf-8")  # strict: must be valid UTF-8, not cp1252
    assert json.loads(line)["rationale"] == EM_DASH_RATIONALE


def test_read_verdict_lines_roundtrips_non_ascii(tmp_path):
    sink = LocalJsonSink(str(tmp_path))
    sink.emit_verdict({"decision": "LONG", "rationale": EM_DASH_RATIONALE})
    lines = trade_gate._read_verdict_lines(str(tmp_path))
    assert json.loads(lines[0])["rationale"] == EM_DASH_RATIONALE


def test_read_verdict_lines_survives_legacy_cp1252_line(tmp_path):
    """A line written by the pre-fix sink (locale bytes) must degrade to a
    replacement character, not raise UnicodeDecodeError; lines after it must
    still parse."""
    path = tmp_path / "verdicts.jsonl"
    legacy = json.dumps({"decision": "NO_TRADE",
                         "rationale": EM_DASH_RATIONALE}, ensure_ascii=False)
    good = json.dumps({"decision": "LONG", "symbol": "EURUSD"})
    path.write_bytes(legacy.encode("cp1252") + b"\n" + good.encode("utf-8") + b"\n")

    lines = trade_gate._read_verdict_lines(str(tmp_path))  # must not raise
    assert len(lines) == 2
    assert json.loads(lines[1])["decision"] == "LONG"


# ---- Bug #5: honest "alerted:" reporting ------------------------------------

@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(TelegramSink, "send", lambda self, text: calls.append(text))
    return calls


def _alert_config():
    return {"alerts": {"enabled": ["telegram"], "telegram": {"quiet_no_trade": True}}}


def test_suppressed_no_trade_not_reported_as_fired(sent):
    fired = notify_verdict({"decision": "NO_TRADE"}, _alert_config())
    assert fired == []
    assert sent == []


def test_directional_verdict_reported_as_fired(sent):
    fired = notify_verdict({"decision": "LONG", "symbol": "EURUSD"}, _alert_config())
    assert fired == ["TelegramSink"]
    assert len(sent) == 1


def test_emit_verdict_returns_sent_status(sent):
    sink = TelegramSink(quiet_no_trade=True)
    assert sink.emit_verdict({"decision": "NO_TRADE"}) is False
    assert sink.emit_verdict({"decision": "SHORT", "symbol": "EURUSD"}) is True


# ---- Bug #3: run_council --alert --------------------------------------------

def _ballot(legend="wyckoff", direction="LONG"):
    return {
        "legend": legend, "symbol": "EURUSD", "timeframe": "1h",
        "direction": direction, "conviction": 0.8, "entry": 1.085,
        "invalidation": 1.080, "target": 1.095,
        "rationale": "test — non-ascii here too", "created_at": "2026-07-09 12:00",
    }


def test_run_council_alert_flag_notifies(tmp_path, monkeypatch, sent):
    from tlc import run_council

    ballots = tmp_path / "ballots.json"
    ballots.write_text(json.dumps([_ballot(l) for l in
                                   ("dow", "wyckoff", "livermore")]),
                       encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"data_dir: {json.dumps(str(tmp_path / 'data'))}\n"
        "alerts:\n  enabled: [telegram]\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv",
                        ["run_council", str(ballots), "--config", str(cfg), "--alert"])
    assert run_council._main() == 0
    assert len(sent) == 1  # the verdict was pushed through the alert path


def test_run_council_without_alert_flag_stays_silent(tmp_path, monkeypatch, sent):
    from tlc import run_council

    ballots = tmp_path / "ballots.json"
    ballots.write_text(json.dumps([_ballot()]), encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"data_dir: {json.dumps(str(tmp_path / 'data'))}\n"
        "alerts:\n  enabled: [telegram]\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv",
                        ["run_council", str(ballots), "--config", str(cfg)])
    assert run_council._main() == 0
    assert sent == []
