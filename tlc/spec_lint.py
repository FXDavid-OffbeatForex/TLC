"""Legend spec validator — the admission gate (PRD §1.12).

Every legend (core or custom) must lint before it can vote, so the ballot contract
and the Historian stay intact. Pure Python; no MT5 / LLM / network.

CLI:  python3 -m tlc.spec_lint <spec.md> [more.md ...]
exit 0 if all clean, 1 if any spec has errors.
"""

from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional, Tuple

from .normalize import canonical_timeframe

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

REQUIRED_FRONTMATTER = ("id", "display_name", "tf_scope", "default_anchor", "regime_strengths")


def parse_spec(text: str) -> Tuple[dict, Dict[str, str], str]:
    """Split a spec into (frontmatter dict, {heading_lower: body}, full body text)."""
    m = _FRONTMATTER_RE.match(text)
    if m:
        fm_text, body = m.group(1), m.group(2)
        try:
            import yaml
            frontmatter = yaml.safe_load(fm_text) or {}
        except ImportError:  # pragma: no cover - yaml is a declared dep
            frontmatter = _mini_yaml(fm_text)
    else:
        frontmatter, body = {}, text

    sections: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    for line in body.splitlines():
        hm = _HEADING_RE.match(line)
        if hm:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = hm.group(1).strip().lower()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return frontmatter if isinstance(frontmatter, dict) else {}, sections, body


def _mini_yaml(text: str) -> dict:  # pragma: no cover - fallback only
    """Tiny key: value / [list] parser if PyYAML is unavailable."""
    out: dict = {}
    for line in text.splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            out[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        else:
            out[k] = v
    return out


def lint_spec(
    text: str,
    known_ids: Optional[set] = None,
    is_core: bool = False,
) -> Tuple[List[str], List[str]]:
    """Validate a spec. Returns (errors, warnings); empty errors == admissible."""
    errors: List[str] = []
    warnings: List[str] = []
    fm, sections, body = parse_spec(text)

    # --- frontmatter ---
    for key in REQUIRED_FRONTMATTER:
        if key not in fm or fm[key] in (None, "", [], {}):
            errors.append(f"frontmatter: missing '{key}'")

    legend_id = fm.get("id")
    if legend_id and not _ID_RE.match(str(legend_id)):
        errors.append(f"id '{legend_id}' must be lowercase letters/digits/underscore, starting with a letter")

    tf_scope = fm.get("tf_scope")
    if tf_scope is not None and tf_scope not in ("single", "multi"):
        errors.append(f"tf_scope must be 'single' or 'multi', got '{tf_scope}'")

    anchor = fm.get("default_anchor")
    if anchor is not None:
        try:
            canonical_timeframe(str(anchor))
        except ValueError:
            errors.append(f"default_anchor '{anchor}' is not a canonical timeframe")

    rs = fm.get("regime_strengths")
    if rs is not None and (not isinstance(rs, list) or not rs):
        errors.append("regime_strengths must be a non-empty list")

    # Optional `needs:` — deterministic indicator ids to pre-compute (§1.13). A
    # typo would silently compute nothing, so surface it as a warning.
    needs = fm.get("needs")
    if needs is not None:
        if not isinstance(needs, list):
            errors.append("needs must be an inline list of indicator ids, e.g. needs: [rsi14, adx14]")
        else:
            from .indicators import known_ids as _indicator_ids
            unknown = [n for n in needs if n not in _indicator_ids()]
            if unknown:
                warnings.append(f"needs references unknown indicator id(s): {unknown} (see tlc/indicators.py REGISTRY)")

    # --- body sections ---
    def has_section(substr: str) -> bool:
        return any(substr in heading for heading in sections)

    if not has_section("method"):
        errors.append("missing a 'Method' section")
    if not any("vote" in h for h in sections):
        errors.append("missing a 'Vote rules' section (LONG/SHORT/FLAT conditions)")
    if not has_section("output"):
        errors.append("missing an 'Output' section")

    body_lower = body.lower()
    if "invalidation" not in body_lower:
        errors.append("no invalidation rule found — required so the Chairman can set a stop and the call can be scored")
    if "conviction" not in body_lower:
        errors.append("no conviction driver described")

    # --- uniqueness / shadowing ---
    if known_ids and legend_id in known_ids and not is_core:
        warnings.append(f"id '{legend_id}' shadows an existing legend (it will take precedence)")

    return errors, warnings


def lint_file(path: str, known_ids: Optional[set] = None) -> Tuple[List[str], List[str]]:
    with open(path, encoding="utf-8") as fh:
        return lint_spec(fh.read(), known_ids=known_ids)


def _main(argv: List[str]) -> int:
    if not argv:
        print("usage: python3 -m tlc.spec_lint <spec.md> [more.md ...]", file=sys.stderr)
        return 2
    bad = 0
    for path in argv:
        errors, warnings = lint_file(path)
        if errors:
            bad += 1
            print(f"✗ {path}")
            for e in errors:
                print(f"    error: {e}")
        else:
            print(f"✓ {path}")
        for w in warnings:
            print(f"    warning: {w}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
