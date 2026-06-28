"""engine=api — a pure-Python council fan-out on the user's own LLM key (PRD §2.14).

This is the public, self-run sibling of the premium hosted orchestrator. It loads
the same legend specs and emits the same ballot/verdict schema as the on-demand
(agent) path — the only difference is *who* runs the model: here, the user's own
OpenRouter / Anthropic key (from .env), not their coding-agent subscription.

  engine=agent  → cron runs `claude -p "convene …"`        (your subscription)
  engine=api    → cron runs `python3 -m tlc.orchestrator …` (your API key)  ← this file

Models are chosen per legend from the `scout_model`/`council_model` tier in the
spec frontmatter, mapped to concrete model ids via config `models`. Cheap model
per legend, a better one for the Chairman, to keep cost down.

CLI:
    python3 -m tlc.orchestrator EURUSD 1h [--platform tv|mt5] [--council N] [--alert]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from .ballot import partition
from .chairman import aggregate
from .config import DEFAULTS as _CONFIG_DEFAULTS
from .config import load_config
from .council import (council_settings, default_council, load_council,
                      resolve_members)
from .data_desk import build_market_packet
from .notify import notify_verdict
from .sinks import LocalJsonSink

# Single source of truth for the tier→model map (see config.DEFAULTS["models"]).
DEFAULT_MODELS = dict(_CONFIG_DEFAULTS["models"])

UNIVERSAL_PROMPT = """You are {display_name}, voting in the Trading Legends Council on {symbol} ({anchor_timeframe}).
Use ONLY your own method (below). Do not adopt other schools. You vote BLIND.

Market packet:
{market_packet}

Your method:
{legend_spec_body}

Rules:
- Output ONE ballot JSON using EXACTLY these field names. Nothing else.
- If your setup is absent, vote FLAT — never force a trade.
- A directional vote MUST include positive entry, invalidation, target.
  LONG: invalidation < entry < target. SHORT: target < entry < invalidation.
- FLAT votes: set conviction to 0.0 and omit entry/invalidation/target (or set to null).

