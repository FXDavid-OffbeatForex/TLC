"""TLC — Trading Legends Council (public tier).

Deterministic core: input normalization, market-packet/ATR construction,
ballot schema + validation + MBT down-projection, Chairman aggregation, sinks,
and local scoring. The LLM work (each legend's analysis) is agent-native via the
Claude Code slash commands in .claude/commands/.
"""

__version__ = "0.1.0"
