"""The Sink interface — the public/private boundary (PRD §1.9)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Sink(ABC):
    """Where ballots, verdicts, and resolved outcomes are emitted.

    Public default is LocalJsonSink (local files). Premium implementations
    (Discord, database, website) implement the same three methods.
    """

    @abstractmethod
    def emit_ballot(self, ballot: dict) -> None: ...

    @abstractmethod
    def emit_verdict(self, verdict: dict) -> None: ...

    @abstractmethod
    def emit_outcome(self, outcome: dict) -> None: ...
