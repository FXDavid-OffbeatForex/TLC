"""Council rosters — load definitions + resolve members (PRD §1.11).

A council is a named roster file (`councils/<name>.yaml`): which legends vote, plus
optional per-council Chairman settings. Members resolve `my_legends/<id>.md` first
(user-authored, may be your edge), then the canonical `tlc/legends/<id>.md`.

Pure Python; no MT5 / LLM / network.

CLI:
  python3 -m tlc.council list
  python3 -m tlc.council show <name>
  python3 -m tlc.council new <name> <id> [<id> ...] [--threshold 0.6]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Canonical specs ship with the package; user dirs live at the repo root (cwd).
LEGENDS_DIR = str(Path(__file__).parent / "legends")
MY_LEGENDS_DIR = "my_legends"
COUNCILS_DIR = "councils"


def core_legend_ids(legends_dir: str = LEGENDS_DIR) -> List[str]:
    """The canonical legend ids (every `*.md` in tlc/legends except `_shared` files)."""
    d = Path(legends_dir)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.md") if not p.name.startswith("_"))


def find_legend(
    legend_id: str,
    my_legends_dir: str = MY_LEGENDS_DIR,
    legends_dir: str = LEGENDS_DIR,
) -> Optional[str]:
    """Resolve a legend id to a spec path: my_legends/ first, then core."""
    for d in (my_legends_dir, legends_dir):
        p = Path(d) / f"{legend_id}.md"
        if p.exists():
            return str(p)
    return None


def load_council(name: str, councils_dir: str = COUNCILS_DIR) -> Dict[str, Any]:
    """Load a council by name or path. Missing → FileNotFoundError."""
    p = Path(name)
    if not p.exists():
        for ext in (".yaml", ".yml"):
            cand = Path(councils_dir) / f"{name}{ext}"
            if cand.exists():
                p = cand
                break
    if not p.exists():
        raise FileNotFoundError(f"council '{name}' not found in {councils_dir}/")
    import yaml
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("name", p.stem)
    data.setdefault("description", "")
    data.setdefault("members", [])
    data.setdefault("chairman", {})
    data.setdefault("weights", {})
    return data


def default_council(legends_dir: str = LEGENDS_DIR) -> Dict[str, Any]:
    """The implicit council used when none is named: the canonical 10."""
    return {
        "name": "standard",
        "description": "The canonical 10 legends.",
        "members": core_legend_ids(legends_dir),
        "chairman": {},
        "weights": {},
    }


def resolve_members(
    council: Dict[str, Any],
    my_legends_dir: str = MY_LEGENDS_DIR,
    legends_dir: str = LEGENDS_DIR,
) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
    """Resolve member ids → [(id, path)]. Returns (resolved, errors, warnings)."""
    resolved: List[Tuple[str, str]] = []
    errors: List[str] = []
    warnings: List[str] = []
    core = set(core_legend_ids(legends_dir))
    legends_dirname = Path(legends_dir).name
    for member in council.get("members", []):
        path = find_legend(member, my_legends_dir, legends_dir)
        if not path:
            errors.append(f"member '{member}' not found in {my_legends_dir}/ or {legends_dir}/")
            continue
        resolved.append((member, path))
        if member in core and Path(path).parent.name != legends_dirname:
            warnings.append(f"'{member}' in {my_legends_dir}/ shadows the core legend")
    if not resolved and not errors:
        errors.append("council has no members")
    return resolved, errors, warnings


def council_settings(council: Dict[str, Any], config: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """Effective (consensus_threshold, weights): council overrides config defaults."""
    threshold = (council.get("chairman") or {}).get(
        "consensus_threshold", config.get("consensus_threshold", 0.65)
    )
    weights: Dict[str, float] = dict(config.get("weights") or {})
    weights.update(council.get("weights") or {})
    return threshold, weights


def list_councils(councils_dir: str = COUNCILS_DIR) -> List[str]:
    d = Path(councils_dir)
    if not d.exists():
        return []
    return sorted({p.stem for p in d.glob("*.yaml")} | {p.stem for p in d.glob("*.yml")})


def write_council(
    name: str,
    members: List[str],
    threshold: Optional[float] = None,
    description: str = "",
    councils_dir: str = COUNCILS_DIR,
    overwrite: bool = False,
) -> str:
    """Write a council file. Returns the path. Validates member resolution first.

    Refuses to clobber an existing roster unless `overwrite=True`, so a reused
    name can't silently destroy a user's hand-tuned council."""
    council = {"name": name, "description": description, "members": members,
               "chairman": {}, "weights": {}}
    if threshold is not None:
        council["chairman"]["consensus_threshold"] = threshold
    _, errors, _ = resolve_members(council)
    if errors:
        raise ValueError("; ".join(errors))
    os.makedirs(councils_dir, exist_ok=True)
    path = Path(councils_dir) / f"{name}.yaml"
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"council '{name}' already exists at {path}. "
            "Pass --force to overwrite, or pick another name."
        )
    import yaml
    path.write_text(yaml.safe_dump(council, sort_keys=False), encoding="utf-8")
    return str(path)


def _print_council(council: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> None:
    resolved, errors, warnings = resolve_members(council)
    threshold, weights = council_settings(council, config or {})
    print(f"council: {council['name']}  (threshold {threshold})")
    if council.get("description"):
        print(f"  {council['description']}")
    core_root = os.path.abspath(LEGENDS_DIR)
    for member, path in resolved:
        # Compare resolved roots, not a substring — a repo path that merely
        # *contains* 'my_legends' must not mislabel a core legend.
        origin = "core" if os.path.abspath(path).startswith(core_root) else "my_legends"
        w = f"  weight {weights[member]}" if member in weights else ""
        print(f"  • {member:14} [{origin}]{w}")
    for w in warnings:
        print(f"  warning: {w}")
    for e in errors:
        print(f"  error: {e}")


def _main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    try:
        from .config import load_config
        config = load_config()
    except Exception:
        config = {}

    if cmd == "list":
        print("default council: standard (the canonical 10)")
        names = list_councils()
        if names:
            print("custom councils:")
            for n in names:
                print(f"  • {n}")
        else:
            print("(no custom councils yet — create one with `new`)")
        return 0

    if cmd == "show":
        if not rest:
            print("usage: python3 -m tlc.council show <name>", file=sys.stderr)
            return 2
        council = default_council() if rest[0] == "standard" else load_council(rest[0])
        _print_council(council, config)
        return 0

    if cmd == "new":
        if len(rest) < 2:
            print("usage: python3 -m tlc.council new <name> <id> [<id> ...] [--threshold 0.6]", file=sys.stderr)
            return 2
        threshold = None
        force = False
        ids: List[str] = []
        i = 0
        while i < len(rest):
            if rest[i] == "--threshold":
                if i + 1 >= len(rest):
                    print("error: --threshold needs a value", file=sys.stderr)
                    return 2
                try:
                    threshold = float(rest[i + 1])
                except ValueError:
                    print(f"error: --threshold must be a number, got '{rest[i + 1]}'", file=sys.stderr)
                    return 2
                i += 2
                continue
            if rest[i] == "--force":
                force = True; i += 1; continue
            ids.append(rest[i]); i += 1
        if len(ids) < 2:
            print("usage: python3 -m tlc.council new <name> <id> [<id> ...] [--threshold 0.6] [--force]", file=sys.stderr)
            return 2
        name, members = ids[0], ids[1:]
        try:
            path = write_council(name, members, threshold=threshold, overwrite=force)
        except (ValueError, FileExistsError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"saved → {path}")
        _print_council(load_council(name), config)
        return 0

    print(f"unknown command '{cmd}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
