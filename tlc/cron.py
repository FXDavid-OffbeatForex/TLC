"""The public scheduler — install a recurring convening as an OS cron job (PRD §2.13).

The council is LLM-driven, so a scheduled fire must invoke an *engine* (§2.14):
  - engine=agent  → your coding-agent CLI headless (e.g. `claude -p "convene …"`)
  - engine=api    → `python3 -m tlc.orchestrator …` on your own LLM key

This module only *generates and installs/removes* the schedule. On Linux/macOS it
manages `crontab`; on Windows it emits the `schtasks` command (Task Scheduler).
Each entry is tagged with a TLC marker so we only ever touch our own lines, and a
registry (`data/schedules.json`) records what's installed.

Pure helpers (parse_interval, to_cron_expr, fires_per_day, build_command,
registry I/O) are import-safe and unit-tested; only `install`/`uninstall` shell out.

CLI:
    python3 -m tlc.cron set EURUSD 1h --every 1h [--platform tv] [--council orderflow]
    python3 -m tlc.cron list
    python3 -m tlc.cron stop EURUSD_1h
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

MARKER = "# TLC-SCHEDULE"
REGISTRY = "schedules.json"

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}
_UNIT_NAME = {"m": "minute", "h": "hour", "d": "day"}


@dataclass(frozen=True)
class Interval:
    n: int
    unit: str            # "m" | "h" | "d"

    @property
    def seconds(self) -> int:
        return self.n * _UNIT_SECONDS[self.unit]

    @property
    def label(self) -> str:
        return f"{self.n}{self.unit}"


def parse_interval(spec: str) -> Interval:
    """'15m' / '2h' / '3d' → Interval. Raises ValueError on anything else."""
    m = _INTERVAL_RE.match(str(spec))
    if not m:
        raise ValueError(f"bad interval '{spec}'. Use e.g. 15m, 30m, 1h, 2h, 3d.")
    n, unit = int(m.group(1)), m.group(2).lower()
    if n < 1:
        raise ValueError("interval must be >= 1")
    ceil = {"m": 59, "h": 23, "d": 31}[unit]
    if n > ceil:
        raise ValueError(f"{n}{unit} is too large for a single cron field (max {ceil}{unit}).")
    return Interval(n, unit)


def to_cron_expr(interval: Interval) -> str:
    """Interval → 5-field cron expression (minute hour dom month dow)."""
    n = interval.n
    if interval.unit == "m":
        return f"*/{n} * * * *"
    if interval.unit == "h":
        return f"0 */{n} * * *"
    return f"0 0 */{n} * *"               # days


def fires_per_day(interval: Interval) -> float:
    """How many times this schedule fires in a day (for budget math, §2.17)."""
    return 86400.0 / interval.seconds


def schtasks_command(name: str, interval: Interval, command: str) -> str:
    """The Windows Task Scheduler equivalent (printed for the user to run)."""
    sc = {"m": "minute", "h": "hourly", "d": "daily"}[interval.unit]
    return (
        f'schtasks /create /tn "TLC_{name}" /tr "{command}" '
        f'/sc {sc} /mo {interval.n} /f'
    )


# --- command building -----------------------------------------------------

def _platform_token(platform: str) -> str:
    return f" {platform}" if platform in ("tv", "mt5") else ""


def build_command(
    symbol: str,
    timeframe: str,
    interval: Interval,
    engine: str = "agent",
    platform: str = "",
    council: str = "",
    repo_dir: str = "",
    agent_cmd: str = "claude -p",
    data_dir: str = "data",
    python: str = "python3",
) -> str:
    """The shell command a cron fire runs. engine=agent invokes the user's agent
    CLI; engine=api invokes the pure-Python orchestrator on the user's own key.

    Every interpolated field is shell-quoted: this string is persisted to the
    crontab and executed by /bin/sh, so an unescaped symbol like `EURUSD"; rm -rf ~`
    would otherwise be a command-injection vector."""
    repo_dir = repo_dir or os.getcwd()
    log = os.path.join(data_dir, "cron.log")

    if engine == "api":
        plat = f" --platform {platform}" if platform in ("tv", "mt5") else ""
        council_flag = f" --council {shlex.quote(council)}" if council else ""
        inner = (
            f"{python} -m tlc.orchestrator {shlex.quote(symbol)} {shlex.quote(timeframe)}"
            f"{plat}{council_flag} --alert"
        )
    else:  # agent: natural-language prompt to the coding-agent CLI
        plat = _platform_token(platform)
        council_phrase = f" using the {council} council" if council else ""
        prompt = (
            f"convene {symbol} {timeframe}{plat}{council_phrase} "
            f"and send the verdict to telegram"
        )
        inner = f"{agent_cmd} {shlex.quote(prompt)}"

    return f"cd {shlex.quote(repo_dir)} && {inner} >> {shlex.quote(log)} 2>&1"


def make_name(symbol: str, timeframe: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", f"{symbol}_{timeframe}").strip("_")


# --- registry -------------------------------------------------------------

def _registry_path(data_dir: str) -> str:
    return os.path.join(data_dir, REGISTRY)


def load_registry(data_dir: str = "data") -> list:
    path = _registry_path(data_dir)
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return json.load(fh)


def save_registry(entries: list, data_dir: str = "data") -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(_registry_path(data_dir), "w") as fh:
        json.dump(entries, fh, indent=2)


def upsert_registry(entry: dict, data_dir: str = "data") -> list:
    entries = [e for e in load_registry(data_dir) if e.get("name") != entry["name"]]
    entries.append(entry)
    save_registry(entries, data_dir)
    return entries


def remove_from_registry(name: str, data_dir: str = "data") -> list:
    entries = [e for e in load_registry(data_dir) if e.get("name") != name]
    save_registry(entries, data_dir)
    return entries


# --- headless settings ----------------------------------------------------

_HEADLESS_BASE_TOOLS = ["Bash", "Read", "Write", "Edit"]
_HEADLESS_MCP_TOOLS = {
    "mt5": ["mcp__MBT__get_ohlcv"],
    "tradingview": ["mcp__tvremix__get_ohlcv"],
}


def _configure_headless_settings(platform: str = "") -> None:
    """Merge the convene tool-set into .claude/settings.json so headless cron
    fires don't pause for permission prompts (no human present on a VPS)."""
    settings_path = os.path.join(".claude", "settings.json")
    os.makedirs(".claude", exist_ok=True)

    existing: dict = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as fh:
                existing = json.load(fh)
        except (json.JSONDecodeError, OSError):
            existing = {}

    needed = list(_HEADLESS_BASE_TOOLS)
    plat = (platform or "").lower()
    if plat in _HEADLESS_MCP_TOOLS:
        needed.extend(_HEADLESS_MCP_TOOLS[plat])
    else:  # unknown or both — approve all MCP tools that may fire
        for tools in _HEADLESS_MCP_TOOLS.values():
            needed.extend(tools)

    current = list(existing.get("allowedTools") or [])
    existing["allowedTools"] = list(dict.fromkeys(current + needed))

    with open(settings_path, "w") as fh:
        json.dump(existing, fh, indent=2)
    print("  → .claude/settings.json updated (headless allowedTools)")


