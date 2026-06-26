"""Output sinks — the open-core seam (PRD §1.9).

Public ships `LocalJsonSink`. Premium adds DiscordSink / DbSink / WebsiteSink,
which are NOT in the public repo. All emit through the same interface so the
public code never changes when premium plugs in.
"""

from .base import Sink
from .local_json import LocalJsonSink
from .telegram import TelegramSink

__all__ = ["Sink", "LocalJsonSink", "TelegramSink"]
