"""Packet prompt-caching (PRD §2.19 / milestone A4.6).

Pins the wire shape so the cost saving can't silently regress: on the
`anthropic` provider the shared packet is a separate cached content block; on
`openrouter` the prompt stays a single concatenated string. Pure Python — no
network (the transport's `_post` is stubbed).
"""

import json

import pytest

from tlc import orchestrator as o


@pytest.fixture
def capture(monkeypatch):
    """Stub the HTTP transport; return the JSON payload the provider would send."""
    box = {}

    def fake_post(req, timeout):
        box["payload"] = json.loads(req.data.decode("utf-8"))
        ballot = '{"direction":"FLAT","conviction":0.0}'
        return {
            "content": [{"text": ballot}],                      # anthropic shape
            "choices": [{"message": {"content": ballot}}],      # openrouter shape
        }

    monkeypatch.setattr(o, "_post", fake_post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    return box


PREFIX = "SHARED PACKET BLOCK " * 50  # a realistic, long shared prefix
BODY = "per-legend method + schema"


def test_anthropic_splits_into_cached_prefix_and_body(capture):
    o.llm_complete(BODY, "claude-x", {"orchestrator": {"provider": "anthropic"}},
                   cache_prefix=PREFIX)
    content = capture["payload"]["messages"][0]["content"]
    assert isinstance(content, list) and len(content) == 2
    assert content[0]["text"] == PREFIX
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1]["text"] == BODY
    assert "cache_control" not in content[1]  # only the prefix is cached


def test_anthropic_without_prefix_is_plain_string(capture):
    o.llm_complete(BODY, "claude-x", {"orchestrator": {"provider": "anthropic"}})
    assert capture["payload"]["messages"][0]["content"] == BODY


def test_openrouter_concatenates_to_single_string(capture):
    o.llm_complete(BODY, "m", {"orchestrator": {"provider": "openrouter"}},
                   cache_prefix=PREFIX)
    # openrouter sees one prompt — the same tokens, no cache markers.
    assert capture["payload"]["messages"][0]["content"] == f"{PREFIX}\n{BODY}"


def test_split_templates_recompose_to_universal_prompt():
    # The model reads the same prompt as before; only the block boundary is new.
    assert o.SHARED_PREFIX + "\n" + o.LEGEND_BODY == o.UNIVERSAL_PROMPT
