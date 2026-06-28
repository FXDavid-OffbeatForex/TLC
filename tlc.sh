#!/usr/bin/env bash
# TLC launcher — plays the optional Thunderclap intro, then hands off to Claude
# Code in your CURRENT directory. Works the same whether you run it as
# `./tlc.sh` inside a clone or as the global `tlc` command from anywhere: it
# never points at a fixed repo, it just adds the splash on top of `claude`.
#
#   ./tlc.sh                     # splash, then `claude` in this folder
#   ./tlc.sh convene EURUSD 1h   # args pass straight through to claude
#
# One-time, optional — a global `tlc` command:
#   ./tlc.sh install
# This copies the launcher into ~/.local/bin (a copy, not a symlink), so it is
# clone-independent: delete a clone, pull a fresh one, `cd` in and `tlc` still
# works — no reinstall, nothing to dangle. The splash is found in whatever
# clone you're standing in, so a fresh clone needs no extra setup.
set -euo pipefail

if [ "${1:-}" = "install" ]; then
  bindir="$HOME/.local/bin"
  dst="$bindir/tlc"
  mkdir -p "$bindir"
  src="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  if [ "$src" != "$dst" ]; then
    rm -f "$dst"          # replace any old symlink/file with a fresh copy
    cp "$src" "$dst"
    chmod +x "$dst"
  fi
  cat <<'BANNER'

████████ ██       ██████
   ██    ██      ██        TRADING LEGENDS COUNCIL
   ██    ██      ██        ten legends · one verdict
   ██    ███████  ██████

BANNER
  echo "Installed: $dst (clone-independent)"
  case ":$PATH:" in
    *":$bindir:"*) echo "Type 'tlc' inside any TLC clone." ;;
    *) echo "Note: $bindir is not on your PATH yet. Add this to your shell rc:"
       echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
  exit 0
fi

python3 -m tlc.splash 2>/dev/null || true   # splash from the cwd's tlc package
exec claude "$@"