# --- crontab management (Unix) -------------------------------------------

def _read_crontab() -> str:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("`crontab` not found — on Windows use the schtasks command instead.")
    return out.stdout if out.returncode == 0 else ""


def _write_crontab(text: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=text, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"crontab write failed: {proc.stderr.strip()}")


def _strip_block(crontab: str, name: str) -> str:
    """Remove the marker line + its command line for `name`, leaving the rest."""
    marker = f"{MARKER}:{name}"
    lines = crontab.splitlines()
    kept, skip_next = [], False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.strip() == marker:
            skip_next = True              # drop the command line that follows
            continue
        kept.append(line)
    return ("\n".join(kept).strip() + "\n") if kept else ""


def install(name: str, cron_expr: str, command: str) -> None:
    """Install/replace a crontab entry (Unix). Idempotent per name."""
    current = _strip_block(_read_crontab(), name)
    block = f"{MARKER}:{name}\n{cron_expr} {command}\n"
    new = (current.rstrip() + "\n" + block) if current.strip() else block
    _write_crontab(new)


def uninstall(name: str) -> bool:
    """Remove a crontab entry by name. Returns True if anything was removed."""
    current = _read_crontab()
    stripped = _strip_block(current, name)
    if stripped == (current.strip() + "\n" if current.strip() else ""):
        # nothing changed
        if f"{MARKER}:{name}" not in current:
            return False
    _write_crontab(stripped)
    return True


def is_windows() -> bool:
    return sys.platform.startswith("win")


# --- CLI ------------------------------------------------------------------

