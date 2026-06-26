"""Tests for the Council Builder: spec lint + council resolution (PRD §1.11–1.12)."""

import pytest

from tlc.spec_lint import lint_spec, parse_spec
from tlc.council import (
    core_legend_ids, find_legend, load_council, default_council,
    resolve_members, council_settings, write_council,
)

GOOD_SPEC = """---
id: test_legend
display_name: Test Legend
tf_scope: single
default_anchor: 15m
regime_strengths: [trending]
---
# Identity
A test profile.
# Method
Do a thing on the anchor timeframe.
# Vote rules
LONG when price breaks out. invalidation = below the breakout level. conviction
scales with volume. FLAT otherwise.
# Output
Follow the shared flow. Ballot JSON.
"""


# ---- spec lint ----------------------------------------------------------

def test_parse_spec_frontmatter_and_sections():
    fm, sections, body = parse_spec(GOOD_SPEC)
    assert fm["id"] == "test_legend"
    assert fm["tf_scope"] == "single"
    assert "method" in sections and "vote rules" in sections


def test_good_spec_passes():
    errors, warnings = lint_spec(GOOD_SPEC)
    assert errors == []


def test_missing_invalidation_fails():
    spec = GOOD_SPEC.replace("invalidation = below the breakout level. ", "")
    errors, _ = lint_spec(spec)
    assert any("invalidation" in e for e in errors)


def test_missing_conviction_fails():
    spec = GOOD_SPEC.replace("conviction\nscales with volume. ", "")
    errors, _ = lint_spec(spec)
    assert any("conviction" in e for e in errors)


def test_bad_tf_scope_fails():
    spec = GOOD_SPEC.replace("tf_scope: single", "tf_scope: hourly")
    errors, _ = lint_spec(spec)
    assert any("tf_scope" in e for e in errors)


def test_bad_anchor_fails():
    spec = GOOD_SPEC.replace("default_anchor: 15m", "default_anchor: 3h")
    errors, _ = lint_spec(spec)
    assert any("default_anchor" in e for e in errors)


def test_empty_regime_strengths_fails():
    spec = GOOD_SPEC.replace("regime_strengths: [trending]", "regime_strengths: []")
    errors, _ = lint_spec(spec)
    assert any("regime_strengths" in e for e in errors)


def test_bad_id_fails():
    spec = GOOD_SPEC.replace("id: test_legend", "id: Test-Legend")
    errors, _ = lint_spec(spec)
    assert any("id" in e.lower() for e in errors)


def test_missing_output_section_fails():
    spec = GOOD_SPEC.replace("# Output\nFollow the shared flow. Ballot JSON.\n", "")
    errors, _ = lint_spec(spec)
    assert any("Output" in e for e in errors)


def test_shadow_warning():
    _, warnings = lint_spec(GOOD_SPEC, known_ids={"test_legend"}, is_core=False)
    assert any("shadows" in w for w in warnings)


def test_real_specs_lint_clean():
    # core + the shipped example custom legend
    for path in ("tlc/legends/wyckoff.md", "tlc/legends/demark.md", "my_legends/ict_ob.md"):
        with open(path, encoding="utf-8") as fh:
            errors, _ = lint_spec(fh.read())
        assert errors == [], f"{path}: {errors}"


# ---- council resolution -------------------------------------------------

def test_core_legend_ids():
    ids = core_legend_ids()
    assert len(ids) == 10
    assert "gann" in ids and "wyckoff" in ids
    assert all(not i.startswith("_") for i in ids)


def test_find_legend_core_and_custom():
    assert find_legend("gann").endswith("tlc/legends/gann.md")
    assert find_legend("ict_ob").endswith("my_legends/ict_ob.md")
    assert find_legend("does_not_exist") is None


def test_default_council_is_the_ten():
    c = default_council()
    assert sorted(c["members"]) == sorted(core_legend_ids())


def test_load_and_resolve_orderflow():
    c = load_council("orderflow")
    resolved, errors, warnings = resolve_members(c)
    ids = [m for m, _ in resolved]
    assert ids == ["wyckoff", "livermore", "ict_ob"]
    assert errors == []


def test_resolve_missing_member_errors():
    c = {"name": "x", "members": ["wyckoff", "nope_legend"]}
    _, errors, _ = resolve_members(c)
    assert any("nope_legend" in e for e in errors)


def test_council_settings_override():
    c = {"chairman": {"consensus_threshold": 0.55}, "weights": {"wyckoff": 2.0}}
    config = {"consensus_threshold": 0.65, "weights": {"gann": 1.5}}
    threshold, weights = council_settings(c, config)
    assert threshold == 0.55                  # council overrides config
    assert weights["wyckoff"] == 2.0 and weights["gann"] == 1.5


def test_council_settings_fallback_to_config():
    c = {"chairman": {}, "weights": {}}
    threshold, _ = council_settings(c, {"consensus_threshold": 0.7})
    assert threshold == 0.7


def test_shadow_warning_in_resolution(tmp_path):
    # a my_legends/ dir whose 'gann.md' shadows the core legend
    d = tmp_path / "my_legends"
    d.mkdir()
    (d / "gann.md").write_text("---\nid: gann\n---\n# Method\n", encoding="utf-8")
    c = {"name": "x", "members": ["gann"]}
    resolved, errors, warnings = resolve_members(c, my_legends_dir=str(d))
    assert errors == []
    assert any("shadows" in w for w in warnings)


def test_write_council_roundtrip(tmp_path):
    path = write_council("scalp", ["wyckoff", "ict_ob"], threshold=0.6,
                         councils_dir=str(tmp_path))
    assert path.endswith("scalp.yaml")
    c = load_council("scalp", councils_dir=str(tmp_path))
    assert c["members"] == ["wyckoff", "ict_ob"]
    assert c["chairman"]["consensus_threshold"] == 0.6


def test_write_council_rejects_unknown_member(tmp_path):
    with pytest.raises(ValueError):
        write_council("bad", ["wyckoff", "ghost_legend"], councils_dir=str(tmp_path))
