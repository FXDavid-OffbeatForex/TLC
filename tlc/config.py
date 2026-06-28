"""Config loading. Public defaults are neutral so the repo runs identically to
premium minus the earned edge (tuned weights live in a gitignored file)."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "default_anchor_timeframe": "1h",
    "frames": ["15m", "1h", "4h", "1d"],
    "bars_per_frame": 200,
    "atr_period": 14,
    "consensus_threshold": 0.65,
    "weights": {},          # legend_id -> multiplier; absent == 1.0 (neutral)
    "data_dir": "data",

    # --- platforms / data sources (PRD §1.10) ---
    # Public default: MT5 only, so existing setups behave exactly as before.
    # Add "tradingview" to enabled_platforms (and a TVR_API_KEY in .env) to switch.
    "enabled_platforms": ["mt5"],
    "default_platform": "mt5",
    "platforms": {
        "mt5": {
            "provider": "mt5",
            "symbol_suffix": "",            # broker quirk, e.g. "zero" → EURUSDzero
            "asset_classes": ["forex", "metals", "indices"],
        },
        "tradingview": {
            "provider": "tvremix",
            "endpoint": "https://tvremix.xyz/api/mcp/v1",
            "asset_classes": ["stocks", "crypto"],
            "exchange_map": {},             # per-symbol overrides, e.g. AAPL: NASDAQ:AAPL
        },
    },
    "routing": {                            # asset class → platform (first enabled match)
        "forex": "mt5", "metals": "mt5", "indices": "mt5",
        "stocks": "tradingview", "crypto": "tradingview",
    },

    # --- scheduled mode / alerts / engines (PRD §2.13–2.17) ---
    # engine: how a scheduled fire produces a verdict.
    #   "agent" → run your coding-agent CLI headless (uses your subscription)
    #   "api"   → run tlc.orchestrator on your own LLM key (OpenRouter/Anthropic, .env)
    "engine": "agent",
    "agent_cmd": "claude -p",               # the CLI invoked when engine == agent
    "alerts": {
        "enabled": [],                      # e.g. ["telegram"] — secrets live in .env
        "telegram": {"quiet_no_trade": True},
    },
    # tvremix budget guard (tvremix-only; MT5 has no caps). Set to {} to disable.
    "rate_limits": {
        "tradingview": {"per_minute": 20, "per_hour": 200, "per_day": 1500},
    },
    "tv_cache_seconds": 300,                # min sane TV interval (smallest-bar cache)
    "orchestrator": {                       # engine == api
        "provider": "openrouter",           # "openrouter" | "anthropic"
    },
    "models": {                             # tier → concrete model id (engine == api)
        "cheap": "anthropic/claude-haiku-4.5",
        "mid": "anthropic/claude-sonnet-4.6",
        "council": "anthropic/claude-sonnet-4.6",
    },
    "vps_plans": {                          # monetization links for the calculator
        "interserver_affiliate": "https://www.interserver.net/vps/?id=579551",
        "windows_calculator": "https://offbeatforex.com/best-forex-vps/",
    },
}


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no override).

    Stdlib-only; avoids a python-dotenv dependency. Secrets (TVR_API_KEY, webhook
    URLs) live in .env, which is gitignored.
    """
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(path: str = "config.yaml", env_path: str = ".env") -> Dict[str, Any]:
    """Load config.yaml merged over DEFAULTS, and .env into the environment.

    Missing files → defaults. `platforms` is deep-merged one level so a user can
    override just `symbol_suffix` without redeclaring the whole platform block.
    """
    load_dotenv(env_path)
    cfg = copy.deepcopy(DEFAULTS)   # deep so nested defaults are never shared/mutated
    if os.path.exists(path):
        try:
            import yaml  # optional dependency
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pyyaml required to read config.yaml; `pip install pyyaml`") from exc
        with open(path) as fh:
            loaded = yaml.safe_load(fh) or {}
        platforms = loaded.pop("platforms", None)
        cfg.update(loaded)
        if platforms:                       # merge per-platform so partial overrides work
            merged = {k: dict(v) for k, v in DEFAULTS["platforms"].items()}
            for name, spec in platforms.items():
                merged[name] = {**merged.get(name, {}), **(spec or {})}
            cfg["platforms"] = merged
    return cfg
