"""Regression tests for the audit/code-review fixes.

Each test pins a bug the review found so it can't silently come back. Pure
Python: no MT5 / LLM / network.
"""

import copy
import json
import shlex

import pytest

from tlc import config as cfg_mod
from tlc import cron
from tlc.chairman import aggregate
from tlc.council import write_council, _print_council, load_council
from tlc.market_packet import atr, build_packet
from tlc.orchestrator import extract_ballot_json, OrchestratorError
from tlc.providers.rate_limit import RateLimiter, RateLimitError
from tlc.scoring.score import to_signal_rows
from tlc.sinks.telegram import format_verdict


# ---- #1 cron shell injection -------------------------------------------------

def test_build_command_quotes_shell_metacharacters():
    # The payload must survive as a single literal token, never as live shell.
    evil = 'EURUSD"; touch /tmp/pwned #'
    cmd = cron.build_command(evil, "1h", cron.parse_interval("1h"),
                             engine="agent", repo_dir="/repo")
    toks = shlex.split(cmd)
    assert "touch" not in toks                       # no standalone injected command
    assert any("touch /tmp/pwned" in t for t in toks)  # it's inside one quoted token

    api = cron.build_command("BTC; rm -rf ~", "1h", cron.parse_interval("1h"),
                             engine="api", council="a; b")
    api_toks = shlex.split(api)
    assert "rm" not in api_toks and "BTC; rm -rf ~" in api_toks


def test_build_command_benign_unchanged():
    # The common case still reads cleanly (and keeps the existing tests' shape).
    cmd = cron.build_command("EURUSD", "1h", cron.parse_interval("1h"),
                             engine="agent", platform="tv", repo_dir="/repo")
    assert "convene EURUSD 1h tv" in cmd and cmd.startswith("cd /repo &&")


# ---- #2 rate limiter cap<=0 edge --------------------------------------------

class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_rate_limiter_zero_cap_raises_cleanly(tmp_path):
    rl = RateLimiter(path=str(tmp_path / "rl.json"),
                     limits={"per_minute": 0, "per_hour": 100, "per_day": 100},
                     now_fn=_Clock())
    with pytest.raises(RateLimitError):   # not ValueError from min([])
        rl.check_and_record()


def test_rate_limiter_save_is_atomic(tmp_path):
    p = tmp_path / "rl.json"
    rl = RateLimiter(path=str(p), now_fn=_Clock())
    rl.record()
    assert json.loads(p.read_text())["calls"]            # valid JSON, not truncated
    assert not list(tmp_path.glob("*.tmp"))              # temp file cleaned up


# ---- #3 atr / packet bad-bar guard ------------------------------------------

def test_atr_skips_bars_missing_ohlc():
    bars = [{"time": "t", "open": 1, "high": None, "low": 1, "close": 1, "volume": 0},
            {"time": "t0", "open": 1, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 0}]
    assert atr(bars) is None        # the one usable pair has a None — skipped, no crash


def test_build_packet_rejects_nonfinite_price():
    bad = [{"time": "t", "open": 1, "high": 2, "low": 1, "close": float("nan"), "volume": 1},
           {"time": "t0", "open": 1, "high": 2, "low": 1, "close": 1.0, "volume": 1}]
    with pytest.raises(ValueError):
        build_packet("X", "1h", {"1h": bad})


# ---- #4 chairman tie roll-call + zero-risk ----------------------------------

def _long(legend, conv=0.8, e=1.0840, inv=1.0790, t=1.0960):
    return {"legend": legend, "symbol": "EURUSD", "timeframe": "1h", "direction": "LONG",
            "conviction": conv, "entry": e, "invalidation": inv, "target": t}


def _short(legend, conv=0.8, e=1.0840, inv=1.0900, t=1.0720):
    return {"legend": legend, "symbol": "EURUSD", "timeframe": "1h", "direction": "SHORT",
            "conviction": conv, "entry": e, "invalidation": inv, "target": t}


def test_tie_keeps_directional_rollcall():
    v = aggregate([_long("gann"), _short("dow")])
    assert v["decision"] == "NO_TRADE"
    assert v["for"] == ["gann"] and v["against"] == ["dow"]   # voters not lost


def test_all_flat_has_empty_rollcall():
    flat = {"legend": "gann", "symbol": "EURUSD", "timeframe": "1h",
            "direction": "FLAT", "conviction": 0.0}
    v = aggregate([flat])
    assert v["decision"] == "NO_TRADE"
    assert v["for"] == [] and v["against"] == [] and v["abstain"] == ["gann"]


# ---- #9 ballot extraction robustness ----------------------------------------

def test_extract_ballot_ignores_prose_brace():
    text = 'Per my rule {see note}, my ballot is {"legend":"gann","direction":"FLAT"}'
    assert extract_ballot_json(text)["legend"] == "gann"


def test_extract_ballot_nested_object():
    text = '{"legend":"x","meta":{"k":1},"direction":"FLAT"}'
    assert extract_ballot_json(text)["meta"]["k"] == 1


# ---- #10 telegram numeric coercion ------------------------------------------

def test_format_verdict_tolerates_string_consensus():
    # notify reads arbitrary verdict files; a string field must not crash render.
    msg = format_verdict({"decision": "LONG", "symbol": "X", "consensus": "0.7",
                          "entry": 1.1, "stop": 1.0, "target": 1.3, "size_fraction": "0.5"})
    assert "LONG" in msg and "70%" in msg


# ---- #8 config deepcopy -----------------------------------------------------

def test_load_config_does_not_share_defaults():
    snapshot = copy.deepcopy(cfg_mod.DEFAULTS)
    c = cfg_mod.load_config("nonexistent.yaml", "nonexistent.env")
    c["routing"]["forex"] = "MUTATED"
    c["models"]["cheap"] = "MUTATED"
    assert cfg_mod.DEFAULTS == snapshot          # module defaults untouched


# ---- #7 council overwrite + scoring re-validate -----------------------------

def test_write_council_refuses_overwrite(tmp_path):
    write_council("scalp", ["wyckoff"], councils_dir=str(tmp_path))
    with pytest.raises(FileExistsError):
        write_council("scalp", ["gann"], councils_dir=str(tmp_path))
    # but --force-style overwrite works
    write_council("scalp", ["gann"], councils_dir=str(tmp_path), overwrite=True)
    assert load_council("scalp", councils_dir=str(tmp_path))["members"] == ["gann"]


def test_scoring_skips_invalid_ballot():
    good = _long("gann")
    good["created_at"] = "2026-06-26 14:00"
    bad = {"legend": "dow", "symbol": "EURUSD", "timeframe": "1h",
           "direction": "LONG", "conviction": 0.8}   # directional but no levels
    rows = to_signal_rows([good, bad])               # must not KeyError
    assert len(rows) == 1 and rows[0]["sl"] == 1.0790