def _cmd_set(args) -> int:
    from .config import load_config
    from .normalize import canonical_symbol, canonical_timeframe
    from .providers.routing import resolve_platform
    cfg = load_config(args.config)
    data_dir = cfg.get("data_dir", "data")

    # Validate the free-text fields before they reach a persisted shell command.
    try:
        symbol = canonical_symbol(args.symbol)
        timeframe = canonical_timeframe(args.timeframe)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.council and not re.fullmatch(r"[A-Za-z0-9_-]+", args.council):
        print("error: council name must be alphanumeric/underscore/hyphen", file=sys.stderr)
        return 2

    interval = parse_interval(args.every)

    # tvremix bars are cached (5m–1h by bar size); scheduling faster than the
    # cache just re-reads stale data and burns the key budget (CLAUDE.md §TV).
    resolved_platform = resolve_platform(symbol, cfg, explicit=args.platform or None)
    if resolved_platform == "tradingview":
        cache = int(cfg.get("tv_cache_seconds", 300))
        if interval.seconds < cache:
            print(
                f"error: every {interval.label} is faster than tv_cache_seconds "
                f"({cache}s) for a TradingView feed — bars are cached, so it would "
                "re-read stale data. Use a longer interval or --platform mt5.",
                file=sys.stderr,
            )
            return 2

    engine = args.engine or cfg.get("engine", "agent")

    # Resolve the agent binary to an absolute path at install time.
    # cron's minimal PATH won't include mise/nvm/homebrew/etc., so a bare
    # "claude" silently fails at runtime. Catch it here instead.
    agent_cmd = cfg.get("agent_cmd", "claude -p")
    if engine == "agent" and not is_windows():
        parts = shlex.split(agent_cmd)
        binary = parts[0]
        if not os.path.isabs(binary):
            abs_bin = shutil.which(binary)
            if not abs_bin:
                print(
                    f"error: '{binary}' not found on PATH — is Claude Code installed?\n"
                    f"  Run 'which {binary}' to verify, or set agent_cmd in config.yaml\n"
                    f"  to the absolute path (e.g. /home/user/.local/bin/claude -p).",
                    file=sys.stderr,
                )
                return 2
            parts[0] = abs_bin
            agent_cmd = " ".join(shlex.quote(p) for p in parts)

    name = make_name(symbol, timeframe)
    command = build_command(
        symbol, timeframe, interval,
        engine=engine, platform=args.platform or "", council=args.council or "",
        agent_cmd=agent_cmd, data_dir=data_dir,
    )
    cron_expr = to_cron_expr(interval)
    entry = {
        "name": name, "symbol": symbol, "timeframe": timeframe,
        "interval": interval.label, "engine": engine,
        "platform": args.platform or "", "council": args.council or "",
        "cron_expr": cron_expr, "command": command,
    }

    if is_windows():
        print("Windows — run this once in an elevated terminal to register the task:\n")
        print("  " + schtasks_command(name, interval, command))
    else:
        install(name, cron_expr, command)
        print(f"installed cron: {cron_expr}  ({name})")
        if engine == "agent":
            _configure_headless_settings(args.platform or resolved_platform)
    upsert_registry(entry, data_dir)
    print(f"  → {command}")
    print(f"\nFires {fires_per_day(interval):.0f}×/day. Tip: `python3 -m tlc.vps_calc` to size a VPS.")
    return 0


def _cmd_list(args) -> int:
    from .config import load_config
    cfg = load_config(args.config)
    entries = load_registry(cfg.get("data_dir", "data"))
    if not entries:
        print("no schedules. Add one: python3 -m tlc.cron set EURUSD 1h --every 1h")
        return 0
    for e in entries:
        extra = " ".join(filter(None, [
            f"[{e['platform']}]" if e.get("platform") else "",
            f"council={e['council']}" if e.get("council") else "",
            f"engine={e.get('engine','agent')}",
        ]))
        print(f"• {e['name']:<16} {e['symbol']} {e['timeframe']} every {e['interval']}  {extra}")
    return 0


def _cmd_stop(args) -> int:
    from .config import load_config
    cfg = load_config(args.config)
    data_dir = cfg.get("data_dir", "data")
    if is_windows():
        print(f'Windows — run: schtasks /delete /tn "TLC_{args.name}" /f')
    else:
        removed = uninstall(args.name)
        print(f"removed cron: {args.name}" if removed else f"no crontab entry named {args.name}")
    remove_from_registry(args.name, data_dir)
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(description="Manage TLC scheduled convenings (cron).")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set", help="install a schedule")
    s.add_argument("symbol")
    s.add_argument("timeframe")
    s.add_argument("--every", required=True, help="interval, e.g. 15m / 1h / 3d")
    s.add_argument("--platform", choices=["tv", "mt5"], default="")
    s.add_argument("--council", default="")
    s.add_argument("--engine", choices=["agent", "api"], default="")
    s.set_defaults(func=_cmd_set)

    sub.add_parser("list", help="list schedules").set_defaults(func=_cmd_list)

    st = sub.add_parser("stop", help="remove a schedule by name")
    st.add_argument("name")
    st.set_defaults(func=_cmd_stop)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(_main())
