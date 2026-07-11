"""Sequential open-trade gate for scheduled fires (PRD §2.13, lever #7 §2.19).

A cron fire wrapped by `run` behaves like MBT's sequential backtest — one open
position per schedule. Before convening, the gate resolves the schedule's last
alerted trade against fresh bars (the exact SL/TP walk of
`MBT/core/backtest.py::_simulate_one`):

  - still open   → skip the fire entirely (no LLM call, no alert),
  - hit SL/TP    → emit a WIN/LOSS outcome (data/outcomes.jsonl + Telegram),
                   then run the fire normally,
  - none tracked → run the fire normally.

After the inner command runs, any new LONG/SHORT verdict this fire appended to
data/verdicts.jsonl becomes the next tracked trade. State lives in
data/schedule_state/<name>.json; a lock file serializes overlapping fires of
the same schedule. On-demand /convene is never gated — only the command
`tlc/cron.py::build_command()` installs.

The whole check→inner→record span runs inside ONE process (not shell-composed
with `&&`/`;`) so the lock is released by try/finally, a skipped fire exits 0
(no cron MAILTO noise), and the generated crontab/schtasks line stays a flat
token string that both /bin/sh and cmd.exe parse.

For Hermes-scheduled convenings the fire is a raw LLM prompt, not a shell
command, so `run` can't wrap it. Instead the convene skill calls two phases
around its own convene — `check` (skip / proceed, relaying any resolved outcome)
then `record` (arm the next trade) — sharing the exact same state files.

CLI:
    python3 -m tlc.trade_gate run <name> <symbol> <tf> [--platform tv|mt5] -- <inner…>
    python3 -m tlc.trade_gate check  <name> <symbol> <tf> [--platform tv|mt5]
    python3 -m tlc.trade_gate record <name> <symbol> <tf> [--platform tv|mt5]
    python3 -m tlc.trade_gate status <name>
    python3 -m tlc.trade_gate clear <name>
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import time
from typing import List, Optional, Tuple

from .config import load_config
from .cron import timeframe_seconds
from .notify import build_alert_sinks, notify_outcome
from .providers import get_provider
from .providers.routing import resolve_platform
from .sinks import LocalJsonSink

STATE_DIR = "schedule_state"
_BARTIME_FMT = "%Y-%m-%d %H:%M"   # every provider path renders bar time this way


def _utcnow() -> datetime.datetime:
    """Naive UTC now — bar times are naive strings (UTC, or broker time on the
    local MT5 path; the fetch buffer absorbs that offset). Monkeypatched in tests."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _parse_bartime(value: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.strptime(str(value), _BARTIME_FMT)
    except (TypeError, ValueError):
        return None


# --- state & lock files -----------------------------------------------------

def _state_path(data_dir: str, name: str) -> str:
    return os.path.join(data_dir, STATE_DIR, f"{name}.json")


def _lock_path(data_dir: str, name: str) -> str:
    return os.path.join(data_dir, STATE_DIR, f"{name}.lock")


