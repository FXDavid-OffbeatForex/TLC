"""LocalJsonSink — the public default. Appends newline-delimited JSON to local
files under the configured data dir. No network, no database."""

from __future__ import annotations

import json
import os
from typing import Optional


class LocalJsonSink:
    """Append ballots/verdicts/outcomes to JSONL files under `data_dir`."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    def _append(self, name: str, record: dict) -> None:
        path = os.path.join(self.data_dir, name)
        with open(path, "a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def emit_ballot(self, ballot: dict) -> None:
        self._append("ballots.jsonl", ballot)

    def emit_verdict(self, verdict: dict) -> None:
        self._append("verdicts.jsonl", verdict)

    def emit_outcome(self, outcome: dict) -> None:
        self._append("outcomes.jsonl", outcome)

    def emit_many(self, ballots: Optional[list] = None, verdict: Optional[dict] = None) -> None:
        for b in ballots or []:
            self.emit_ballot(b)
        if verdict is not None:
            self.emit_verdict(verdict)
