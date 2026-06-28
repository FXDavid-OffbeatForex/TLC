#!/usr/bin/env bash
# TLC launcher — plays the optional Thunderclap intro, then hands off to Claude
# Code. Running `claude` directly works exactly the same; this just adds the
# animated splash for terminal users. The splash no-ops in any non-interactive
# context (no /dev/tty) and respects NO_COLOR.
#
#   ./tlc.sh            # splash, then `claude`
#   ./tlc.sh convene EURUSD 1h   # args pass straight through to claude
#
# Tip: add an alias so you can just type `tlc` from the repo:
#   alias tlc='/path/to/TA-Legends-Council/tlc.sh'
set -euo pipefail

cd "$(dirname "$0")"

python3 -m tlc.splash || true   # never let the splash block the session
exec claude "$@"
