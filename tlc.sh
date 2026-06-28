#!/usr/bin/env bash
# TLC launcher — plays the optional Thunderclap intro, then hands off to Claude
# Code. Running `claude` directly works exactly the same; this just adds the
# animated splash for terminal users. The splash no-ops in any non-interactive
# context (no /dev/tty) and respects NO_COLOR.
#
#   ./tlc.sh                     # splash, then `claude`
#   ./tlc.sh convene EURUSD 1h   # args pass straight through to claude
#
# One-time: make `tlc` a global command (symlinks this into ~/.local/bin):
#   ./tlc.sh install             # then just type `tlc` from anywhere
set -euo pipefail

# Resolve this script's real location, following symlinks, so the launcher
# works both as `./tlc.sh` in the repo and as a `~/.local/bin/tlc` symlink.
src="${BASH_SOURCE[0]}"
while [ -h "$src" ]; do
  dir="$(cd -P "$(dirname "$src")" >/dev/null 2>&1 && pwd)"
  src="$(readlink "$src")"
  [ "${src#/}" = "$src" ] && src="$dir/$src"
done
REPO="$(cd -P "$(dirname "$src")" >/dev/null 2>&1 && pwd)"

# `tlc.sh install` — symlink this launcher into ~/.local/bin as `tlc`.
if [ "${1:-}" = "install" ]; then
  bindir="$HOME/.local/bin"
  mkdir -p "$bindir"
  ln -sf "$REPO/tlc.sh" "$bindir/tlc"
  echo "Installed: $bindir/tlc -> $REPO/tlc.sh"
  case ":$PATH:" in
    *":$bindir:"*) echo "You can now type 'tlc' from anywhere." ;;
    *) echo "Note: $bindir is not on your PATH. Add this to your shell rc:"
       echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
  exit 0
fi

cd "$REPO"
python3 -m tlc.splash || true   # never let the splash block the session
exec claude "$@"
