"""Tests for Phase A4: scheduling, rate limiter, alerts, calculator (PRD §2.13–2.17).

Pure-Python: no cron installed, no network, no LLM. The crontab/Telegram/LLM
transports are exercised via injected clocks and monkeypatched urlopen.
"""

import json

import pytest

from tlc import cron, vps_calc
from tlc.providers.rate_limit import RateLimiter, RateLimitError
from tlc.sinks.telegram import TelegramSink, format_verdict, TelegramError
from tlc.orchestrator import extract_ballot_json, OrchestratorError
from tlc import notify


# ---- interval parsing & cron expressions --------------------------------

@pytest.mark.parametrize("spec,n,unit,seconds", [
    ("15m", 15, "m", 900),
    ("1h", 1, "h", 3600),
    ("2h", 2, "h", 7200),
    ("3d", 3, "d", 259200),
    (" 30M ", 30, "m", 1800),
])
def test_parse_interval(spec, n, unit, seconds):
    iv = cron.parse_interval(spec)
    assert (iv.n, iv.unit, iv.seconds) == (n, unit, seconds)


@pytest.mark.parametrize("bad", ["", "h", "0m", "5x", "90m", "25h", "40d", "abc"])
def test_parse_interval_rejects(bad):
    with pytest.raises(ValueError):
        cron.parse_interval(bad)


@pytest.mark.parametrize("spec,expr", [
    ("15m", "*/15 * * * *"),
    ("1h", "0 */1 * * *"),
    ("2h", "0 */2 * * *"),
    ("3d", "0 0 */3 * *"),
])
def test_to_cron_expr(spec, expr):
    assert cron.to_cron_expr(cron.parse_interval(spec)) == expr


def test_fires_per_day():
    assert cron.fires_per_day(cron.parse_interval("1h")) == 24
    assert cron.fires_per_day(cron.parse_interval("15m")) == 96
    assert cron.fires_per_day(cron.parse_interval("1d")) == 1


# ---- command building ----------------------------------------------------

def test_build_command_agent():
    cmd = cron.build_command("EURUSD", "1h", cron.parse_interval("1h"),
                             engine="agent", platform="tv", repo_dir="/repo",
                             agent_cmd="claude -p")
    assert "claude -p" in cmd
    assert "convene EURUSD 1h tv" in cmd
    assert "telegram" in cmd
    assert cmd.startswith("cd /repo &&")


def test_build_command_api_with_council():
    cmd = cron.build_command("BTCUSD", "15m", cron.parse_interval("15m"),
                             engine="api", platform="tv", council="orderflow",
                             repo_dir="/repo")
    assert "python3 -m tlc.orchestrator BTCUSD 15m" in cmd
    assert "--platform tv" in cmd
    assert "--council orderflow" in cmd
    assert "--alert" in cmd


def test_make_name():
    assert cron.make_name("EUR/USD", "1h") == "EUR_USD_1h"
    assert cron.make_name("NASDAQ:AAPL", "1D") == "NASDAQ_AAPL_1D"


def test_schtasks_command():
    s = cron.schtasks_command("EURUSD_1h", cron.parse_interval("2h"), "do thing")
    assert '/tn "TLC_EURUSD_1h"' in s and "/sc hourly /mo 2" in s


# ---- registry roundtrip --------------------------------------------------

def test_registry_roundtrip(tmp_path):
    d = str(tmp_path)
    cron.upsert_registry({"name": "a", "symbol": "EURUSD"}, data_dir=d)
    cron.upsert_registry({"name": "b", "symbol": "BTCUSD"}, data_dir=d)
    cron.upsert_registry({"name": "a", "symbol": "EURUSD", "interval": "2h"}, data_dir=d)  # update
    entries = cron.load_registry(d)
    assert {e["name"] for e in entries} == {"a", "b"}
    assert next(e for e in entries if e["name"] == "a")["interval"] == "2h"
    cron.remove_from_registry("a", data_dir=d)
    assert {e["name"] for e in cron.load_registry(d)} == {"b"}


def test_strip_block_removes_marker_and_command():
    table = (
        "# unrelated\n"
        "0 0 * * * other\n"
        f"{cron.MARKER}:EURUSD_1h\n"
        "0 */1 * * * cd /repo && claude -p \"...\"\n"
    )
    out = cron._strip_block(table, "EURUSD_1h")
    assert "EURUSD_1h" not in out
    assert "claude -p" not in out
    assert "other" in out               # unrelated lines survive


# ---- rate limiter --------------------------------------------------------

class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_rate_limiter_blocks_at_minute_cap(tmp_path):
    clk = _Clock()
    rl = RateLimiter(path=str(tmp_path / "rl.json"),
                     limits={"per_minute": 2, "per_hour": 100, "per_day": 1000},
                     now_fn=clk)
    rl.check_and_record()
    rl.check_and_record()
    with pytest.raises(RateLimitError):
        rl.check()
    # after the minute window passes, it frees up
    clk.t += 61
    rl.check()  # no raise


def test_rate_limiter_day_window(tmp_path):
    clk = _Clock()
    rl = RateLimiter(path=str(tmp_path / "rl.json"),
                     limits={"per_minute": 100, "per_hour": 100, "per_day": 3},
                     now_fn=clk)
    for _ in range(3):
        rl.check_and_record()
        clk.t += 120                     # spread across minutes, still same day
    with pytest.raises(RateLimitError):
        rl.check()
    assert rl.counts()["day"] == 3


def test_rate_limiter_persists_across_instances(tmp_path):
    p = str(tmp_path / "rl.json")
    clk = _Clock()
    RateLimiter(p, limits={"per_minute": 5, "per_hour": 5, "per_day": 5}, now_fn=clk).record()
    rl2 = RateLimiter(p, limits={"per_minute": 5, "per_hour": 5, "per_day": 5}, now_fn=clk)
    assert rl2.counts()["minute"] == 1


