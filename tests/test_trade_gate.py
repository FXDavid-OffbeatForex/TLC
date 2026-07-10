"""Tests for the sequential open-trade gate (tlc/trade_gate.py).

Pure-Python: providers are faked, alerts disabled (or faked), the inner command
is a tiny `python -c` that writes a sentinel file — so every test proves whether
the council would actually have been convened.
"""

import datetime
import json
import os
import sys

import pytest

from tlc import trade_gate

NOW = datetime.datetime(2026, 7, 9, 12, 0)   # frozen "wall clock" (UTC, naive)
NAME = "EURUSD_1h"


# ---- harness ---------------------------------------------------------------

class FakeProvider:
    """Canonical provider: returns bars NEWEST-FIRST, like every real one."""

    def __init__(self, bars_oldest_first=None, exc=None):
        self.bars = list(bars_oldest_first or [])
        self.exc = exc
        self.calls = []

    def fetch(self, symbol, timeframe, count=200):
        self.calls.append((symbol, timeframe, count))
        if self.exc:
            raise self.exc
        return list(reversed(self.bars))


def _bar(t, high, low):
    return {"time": t, "open": (high + low) / 2, "high": high, "low": low,
            "close": (high + low) / 2, "volume": 1}


def _trade(**over):
    trade = {
        "direction": "LONG", "entry": 1.0850, "sl": 1.0800, "tp": 1.0950,
        "opened_at": "2026-07-09 08:00", "symbol": "EURUSD",
        "timeframe": "1h", "platform": "mt5",
    }
    trade.update(over)
    return trade


def _config(tmp_path, **gate_over):
    gate = {"enabled": True, "ambiguous_bar": "loss", "stale_lock_seconds": 1800,
            "max_open_bars": 1000, "warn_after_failures": 3}
    gate.update(gate_over)
    return {
        "data_dir": str(tmp_path / "data"),
        "alerts": {"enabled": []},
        "enabled_platforms": ["mt5"],
        "default_platform": "mt5",
        "platforms": {"mt5": {"provider": "mt5", "symbol_suffix": ""}},
        "routing": {"forex": "mt5"},
        "open_trade_gate": gate,
    }


def _seed_state(cfg, trade=None, checkpoint=0, failures=0, name=NAME):
    trade_gate.save_state(cfg["data_dir"], name, {
        "verdicts_checkpoint": checkpoint, "open_trade": trade,
        "consecutive_check_failures": failures,
    })


def _state(cfg, name=NAME):
    return trade_gate.load_state(cfg["data_dir"], name)


def _write_verdicts(cfg, *verdicts):
    os.makedirs(cfg["data_dir"], exist_ok=True)
    with open(os.path.join(cfg["data_dir"], "verdicts.jsonl"), "a") as fh:
        for v in verdicts:
            fh.write(json.dumps(v) + "\n")


def _verdict(**over):
    v = {"symbol": "EURUSD", "timeframe": "1h", "decision": "LONG",
         "entry": 1.0850, "stop": 1.0800, "target": 1.0950,
         "created_at": "2026-07-09 11:00", "platform": "mt5"}
    v.update(over)
    return v