Required ballot schema (use these exact field names):
{{
  "legend": "{legend_id}",
  "symbol": "{symbol}",
  "timeframe": "{anchor_timeframe}",
  "platform": "{platform}",
  "direction": "LONG | SHORT | FLAT",
  "conviction": 0.0,
  "entry": null,
  "invalidation": null,
  "target": null
}}
"""


class OrchestratorError(RuntimeError):
    pass


# --- ballot parsing (testable, no network) --------------------------------

def extract_ballot_json(text: str) -> dict:
    """Pull the ballot object out of an LLM reply (tolerates code fences / prose)."""
    if not text or not text.strip():
        raise OrchestratorError("empty model reply")
    # Prefer a fenced ```json block.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass  # fall through to scanning the raw text
    # Otherwise scan for the first '{' that begins a balanced JSON object. Using
    # raw_decode (not find/rfind) means a stray brace in prose — e.g. "per rule
    # {note}, my ballot is {…}" — no longer swallows or breaks the real object.
    decoder = json.JSONDecoder()
    last_err: Optional[json.JSONDecodeError] = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
        if isinstance(obj, dict):
            return obj
    if last_err is not None:
        raise OrchestratorError(f"ballot JSON did not parse: {last_err}") from last_err
    raise OrchestratorError("no JSON object in model reply")


# --- spec loading ---------------------------------------------------------

def _read_spec(path: str) -> Tuple[Dict[str, Any], str]:
    from .spec_lint import parse_spec
    with open(path, encoding="utf-8") as fh:
        fm, _sections, body = parse_spec(fh.read())
    return fm, body


def _model_for(frontmatter: dict, models: dict, default_tier: str = "council") -> str:
    tier = frontmatter.get("council_model") or frontmatter.get("scout_model") or default_tier
    return models.get(tier, models.get("council", DEFAULT_MODELS["council"]))


# --- LLM transport (OpenRouter / Anthropic, stdlib only) ------------------

def llm_complete(prompt: str, model: str, config: dict, timeout: int = 90) -> str:
    provider = (config.get("orchestrator") or {}).get("provider", "openrouter")
    if provider == "anthropic":
        return _anthropic(prompt, model, timeout)
    return _openrouter(prompt, model, timeout)


def _openrouter(prompt: str, model: str, timeout: int) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise OrchestratorError("OPENROUTER_API_KEY not set (see .env.example).")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    body = _post(req, timeout)
    return body["choices"][0]["message"]["content"]


def _anthropic(prompt: str, model: str, timeout: int) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise OrchestratorError("ANTHROPIC_API_KEY not set (see .env.example).")
    payload = json.dumps({
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    body = _post(req, timeout)
    return body["content"][0]["text"]


def _post(req: urllib.request.Request, timeout: int) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise OrchestratorError(f"LLM HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise OrchestratorError(f"cannot reach LLM endpoint: {exc}") from exc


# --- the run --------------------------------------------------------------

def run_council(
    symbol: str,
    timeframe: Optional[str] = None,
    council_name: str = "",
    platform: str = "",
    config: Optional[dict] = None,
    alert: bool = False,
) -> dict:
    """Build a packet, fan the council out via the API, aggregate, persist, alert."""
    config = config if config is not None else load_config()
    models = {**DEFAULT_MODELS, **(config.get("models") or {})}

    council = load_council(council_name) if council_name else default_council()
    members, errors, _warnings = resolve_members(council)
    if errors:
        raise OrchestratorError(f"council '{council.get('name','?')}' has bad members: {errors}")

    packet = build_market_packet(
        symbol, timeframe, config=config,
        explicit_platform=(platform or None),
    )
    packet_json = json.dumps(packet, ensure_ascii=False)

    def cast(member: Tuple[str, str]) -> Optional[dict]:
        legend_id, path = member
        fm, body = _read_spec(path)
        prompt = UNIVERSAL_PROMPT.format(
            display_name=fm.get("display_name", legend_id),
            legend_id=legend_id,
            symbol=packet["symbol"],
            anchor_timeframe=packet["anchor_timeframe"],
            platform=packet.get("platform", ""),
            market_packet=packet_json,
            legend_spec_body=body,
        )
        try:
            reply = llm_complete(prompt, _model_for(fm, models), config)
            ballot = extract_ballot_json(reply)
        except OrchestratorError as exc:
            print(f"  {legend_id}: {exc}", file=sys.stderr)
            return None
        ballot.setdefault("legend", legend_id)
        ballot.setdefault("platform", packet.get("platform", ""))
        # Stamp the packet's as_of so down-projected MBT signals carry a real
        # time (to_mbt_signal reads created_at) and the verdict timestamp is set.
        ballot.setdefault("created_at", packet.get("as_of", ""))
        return ballot

    # Legends vote independently, so fan out concurrently — wall-clock collapses
    # from N serial LLM round-trips to roughly one. Order is preserved via map().
    max_workers = min(len(members), 8) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        ballots = [b for b in pool.map(cast, members) if b is not None]

    valid, invalid = partition(ballots)
    for bad in invalid:
        print(f"  dropped {bad.get('legend','?')}: {bad.get('_errors')}", file=sys.stderr)

    threshold, weights = council_settings(council, config)
    verdict = aggregate(
        valid, weights=weights, threshold=threshold,
        as_of=packet.get("as_of", ""),
    )
    verdict.setdefault("platform", packet.get("platform", ""))

    sink = LocalJsonSink(config.get("data_dir", "data"))
    for b in valid:
        sink.emit_ballot(b)
    sink.emit_verdict(verdict)

    if alert:
        fired = notify_verdict(verdict, config)
        if fired:
            print(f"alerted: {', '.join(fired)}", file=sys.stderr)

    return verdict


def _main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the council headlessly on your own LLM key.")
    ap.add_argument("symbol")
    ap.add_argument("timeframe", nargs="?", default=None)
    ap.add_argument("--platform", choices=["tv", "mt5"], default="")
    ap.add_argument("--council", default="")
    ap.add_argument("--alert", action="store_true", help="push the verdict to enabled alert channels")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    verdict = run_council(
        args.symbol, args.timeframe, council_name=args.council,
        platform=args.platform, config=cfg, alert=args.alert,
    )
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