# ---- telegram sink -------------------------------------------------------

def test_format_verdict_long():
    msg = format_verdict({
        "decision": "LONG", "symbol": "EURUSD", "platform": "mt5", "consensus": 0.83,
        "entry": 1.1, "stop": 1.09, "target": 1.13, "rr": 2.0,
        "for": ["wyckoff", "dow"], "against": ["demark"],
    })
    assert "LONG" in msg and "EURUSD" in msg and "83%" in msg
    assert "wyckoff" in msg and "demark" in msg


def test_format_verdict_no_trade():
    msg = format_verdict({"decision": "NO_TRADE", "symbol": "EURUSD",
                          "rationale": "split"})
    assert "NO TRADE" in msg


def test_telegram_quiet_no_trade_suppresses(monkeypatch):
    sent = []
    sink = TelegramSink(token="t", chat_id="c", quiet_no_trade=True)
    monkeypatch.setattr(sink, "send", lambda text: sent.append(text))
    sink.emit_verdict({"decision": "NO_TRADE", "symbol": "X"})
    assert sent == []
    sink.emit_verdict({"decision": "LONG", "symbol": "X", "consensus": 0.7})
    assert len(sent) == 1


def test_telegram_send_builds_payload(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"ok": True, "result": {}}).encode()

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("tlc.sinks.telegram.urllib.request.urlopen", fake_urlopen)
    TelegramSink(token="TOK", chat_id="42").send("hello")
    assert "botTOK/sendMessage" in captured["url"]
    assert captured["body"]["chat_id"] == "42"
    assert captured["body"]["text"] == "hello"


def test_telegram_send_requires_credentials():
    with pytest.raises(TelegramError):
        TelegramSink(token="", chat_id="").send("x")


# ---- notify routing ------------------------------------------------------

def test_notify_routes_to_enabled(monkeypatch):
    fired = []

    class FakeTelegram:
        name = "telegram"

        def __init__(self, *a, **k): pass

        def emit_verdict(self, verdict): fired.append(verdict["symbol"])

    monkeypatch.setattr("tlc.notify.TelegramSink", FakeTelegram)
    cfg = {"alerts": {"enabled": ["telegram"], "telegram": {"quiet_no_trade": False}}}
    result = notify.notify_verdict({"symbol": "EURUSD", "decision": "LONG"}, cfg)
    assert fired == ["EURUSD"] and result == ["telegram"]


def test_notify_none_enabled():
    assert notify.notify_verdict({"symbol": "X"}, {"alerts": {"enabled": []}}) == []


# ---- orchestrator ballot extraction -------------------------------------

def test_extract_ballot_fenced():
    text = 'Here is my vote:\n```json\n{"legend": "gann", "direction": "FLAT"}\n```\n'
    assert extract_ballot_json(text)["legend"] == "gann"


def test_extract_ballot_bare():
    assert extract_ballot_json('{"direction": "LONG", "entry": 1.1}')["direction"] == "LONG"


def test_extract_ballot_with_prose():
    text = 'I think LONG. {"direction": "LONG", "conviction": 0.7} — final.'
    assert extract_ballot_json(text)["conviction"] == 0.7


def test_extract_ballot_bad():
    with pytest.raises(OrchestratorError):
        extract_ballot_json("no json here")


# ---- vps calculator ------------------------------------------------------

def test_interserver_slice_model():
    assert vps_calc.interserver_slice(1) == {
        "slices": 1, "cores": 1, "ram_gb": 2, "ssd_gb": 40, "transfer_tb": 2, "price_usd": 3}
    s32 = vps_calc.interserver_slice(32)
    assert (s32["cores"], s32["ram_gb"], s32["price_usd"]) == (16, 64, 96)
    # cores = ceil(slices/2), matches interserver-slices.md
    assert vps_calc.interserver_slice(3)["cores"] == 2
    assert vps_calc.interserver_slice(8)["cores"] == 4


def test_smallest_slice_for():
    assert vps_calc.smallest_slice_for(1.0, 1)["slices"] == 1
    assert vps_calc.smallest_slice_for(5.0, 1)["slices"] == 3      # needs 6GB
    assert vps_calc.smallest_slice_for(2.0, 2)["slices"] == 3      # needs 2 cores


def test_feed_budget_ok_and_over():
    one = vps_calc.feed_budget(1, cron.parse_interval("1h"), "tv")
    assert one["ok"] and one["per_day"] == 96          # 1 × 24 × 4 frames
    heavy = vps_calc.feed_budget(20, cron.parse_interval("1m"), "tv")
    assert not heavy["ok"] and heavy["warnings"]
    assert vps_calc.feed_budget(5, cron.parse_interval("1h"), "mt5") is None


def test_llm_cost_scales():
    a = vps_calc.llm_cost(1, cron.parse_interval("1h"), 10)
    b = vps_calc.llm_cost(2, cron.parse_interval("1h"), 10)
    assert b["usd_per_month"] > a["usd_per_month"] > 0


def test_estimate_tv_recommends_interserver():
    e = vps_calc.estimate(jobs=3, interval="1h", engine="api", platform="tv")
    assert e["deploy"]["lane"] == "interserver"
    assert "interserver.net" in e["deploy"]["link"]
    assert e["feed_budget"]["ok"]
    assert "interserver" in vps_calc.format_report(e).lower()


def test_estimate_mt5_recommends_windows():
    e = vps_calc.estimate(jobs=1, interval="1h", engine="agent", platform="mt5")
    assert e["deploy"]["lane"] == "windows"
    assert "offbeatforex.com" in e["deploy"]["link"]
    assert e["feed_budget"] is None