def _outcomes(cfg):
    path = os.path.join(cfg["data_dir"], "outcomes.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(line) for line in fh]


@pytest.fixture
def gate_env(tmp_path, monkeypatch):
    """Frozen clock + injectable config/provider; returns a `run` helper."""
    cfg = _config(tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(trade_gate, "_utcnow", lambda: NOW)
    monkeypatch.setattr(trade_gate, "load_config", lambda path="config.yaml": cfg)
    monkeypatch.setattr(trade_gate, "get_provider", lambda platform, c=None: provider)

    sentinel = tmp_path / "inner_ran.txt"

    def run(inner=None, name=NAME, symbol="EURUSD", tf="1h", platform=""):
        if inner is None:
            inner = [sys.executable, "-c",
                     "import pathlib; pathlib.Path(r'%s').write_text('x')"
                     % sentinel.as_posix()]
        argv = ["run", name, symbol, tf]
        if platform:
            argv += ["--platform", platform]
        return trade_gate._main(argv + ["--"] + inner)

    class Env:
        pass

    env = Env()
    env.cfg = cfg
    env.provider = provider
    env.run = run
    env.inner_ran = lambda: sentinel.exists()
    return env


# ---- run: no state ----------------------------------------------------------

def test_no_state_runs_inner_and_stamps_checkpoint(gate_env):
    _write_verdicts(gate_env.cfg, {"old": True})   # pre-existing line
    assert gate_env.run() == 0
    assert gate_env.inner_ran()
    st = _state(gate_env.cfg)
    assert st["verdicts_checkpoint"] == 1          # advanced to EOF by record
    assert st["open_trade"] is None                # inner produced no verdict
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


def test_gate_disabled_runs_inner_with_no_state(gate_env):
    gate_env.cfg["open_trade_gate"]["enabled"] = False
    assert gate_env.run() == 0
    assert gate_env.inner_ran()
    assert not os.path.exists(trade_gate._state_path(gate_env.cfg["data_dir"], NAME))
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


# ---- run: open trade checks -------------------------------------------------

def test_still_open_skips_fire(gate_env):
    _seed_state(gate_env.cfg, _trade(), failures=2)
    # Bars never touch sl 1.0800 or tp 1.0950.
    gate_env.provider.bars = [_bar("2026-07-09 07:00", 1.0870, 1.0830),
                              _bar("2026-07-09 09:00", 1.0900, 1.0820),
                              _bar("2026-07-09 10:00", 1.0910, 1.0840)]
    assert gate_env.run() == 0
    assert not gate_env.inner_ran()                 # no LLM call, no alert
    st = _state(gate_env.cfg)
    assert st["open_trade"] == _trade()             # untouched
    assert st["consecutive_check_failures"] == 0    # conclusive check resets it


def test_tp_hit_emits_win_and_proceeds(gate_env):
    _seed_state(gate_env.cfg, _trade())
    gate_env.provider.bars = [_bar("2026-07-09 07:00", 1.0999, 1.0820),  # pre-open, ignored
                              _bar("2026-07-09 09:00", 1.0900, 1.0820),
                              _bar("2026-07-09 10:00", 1.0960, 1.0840)]  # tp 1.0950 hit
    assert gate_env.run() == 0
    assert gate_env.inner_ran()
    st = _state(gate_env.cfg)
    assert st["open_trade"] is None
    (outcome,) = _outcomes(gate_env.cfg)
    assert outcome["outcome"] == "WIN"
    assert outcome["r"] == pytest.approx(2.0)       # 0.0100 reward / 0.0050 risk
    assert outcome["resolved_at"] == "2026-07-09 10:00"
    assert outcome["bars_held"] == 2


def test_sl_hit_short_emits_loss(gate_env):
    _seed_state(gate_env.cfg, _trade(direction="SHORT", entry=1.0850,
                                     sl=1.0900, tp=1.0750))
    gate_env.provider.bars = [_bar("2026-07-09 08:00", 1.0870, 1.0830),  # open bar (skipped)
                              _bar("2026-07-09 09:00", 1.0910, 1.0840)]  # high >= sl
    assert gate_env.run() == 0
    (outcome,) = _outcomes(gate_env.cfg)
    assert outcome["outcome"] == "LOSS" and outcome["r"] == -1.0


@pytest.mark.parametrize("policy,expected", [("loss", "LOSS"), ("win", "WIN")])
def test_ambiguous_bar_policy(gate_env, policy, expected):
    gate_env.cfg["open_trade_gate"]["ambiguous_bar"] = policy
    _seed_state(gate_env.cfg, _trade())
    # One bar spans BOTH sl and tp — order unknowable from OHLC.
    gate_env.provider.bars = [_bar("2026-07-09 08:00", 1.0870, 1.0830),  # open bar (skipped)
                              _bar("2026-07-09 09:00", 1.0999, 1.0700)]
    assert gate_env.run() == 0
    (outcome,) = _outcomes(gate_env.cfg)
    assert outcome["outcome"] == expected


def test_fetch_error_fails_closed_and_counts(gate_env):
    _seed_state(gate_env.cfg, _trade())
    gate_env.provider.exc = RuntimeError("MT5 gone")
    assert gate_env.run() == 0
    assert not gate_env.inner_ran()
    st = _state(gate_env.cfg)
    assert st["open_trade"] == _trade()
    assert st["consecutive_check_failures"] == 1


def test_short_window_fails_closed(gate_env):
    _seed_state(gate_env.cfg, _trade())
    # Oldest fetched bar is AFTER the open — a hit may hide in the gap.
    gate_env.provider.bars = [_bar("2026-07-09 10:00", 1.0999, 1.0700)]
    assert gate_env.run() == 0
    assert not gate_env.inner_ran()
    assert _state(gate_env.cfg)["consecutive_check_failures"] == 1


def test_warning_alert_after_consecutive_failures(gate_env, monkeypatch):
    sent = []

    class FakeSink:
        def send(self, text):
            sent.append(text)

    monkeypatch.setattr(trade_gate, "build_alert_sinks", lambda cfg: [FakeSink()])
    _seed_state(gate_env.cfg, _trade(), failures=2)     # this failure is the 3rd
    gate_env.provider.exc = RuntimeError("down")
    assert gate_env.run() == 0
    assert _state(gate_env.cfg)["consecutive_check_failures"] == 3
    assert len(sent) == 1 and NAME in sent[0]
    # A 4th failure must NOT re-warn (fires once, at the threshold).
    assert gate_env.run() == 0
    assert len(sent) == 1


def test_expires_after_max_open_bars(gate_env):
    _seed_state(gate_env.cfg, _trade(opened_at="2025-01-01 00:00"))  # ~13k bars ago
    assert gate_env.run() == 0
    assert gate_env.inner_ran()                      # schedule resumes
    assert gate_env.provider.calls == []             # expired before any fetch
    st = _state(gate_env.cfg)
    assert st["open_trade"] is None
    (outcome,) = _outcomes(gate_env.cfg)
    assert outcome["outcome"] == "EXPIRED" and outcome["r"] == 0.0


# ---- run: locking -----------------------------------------------------------

def test_fresh_lock_skips_without_fetching(gate_env):
    _seed_state(gate_env.cfg, _trade())
    assert trade_gate.acquire_lock(gate_env.cfg["data_dir"], NAME, 1800)
    assert gate_env.run() == 0
    assert not gate_env.inner_ran()
    assert gate_env.provider.calls == []


def test_stale_lock_is_reclaimed(gate_env):
    data_dir = gate_env.cfg["data_dir"]
    assert trade_gate.acquire_lock(data_dir, NAME, 1800)
    old = trade_gate._lock_path(data_dir, NAME)
    os.utime(old, (0, 0))                            # epoch mtime → very stale
    assert gate_env.run() == 0
    assert gate_env.inner_ran()
    assert not os.path.exists(old)                   # released after the fire


def test_inner_failure_still_records_and_releases_lock(gate_env):
    _write_verdicts(gate_env.cfg, _verdict())        # pre-existing, must be ignored
    _seed_state(gate_env.cfg, None, checkpoint=1)
    rc = gate_env.run(inner=[sys.executable, "-c", "import sys; sys.exit(7)"])
    assert rc == 7                                   # honest cron log
    st = _state(gate_env.cfg)
    assert st["verdicts_checkpoint"] == 1 and st["open_trade"] is None
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


# ---- record phase -----------------------------------------------------------

def _run_with_verdict(gate_env, verdict, **runkw):
    """Inner command = append `verdict` to verdicts.jsonl, like a real fire."""
    path = os.path.join(gate_env.cfg["data_dir"], "verdicts.jsonl")
    code = ("import json,pathlib; p=pathlib.Path(r'%s'); "
            "f=p.open('a'); f.write(json.dumps(%r)+'\\n'); f.close()"
            % (pathlib_posix(path), verdict))
    return gate_env.run(inner=[sys.executable, "-c", code], **runkw)


def pathlib_posix(p):
    return p.replace("\\", "/")


def test_record_arms_gate_from_fresh_verdict(gate_env):
    assert _run_with_verdict(gate_env, _verdict()) == 0
    trade = _state(gate_env.cfg)["open_trade"]
    assert trade["direction"] == "LONG"
    assert trade["sl"] == 1.0800 and trade["tp"] == 1.0950   # stop/target mapped
    assert trade["opened_at"] == "2026-07-09 11:00"
    assert trade["platform"] == "mt5"


def test_record_ignores_other_timeframe(gate_env):
    # Same symbol, 4h verdict — the 1h schedule must NOT adopt it (the
    # chairman.py timeframe stamp is what makes this distinguishable).
    assert _run_with_verdict(gate_env, _verdict(timeframe="4h")) == 0
    assert _state(gate_env.cfg)["open_trade"] is None


def test_record_matches_exchange_prefixed_symbol(gate_env):
    v = _verdict(symbol="NASDAQ:AAPL", timeframe="1D", platform="tradingview")
    assert _run_with_verdict(gate_env, v, name="AAPL_1D", symbol="AAPL",
                             tf="1D") == 0
    trade = _state(gate_env.cfg, "AAPL_1D")["open_trade"]
    assert trade["symbol"] == "NASDAQ:AAPL"          # native kept for fetching


def test_record_matches_broker_suffixed_symbol(gate_env):
    gate_env.cfg["platforms"]["mt5"]["symbol_suffix"] = "zero"
    assert _run_with_verdict(gate_env, _verdict(symbol="EURUSDzero")) == 0
    assert _state(gate_env.cfg)["open_trade"]["symbol"] == "EURUSDzero"


def test_record_ignores_pre_checkpoint_verdict(gate_env):
    _write_verdicts(gate_env.cfg, _verdict())        # stale line before the fire
    assert gate_env.run() == 0                       # inner emits nothing
    st = _state(gate_env.cfg)
    assert st["open_trade"] is None
    assert st["verdicts_checkpoint"] == 1


def test_record_no_trade_advances_checkpoint_only(gate_env):
    v = _verdict(decision="NO_TRADE")
    v.pop("entry"), v.pop("stop"), v.pop("target")
    assert _run_with_verdict(gate_env, v) == 0
    st = _state(gate_env.cfg)
    assert st["open_trade"] is None
    assert st["verdicts_checkpoint"] == 1


# ---- status / clear ---------------------------------------------------------

def test_clear_drops_trade_and_lock(gate_env, capsys):
    _seed_state(gate_env.cfg, _trade())
    trade_gate.acquire_lock(gate_env.cfg["data_dir"], NAME, 1800)
    assert trade_gate._main(["clear", NAME]) == 0
    assert _state(gate_env.cfg)["open_trade"] is None
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


def test_status_reports_open_trade(gate_env, capsys):
    _seed_state(gate_env.cfg, _trade())
    assert trade_gate._main(["status", NAME]) == 0
    out = capsys.readouterr().out
    assert "OPEN LONG" in out and "EURUSD" in out and "2026-07-09 08:00" in out


# ---- check / record (Hermes two-process flow) -------------------------------

def _check(name=NAME, symbol="EURUSD", tf="1h"):
    return trade_gate._main(["check", name, symbol, tf])


def _record(name=NAME, symbol="EURUSD", tf="1h"):
    return trade_gate._main(["record", name, symbol, tf])


def test_check_proceeds_and_stamps_checkpoint(gate_env, capsys):
    _write_verdicts(gate_env.cfg, {"old": 1}, {"old": 2})   # two pre-existing lines
    assert _check() == 0
    out = capsys.readouterr().out
    assert "PROCEED" in out and "SKIP" not in out
    st = _state(gate_env.cfg)
    assert st["verdicts_checkpoint"] == 2                    # stamped to EOF
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


def test_check_skips_while_open_and_leaves_no_lock(gate_env, capsys):
    _seed_state(gate_env.cfg, _trade(), checkpoint=5)
    gate_env.provider.bars = [_bar("2026-07-09 09:00", 1.0900, 1.0820),
                              _bar("2026-07-09 10:00", 1.0910, 1.0840)]  # no sl/tp
    assert _check() == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "PROCEED" not in out
    st = _state(gate_env.cfg)
    assert st["open_trade"] == _trade()                     # still tracked
    assert st["verdicts_checkpoint"] == 5                   # NOT re-stamped on skip
    # Non-held lock: released even though we skipped (no wedge on next fire).
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


def test_check_resolve_prints_outcome_and_proceeds(gate_env, capsys):
    _seed_state(gate_env.cfg, _trade())
    gate_env.provider.bars = [_bar("2026-07-09 07:00", 1.0860, 1.0840),  # pre-open, reaches back
                              _bar("2026-07-09 09:00", 1.0900, 1.0820),
                              _bar("2026-07-09 10:00", 1.0960, 1.0840)]  # tp hit
    assert _check() == 0
    out = capsys.readouterr().out
    assert "OUTCOME" in out and "PROCEED" in out
    # The OUTCOME line carries a relayable WIN payload for the Hermes channel.
    payload = json.loads(out.split("OUTCOME", 1)[1].splitlines()[0])
    assert payload["outcome"] == "WIN"
    assert _state(gate_env.cfg)["open_trade"] is None
    (outcome,) = _outcomes(gate_env.cfg)                    # also persisted locally
    assert outcome["outcome"] == "WIN"


def test_check_skips_when_another_fire_holds_lock(gate_env, capsys):
    _seed_state(gate_env.cfg, _trade())
    assert trade_gate.acquire_lock(gate_env.cfg["data_dir"], NAME, 1800)
    assert _check() == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "in flight" in out
    assert gate_env.provider.calls == []                    # never even checked


def test_check_disabled_proceeds(gate_env, capsys):
    gate_env.cfg["open_trade_gate"]["enabled"] = False
    _seed_state(gate_env.cfg, _trade())                     # would normally skip
    assert _check() == 0
    assert "PROCEED" in capsys.readouterr().out


def test_record_arms_from_verdict_after_checkpoint(gate_env, capsys):
    _write_verdicts(gate_env.cfg, {"old": 1})               # pre-fire line, ignored
    _seed_state(gate_env.cfg, None, checkpoint=1)           # as `check` would stamp
    _write_verdicts(gate_env.cfg, _verdict())               # the fire's verdict
    assert _record() == 0
    trade = _state(gate_env.cfg)["open_trade"]
    assert trade["direction"] == "LONG" and trade["tp"] == 1.0950
    assert not os.path.exists(trade_gate._lock_path(gate_env.cfg["data_dir"], NAME))


def test_check_then_record_round_trip(gate_env, capsys):
    """The full Hermes sequence: check (proceed) → convene writes a verdict →
    record (arms) → next check (skips while open)."""
    assert _check() == 0                                    # nothing open → proceed
    assert "PROCEED" in capsys.readouterr().out
    _write_verdicts(gate_env.cfg, _verdict())              # the convene's verdict
    assert _record() == 0
    assert _state(gate_env.cfg)["open_trade"]["direction"] == "LONG"
    # A following fire must now skip while that trade is open.
    gate_env.provider.bars = [_bar("2026-07-09 10:00", 1.0900, 1.0820)]
    assert _check() == 0
    assert "SKIP" in capsys.readouterr().out


def test_record_no_verdict_tracks_nothing(gate_env, capsys):
    _seed_state(gate_env.cfg, None, checkpoint=0)
    assert _record() == 0
    assert "no new trade" in capsys.readouterr().out
    assert _state(gate_env.cfg)["open_trade"] is None
