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

import json
import os
import urllib.error
import urllib.request
from typing import Optional

API_BASE = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


def format_verdict(verdict: dict) -> str:
    """Render a verdict as a compact Telegram (Markdown) message."""
    decision = verdict.get("decision", "?")
    symbol = verdict.get("symbol", "?")
    platform = verdict.get("platform", "")
    plat = f" · {platform}" if platform else ""
    consensus = verdict.get("consensus", 0.0)

    if decision == "NO_TRADE":
        head = f"⚪ *NO TRADE* — {symbol}{plat}"
        why = verdict.get("rationale", "Council split / below threshold.")
        return f"{head}\n_{why}_"

    arrow = "🟢" if decision == "LONG" else "🔴"
    lines = [
        f"{arrow} *{decision}* — {symbol}{plat}   ({consensus:.0%} consensus)",
    ]
    entry, stop, target = verdict.get("entry"), verdict.get("stop"), verdict.get("target")
    if entry is not None:
        lines.append(f"entry `{entry}`  ·  stop `{stop}`  ·  target `{target}`")
    rr = verdict.get("rr")
    size = verdict.get("size_fraction")
    bits = []
    if rr is not None:
        bits.append(f"R:R `{rr}`")
    if size is not None:
        bits.append(f"size `{size}`")
    if bits:
        lines.append("  ·  ".join(bits))
    for_l = verdict.get("for", [])
    against = verdict.get("against", [])
    if for_l:
        lines.append(f"for: {', '.join(for_l)}")
    if against:
        lines.append(f"against: {', '.join(against)}")
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
            "parse_mode": "Markdown",
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
