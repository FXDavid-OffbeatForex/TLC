"""TelegramSink — the public alert path (PRD §1.9, §2.15).

Pushes a verdict to a user's Telegram via the Bot API. Stdlib `urllib` only —
no new dependency. Secrets come from the environment (loaded from .env):

  TELEGRAM_BOT_TOKEN   from @BotFather  (/newbot)
  TELEGRAM_CHAT_ID     your chat/channel id (see README for the 2-minute setup)

Discord stays premium (the community/leaderboard feed). This sink is for a
trader's own private alerts. It implements the same Sink interface, so a
scheduled run can fan out to LocalJsonSink AND Telegram with no special-casing.
"""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.request
from typing import List, Optional

API_BASE = "https://api.telegram.org"
_RULE = "──────────────────"

# Pretty display names for the core 10; custom legends fall back to Title Case.
_DISPLAY = {
    "dow": "Dow", "wyckoff": "Wyckoff", "livermore": "Livermore",
    "elliott": "Elliott", "gann": "Gann", "demark": "DeMark",
    "wilder": "Wilder", "hosoda": "Ichimoku", "weinstein": "Weinstein",
    "oneil": "O'Neil",
}


class TelegramError(RuntimeError):
    pass


def _esc(s: object) -> str:
    return html.escape(str(s), quote=False)


def _as_float(v: object, default: float = 0.0) -> float:
    """Coerce a verdict field to float; tolerate strings / None from raw JSON
    (notify reads arbitrary verdict files) so formatting never raises."""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return f if f == f else default  # drop NaN


def _name(legend_id: str) -> str:
    return _DISPLAY.get(legend_id, str(legend_id).replace("_", " ").title())


def _names(ids: List[str]) -> str:
    return ", ".join(_name(i) for i in ids) if ids else "none"


def _bar(frac: float, n: int = 10) -> str:
    """A 10-cell progress bar for the consensus level."""
    try:
        frac = max(0.0, min(1.0, float(frac)))
    except (TypeError, ValueError):
        frac = 0.0
    filled = round(frac * n)
    return "▓" * filled + "░" * (n - filled)


def _fmt_px(v: object) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.6f}".rstrip("0").rstrip(".") or "0"


def format_verdict(verdict: dict) -> str:
    """Render a verdict as a rich Telegram (HTML) message with a full roll-call."""
    decision = verdict.get("decision", "?")
    symbol = _esc(verdict.get("symbol", "?"))
    platform = verdict.get("platform", "")
    plat = f" <i>({_esc(platform)})</i>" if platform else ""
    consensus = _as_float(verdict.get("consensus"), 0.0)
    for_l = verdict.get("for", []) or []
    against = verdict.get("against", []) or []
    abstain = verdict.get("abstain", []) or []

    if decision == "NO_TRADE":
        lines = [
            f"⚪ <b>NO TRADE</b> · <b>{symbol}</b>{plat}",
            _RULE,
            f"📊 Consensus {consensus:.0%}",
            _bar(consensus),
        ]
    else:
        emoji = "🟢" if decision == "LONG" else "🔴"
        lines = [
            f"{emoji} <b>{decision}</b> · <b>{symbol}</b>{plat}",
            _RULE,
            f"📊 <b>Consensus {consensus:.0%}</b>",
            _bar(consensus),
        ]
        entry = verdict.get("entry")
        if entry is not None:
            rows = [
                f"{'Entry':<7}{_fmt_px(entry)}",
                f"{'Stop':<7}{_fmt_px(verdict.get('stop'))}",
                f"{'Target':<7}{_fmt_px(verdict.get('target'))}",
            ]
            if verdict.get("rr") is not None:
                rows.append(f"{'R:R':<7}{verdict['rr']}")
            size = verdict.get("size_fraction")
            if size is not None:
                rows.append(f"{'Size':<7}{_as_float(size):.0%}")
            lines += ["", "<pre>" + "\n".join(rows) + "</pre>"]

    # Roll-call — always shown (who voted yes / no / abstained).
    lines += [
        "",
        f"🗳 <b>Council</b> · {len(for_l)} for · {len(against)} against · {len(abstain)} abstain",
        f"✅ <b>For</b> — {_esc(_names(for_l))}",
        f"❌ <b>Against</b> — {_esc(_names(against))}",
        f"⚪ <b>Abstain</b> — {_esc(_names(abstain))}",
    ]

    if decision == "NO_TRADE" and verdict.get("rationale"):
        lines += ["", f"<i>{_esc(verdict['rationale'])}</i>"]
    if verdict.get("created_at"):
        lines += ["", f"🕐 {_esc(verdict['created_at'])}"]
    return "\n".join(lines)


class TelegramSink:
    """Emit verdicts (and optionally ballots/outcomes) to Telegram."""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        quiet_no_trade: bool = True,
        timeout: int = 15,
    ):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.quiet_no_trade = quiet_no_trade
        self.timeout = timeout

    # The alert sink only acts on verdicts; ballots/outcomes are no-ops so it can
    # slot into the same fan-out loop as LocalJsonSink without erroring.
    def emit_ballot(self, ballot: dict) -> None:  # pragma: no cover - intentional no-op
        return None

    def emit_outcome(self, outcome: dict) -> None:  # pragma: no cover - intentional no-op
        return None

    def emit_verdict(self, verdict: dict) -> None:
        if self.quiet_no_trade and verdict.get("decision") == "NO_TRADE":
            return None
        self.send(format_verdict(verdict))

    # --- transport --------------------------------------------------------
    def send(self, text: str) -> dict:
        if not self.token or not self.chat_id:
            raise TelegramError(
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (see .env.example / README)."
            )
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise TelegramError(f"HTTP {exc.code} from Telegram: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise TelegramError(f"cannot reach Telegram: {exc}") from exc
        if not body.get("ok"):
            raise TelegramError(f"Telegram rejected the message: {body}")
        return body
