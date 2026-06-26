"""Sliding-window rate limiter for the tvremix key (PRD §2.16).

tvremix is free during beta but capped: 20/min · 200/hour · 1,500/day per key.
A scheduled run can fire from many short-lived processes, so the counter is
persisted to disk (`data/tvr_ratelimit.json`) and shared across them. We check
the budget *before* a call and refuse rather than risk a key suspension.

MT5 (your broker feed) has no such cap — this guard is tvremix-only.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

# (window seconds, default cap, human label)
WINDOWS: Tuple[Tuple[int, int, str], ...] = (
    (60, 20, "minute"),
    (3600, 200, "hour"),
    (86400, 1500, "day"),
)


class RateLimitError(RuntimeError):
    """Raised when a call would breach a tvremix window."""


class RateLimiter:
    """Disk-persisted sliding-window limiter. `now_fn` is injectable for tests."""

    def __init__(
        self,
        path: str = "data/tvr_ratelimit.json",
        limits: Optional[Dict[str, int]] = None,
        now_fn: Callable[[], float] = time.time,
    ):
        self.path = path
        self.now_fn = now_fn
        # limits override by label: {"per_minute":.., "per_hour":.., "per_day":..}
        limits = limits or {}
        self.caps = {
            60: limits.get("per_minute", 20),
            3600: limits.get("per_hour", 200),
            86400: limits.get("per_day", 1500),
        }

    # --- persistence ------------------------------------------------------
    def _load(self) -> List[float]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path) as fh:
                data = json.load(fh)
            return [float(t) for t in data.get("calls", [])]
        except (json.JSONDecodeError, ValueError, OSError):
            return []

    def _save(self, calls: List[float]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump({"calls": calls}, fh)

    def _prune(self, calls: List[float], now: float) -> List[float]:
        cutoff = now - 86400          # keep only the last day
        return [t for t in calls if t > cutoff]

    # --- public API -------------------------------------------------------
    def counts(self) -> Dict[str, int]:
        """Current usage per window (for status / the calculator)."""
        now = self.now_fn()
        calls = self._prune(self._load(), now)
        return {label: sum(1 for t in calls if t > now - win) for win, _, label in WINDOWS}

    def check(self) -> None:
        """Raise RateLimitError if a call now would breach a window."""
        now = self.now_fn()
        calls = self._prune(self._load(), now)
        for win, _default, label in WINDOWS:
            cap = self.caps[win]
            in_window = [t for t in calls if t > now - win]
            if len(in_window) >= cap:
                reset_in = int(win - (now - min(in_window)))
                raise RateLimitError(
                    f"tvremix {label} limit reached ({cap}/{label}). "
                    f"Retry in ~{max(reset_in, 1)}s, or space the schedule out."
                )

    def record(self) -> None:
        now = self.now_fn()
        calls = self._prune(self._load(), now)
        calls.append(now)
        self._save(calls)

    def check_and_record(self) -> None:
        """The fetch path: refuse if over budget, otherwise count this call."""
        self.check()
        self.record()