def load_state(data_dir: str, name: str) -> dict:
    path = _state_path(data_dir, name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            print(f"[trade_gate] {name}: unreadable state file, starting fresh",
                  file=sys.stderr)
    return {"verdicts_checkpoint": 0, "open_trade": None,
            "consecutive_check_failures": 0}


def save_state(data_dir: str, name: str, state: dict) -> None:
    path = _state_path(data_dir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def _ensure_started(state: dict) -> str:
    """Stamp (once) when this schedule began tracking, so tlc.pnl can scope the
    'since cron start' running-stats window. Returns the started_at string."""
    started = state.get("started_at")
    if not started:
        started = _utcnow().strftime(_BARTIME_FMT)
        state["started_at"] = started
    return started


def acquire_lock(data_dir: str, name: str, stale_seconds: int) -> bool:
    """Atomically create the lock. False = a fresh lock exists (fire in flight).
    A stale lock (older than stale_seconds — crashed fire, reboot) is reclaimed."""
    path = _lock_path(data_dir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in (1, 2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as fh:
                json.dump({"pid": os.getpid(), "started_at": time.time()}, fh)
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(path)
            except OSError:
                age = float(stale_seconds) + 1  # vanished between checks — retry
            if attempt == 2 or age <= stale_seconds:
                return False
            print(f"[trade_gate] {name}: reclaiming stale lock ({int(age)}s old)",
                  file=sys.stderr)
            try:
                os.remove(path)
            except OSError:
                return False
    return False


def release_lock(data_dir: str, name: str) -> None:
    try:
        os.remove(_lock_path(data_dir, name))
    except OSError:
        pass


# --- symbol matching ---------------------------------------------------------

def _norm_symbol(symbol: str, config: dict) -> str:
    """Comparable form of a symbol across platforms: strip a TV exchange prefix
    (NASDAQ:AAPL → AAPL) and the configured MT5 broker suffix (EURUSDzero →
    EURUSD), upper-case. Deliberately NOT provider.resolve_symbol(): that needs
    an exchange_map hit for TV stocks and would silently never match."""
    s = str(symbol).split(":")[-1].strip().upper()
    suffix = (((config.get("platforms") or {}).get("mt5") or {})
              .get("symbol_suffix") or "").upper()
    if suffix and s.endswith(suffix) and len(s) > len(suffix):
        s = s[: -len(suffix)]
    return s


# --- check phase: resolve the tracked trade against fresh bars ---------------

def resolve_against_bars(trade: dict, bars: List[dict],
                         ambiguous: str) -> Optional[Tuple[str, str, int]]:
    """Walk bars oldest→newest from after the open; (outcome, exit_time,
    bars_held) or None if neither SL nor TP was touched. Mirrors
    MBT/core/backtest.py::_simulate_one exactly (incl. ambiguous-bar policy).

    Public: the backtest gate (`backtest/gate.py`) reuses this so a backtested
    trade resolves on the identical SL/TP walk as a live scheduled trade."""
    is_long = trade["direction"] == "LONG"
    sl, tp = float(trade["sl"]), float(trade["tp"])
    opened_at = str(trade.get("opened_at", ""))
    held = 0
    for b in bars:
        if str(b["time"]) <= opened_at:
            continue
        held += 1
        if is_long:
            hit_sl = b["low"] <= sl
            hit_tp = b["high"] >= tp
        else:
            hit_sl = b["high"] >= sl
            hit_tp = b["low"] <= tp
        if hit_sl and hit_tp:
            return ("WIN" if ambiguous == "win" else "LOSS", str(b["time"]), held)
        if hit_sl:
            return ("LOSS", str(b["time"]), held)
        if hit_tp:
            return ("WIN", str(b["time"]), held)
    return None


def build_outcome(trade: dict, result: str, resolved_at: str,
                  bars_held: int, name: str = "", started_at: str = "") -> dict:
    """An outcomes.jsonl record for a resolved/expired trade. Public: shared by
    the live gate and the backtest gate so both emit the same outcome shape.

    `name` (schedule) and `started_at` (when the schedule began tracking) let
    tlc.pnl scope running stats to one schedule since it started; both default
    empty so the backtest gate can keep calling this unchanged."""
    risk = abs(float(trade["entry"]) - float(trade["sl"]))
    reward = abs(float(trade["tp"]) - float(trade["entry"]))
    rr = (reward / risk) if risk > 0 else 0.0
    r = {"WIN": round(rr, 2), "LOSS": -1.0}.get(result, 0.0)
    return {
        "name": name,
        "symbol": trade.get("symbol", ""),
        "timeframe": trade.get("timeframe", ""),
        "platform": trade.get("platform", ""),
        "direction": trade.get("direction", ""),
        "entry": trade.get("entry"),
        "sl": trade.get("sl"),
        "tp": trade.get("tp"),
        "outcome": result,
        "r": r,
        "opened_at": trade.get("opened_at", ""),
        "resolved_at": resolved_at,
        "bars_held": bars_held,
        "started_at": started_at,
    }


def _emit_outcome(outcome: dict, config: dict) -> None:
    LocalJsonSink(config.get("data_dir", "data")).emit_outcome(outcome)
    notify_outcome(outcome, config)


def _inconclusive(state: dict, config: dict, name: str, reason: str) -> bool:
    """Fail closed: can't disprove the trade is live → skip this fire. Repeated
    inconclusive checks would silently kill the schedule, so after
    warn_after_failures in a row a Telegram warning makes the wedge visible."""
    fails = int(state.get("consecutive_check_failures", 0)) + 1
    state["consecutive_check_failures"] = fails
    print(f"[trade_gate] {name}: cannot verify open trade ({reason}) — "
          f"failing closed, skipping fire ({fails} consecutive)", file=sys.stderr)
    warn_at = int((config.get("open_trade_gate") or {}).get("warn_after_failures", 3))
    if warn_at and fails == warn_at:   # once, not on every subsequent skip
        msg = (f"⚠️ TLC gate stuck on {name}: {fails} consecutive fires could not "
               f"verify the tracked trade ({reason}). Fires are being skipped — "
               f"inspect with `python3 -m tlc.trade_gate status {name}` or force "
               f"with `clear {name}`.")
        for sink in build_alert_sinks(config):
            send = getattr(sink, "send", None)
            if send is None:
                continue
            try:
                send(msg)
            except Exception as exc:  # noqa: BLE001 — warning is best-effort
                print(f"[trade_gate] warning alert failed: {exc}", file=sys.stderr)
    return False


def _check_phase(state: dict, config: dict,
                 name: str) -> Tuple[bool, Optional[dict]]:
    """(proceed, outcome). proceed=True → clear to convene; False → skip this
    fire. `outcome` is the WIN/LOSS/EXPIRED record emitted this call (so callers
    that deliver through their own channel — the Hermes flow — can relay it), or
    None. Mutates state: outcome emitted / trade cleared / failure counter."""
    started = _ensure_started(state)
    trade = state.get("open_trade")
    if not trade:
        return True, None

    gate_cfg = config.get("open_trade_gate") or {}
    tf_s = timeframe_seconds(trade.get("timeframe", "")) or 3600
    opened_dt = _parse_bartime(trade.get("opened_at", ""))
    if opened_dt is None:
        # Un-walkable open time — expire rather than wedge the schedule forever.
        print(f"[trade_gate] {name}: tracked trade has no parseable opened_at — "
              f"expiring it", file=sys.stderr)
        outcome = build_outcome(trade, "EXPIRED", "", 0, name=name, started_at=started)
        _emit_outcome(outcome, config)
        state["open_trade"] = None
        state["consecutive_check_failures"] = 0
        return True, outcome

    elapsed_bars = max(0, int((_utcnow() - opened_dt).total_seconds() // tf_s))
    max_open = int(gate_cfg.get("max_open_bars", 1000))
    if elapsed_bars > max_open:
        # Anti-wedge: matches MBT, where forward_bars bounds resolution and an
        # OPEN trade doesn't block later signals forever.
        print(f"[trade_gate] {name}: trade unresolved after {elapsed_bars} bars "
              f"(max {max_open}) — expiring, tracking stopped")
        outcome = build_outcome(trade, "EXPIRED", "", elapsed_bars, name=name, started_at=started)
        _emit_outcome(outcome, config)
        state["open_trade"] = None
        state["consecutive_check_failures"] = 0
        return True, outcome

    # Enough bars to cover open→now, plus a generous pad: the local MT5 path
    # stamps broker-server time (MBT/core/ohlcv.py) which can sit hours off the
    # wall clock used for elapsed_bars.
    count = elapsed_bars + max(10, math.ceil(43200 / tf_s))
    try:
        provider = get_provider(trade.get("platform") or
                                config.get("default_platform", "mt5"), config)
        bars = provider.fetch(trade["symbol"], trade["timeframe"], count)
    except Exception as exc:  # noqa: BLE001 — any fetch failure fails closed
        return _inconclusive(state, config, name, f"bar fetch failed: {exc}"), None

    bars = list(reversed(bars))  # canonical newest-first → oldest-first walk
    if not bars or str(bars[0]["time"]) > str(trade.get("opened_at", "")):
        return _inconclusive(state, config, name,
                             "fetched window does not reach back to the open"), None

    hit = resolve_against_bars(trade, bars, gate_cfg.get("ambiguous_bar", "loss"))
    if hit is None:
        state["consecutive_check_failures"] = 0   # conclusive answer: still open
        print(f"[trade_gate] {name}: previous {trade.get('direction')} on "
              f"{trade.get('symbol')} still open — skipping this fire")
        return False, None

    result, exit_time, held = hit
    outcome = build_outcome(trade, result, exit_time, held, name=name, started_at=started)
    _emit_outcome(outcome, config)
    state["open_trade"] = None
    state["consecutive_check_failures"] = 0
    print(f"[trade_gate] {name}: previous trade resolved {result} "
          f"({outcome['r']:+.2f}R) — proceeding")
    return True, outcome


# --- record phase: arm the gate from the verdict this fire produced ----------

def _read_verdict_lines(data_dir: str) -> List[str]:
    path = os.path.join(data_dir, "verdicts.jsonl")
    if not os.path.exists(path):
        return []
    # errors="replace": a line written before the sink forced UTF-8 (or by any
    # foreign tool in the platform codepage) must degrade to one unparseable
    # line, not a UnicodeDecodeError that breaks record's never-raises contract.
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.readlines()


def _record_phase(state: dict, config: dict, symbol: str, timeframe: str,
                  platform_flag: str, name: str) -> None:
    """Scan verdicts appended after this fire's checkpoint; the last LONG/SHORT
    matching this schedule becomes the tracked open trade. Always advances the
    checkpoint. Never raises — recording must not fail the cron job."""
    _ensure_started(state)
    data_dir = config.get("data_dir", "data")
    lines = _read_verdict_lines(data_dir)
    checkpoint = int(state.get("verdicts_checkpoint", 0))
    want_sym = _norm_symbol(symbol, config)

    chosen: Optional[dict] = None
    for line in lines[checkpoint:]:
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(v, dict):
            continue
        if _norm_symbol(v.get("symbol", ""), config) != want_sym:
            continue
        vtf = v.get("timeframe", "")
        if vtf:
            if vtf != timeframe:
                continue
        else:  # pre-migration verdict without the field (chairman.py stamp)
            print(f"[trade_gate] {name}: verdict has no timeframe — matching on "
                  f"symbol only", file=sys.stderr)
        if v.get("decision") in ("LONG", "SHORT"):
            chosen = v

    if chosen is not None:
        opened_at = chosen.get("created_at", "")
        if not opened_at:
            print(f"[trade_gate] {name}: verdict has no created_at bar time — "
                  f"cannot track it as an open trade", file=sys.stderr)
        else:
            try:
                state["open_trade"] = {
                    "direction": chosen["decision"],
                    "entry": float(chosen["entry"]),
                    "sl": float(chosen["stop"]),
                    "tp": float(chosen["target"]),
                    "opened_at": opened_at,
                    # The verdict's own native symbol — exactly what the provider
                    # fetch in the next check needs; no re-resolution round-trip.
                    "symbol": chosen.get("symbol", symbol),
                    "timeframe": timeframe,
                    "platform": chosen.get("platform") or resolve_platform(
                        symbol, config, explicit=platform_flag or None),
                }
                print(f"[trade_gate] {name}: tracking new {chosen['decision']} on "
                      f"{state['open_trade']['symbol']} "
                      f"(entry {chosen['entry']}, sl {chosen['stop']}, "
                      f"tp {chosen['target']})")
            except (KeyError, TypeError, ValueError) as exc:
                print(f"[trade_gate] {name}: malformed verdict, not tracking: {exc}",
                      file=sys.stderr)

    state["verdicts_checkpoint"] = len(lines)


# --- CLI ----------------------------------------------------------------------

def cmd_run(args, inner: List[str]) -> int:
    config = load_config(args.config)
    gate_cfg = config.get("open_trade_gate") or {}
    if not inner:
        print("trade_gate run: no inner command after '--'", file=sys.stderr)
        return 2
    if not gate_cfg.get("enabled", True):
        # Runtime kill switch: behave exactly like an ungated schedule.
        return subprocess.run(inner).returncode

    data_dir = config.get("data_dir", "data")
    name = args.name
    if not acquire_lock(data_dir, name,
                        int(gate_cfg.get("stale_lock_seconds", 1800))):
        print(f"[trade_gate] {name}: skipped — another fire is in flight")
        return 0
    try:
        state = load_state(data_dir, name)
        proceed, _outcome = _check_phase(state, config, name)
        if not proceed:
            save_state(data_dir, name, state)
            return 0
        # Stamp before the convene so record only sees THIS fire's verdicts.
        state["verdicts_checkpoint"] = len(_read_verdict_lines(data_dir))
        save_state(data_dir, name, state)

        rc = subprocess.run(inner).returncode

        # Record even when inner failed — the checkpoint must advance and the
        # cron job must not wedge on a bad fire.
        _record_phase(state, config, args.symbol, args.timeframe,
                      args.platform, name)
        save_state(data_dir, name, state)
        return rc
    finally:
        release_lock(data_dir, name)


def cmd_check(args) -> int:
    """Hermes-flow phase 1 (PRD §2.13). `run` can't wrap a Hermes cron fire —
    that fire is a raw LLM prompt, not a shell command — so the convene skill
    calls `check` before convening and `record` after. Unlike `run`, the lock is
    NOT held across the (LLM) convene: two short-lived processes can't share a
    held OS lock cleanly, and a leaked held lock would wedge the schedule for
    stale_lock_seconds. It only guards the check→checkpoint critical section.

    Prints a decision token on its own line — `PROCEED` or `SKIP …` — that the
    skill keys off. If the tracked trade resolved this check, an `OUTCOME <json>`
    line is also printed so the agent can relay WIN/LOSS through the Hermes
    channel (Discord/Slack/…), which TLC's own Telegram sink doesn't reach."""
    config = load_config(args.config)
    gate_cfg = config.get("open_trade_gate") or {}
    data_dir = config.get("data_dir", "data")
    name = args.name
    if not gate_cfg.get("enabled", True):
        print("PROCEED (gate disabled)")
        return 0
    if not acquire_lock(data_dir, name, int(gate_cfg.get("stale_lock_seconds", 1800))):
        print("SKIP another fire is in flight")
        return 0
    try:
        state = load_state(data_dir, name)
        proceed, outcome = _check_phase(state, config, name)
        if proceed:
            # Stamp before the convene so `record` only sees THIS fire's verdicts.
            state["verdicts_checkpoint"] = len(_read_verdict_lines(data_dir))
        save_state(data_dir, name, state)
    finally:
        release_lock(data_dir, name)

    if outcome:
        print("OUTCOME " + json.dumps(outcome))
    if proceed:
        print("PROCEED")
    else:
        print("SKIP previous trade still open")
    return 0


def cmd_record(args) -> int:
    """Hermes-flow phase 2: arm the gate from the verdict the just-finished
    convene appended to data/verdicts.jsonl (scanned from the checkpoint `check`
    stamped). Idempotent-ish and never fatal — a convene that produced no
    LONG/SHORT simply arms nothing."""
    config = load_config(args.config)
    gate_cfg = config.get("open_trade_gate") or {}
    if not gate_cfg.get("enabled", True):
        print("gate disabled — nothing recorded")
        return 0
    data_dir = config.get("data_dir", "data")
    name = args.name
    got_lock = acquire_lock(data_dir, name, int(gate_cfg.get("stale_lock_seconds", 1800)))
    try:
        state = load_state(data_dir, name)
        _record_phase(state, config, args.symbol, args.timeframe, args.platform, name)
        save_state(data_dir, name, state)
    finally:
        if got_lock:
            release_lock(data_dir, name)
    trade = state.get("open_trade")
    if trade:
        print(f"armed {trade['direction']} {trade['symbol']} {trade['timeframe']} "
              f"(entry {trade['entry']}, sl {trade['sl']}, tp {trade['tp']})")
    else:
        print("no new trade to track")
    return 0


def cmd_status(args) -> int:
    config = load_config(args.config)
    data_dir = config.get("data_dir", "data")
    state = load_state(data_dir, args.name)
    trade = state.get("open_trade")
    lock = " · lock present" if os.path.exists(_lock_path(data_dir, args.name)) else ""
    if not trade:
        print(f"{args.name}: no open trade tracked{lock}")
    else:
        tf_s = timeframe_seconds(trade.get("timeframe", "")) or 3600
        opened_dt = _parse_bartime(trade.get("opened_at", ""))
        age = (f"{max(0, int((_utcnow() - opened_dt).total_seconds() // tf_s))} bars"
               if opened_dt else "unknown age")
        print(f"{args.name}: OPEN {trade.get('direction')} {trade.get('symbol')} "
              f"{trade.get('timeframe')} [{trade.get('platform')}]{lock}\n"
              f"  entry {trade.get('entry')} · sl {trade.get('sl')} · "
              f"tp {trade.get('tp')}\n"
              f"  opened {trade.get('opened_at')} ({age})")
    fails = int(state.get("consecutive_check_failures", 0))
    if fails:
        print(f"  warning: {fails} consecutive inconclusive checks")
    print(f"  verdicts checkpoint: {state.get('verdicts_checkpoint', 0)}")
    return 0


def cmd_clear(args) -> int:
    """Manual escape hatch: drop the tracked trade and any lock."""
    config = load_config(args.config)
    data_dir = config.get("data_dir", "data")
    state = load_state(data_dir, args.name)
    had = bool(state.get("open_trade"))
    state["open_trade"] = None
    state["consecutive_check_failures"] = 0
    save_state(data_dir, args.name, state)
    release_lock(data_dir, args.name)
    print(f"{args.name}: cleared" + ("" if had else " (nothing was tracked)"))
    return 0


def _main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Split the inner command off manually — argparse.REMAINDER misparses
    # `run NAME SYM TF --platform mt5 -- inner…` (its options-after-positionals
    # interleaving), and the inner command may itself contain flags.
    inner: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        inner = argv[i + 1:]
        argv = argv[:i]

    ap = argparse.ArgumentParser(
        description="Sequential open-trade gate for scheduled convenings.")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="gate-check, run the inner command, record")
    r.add_argument("name", help="schedule name (make_name), e.g. EURUSD_1h")
    r.add_argument("symbol")
    r.add_argument("timeframe")
    r.add_argument("--platform", choices=["tv", "mt5"], default="")
    r.set_defaults(func=lambda a: cmd_run(a, inner))

    ck = sub.add_parser("check", help="phase 1: print PROCEED/SKIP (Hermes flow)")
    ck.add_argument("name")
    ck.add_argument("symbol")
    ck.add_argument("timeframe")
    ck.add_argument("--platform", choices=["tv", "mt5"], default="")
    ck.set_defaults(func=cmd_check)

    rec = sub.add_parser("record", help="phase 2: arm the next trade (Hermes flow)")
    rec.add_argument("name")
    rec.add_argument("symbol")
    rec.add_argument("timeframe")
    rec.add_argument("--platform", choices=["tv", "mt5"], default="")
    rec.set_defaults(func=cmd_record)

    st = sub.add_parser("status", help="show the tracked open trade")
    st.add_argument("name")
    st.set_defaults(func=cmd_status)

    cl = sub.add_parser("clear", help="force-clear the tracked trade + lock")
    cl.add_argument("name")
    cl.set_defaults(func=cmd_clear)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(_main())
