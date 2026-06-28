"""TLC session-start splash — Thunderclap animation (~3.5s).

Fires once per shell session via the UserPromptSubmit hook in
.claude/settings.json. Silently no-ops when:
  - stdout is not a TTY (cron, headless claude -p, piped output)
  - NO_COLOR is set
  - the same parent shell already saw the splash this run
  - the terminal is too small (<= 20 cols or <= 10 rows)

CLI:
    python3 -m tlc.splash          # show splash (once-per-session guard applies)
    python3 -m tlc.splash --force  # always show (for testing / demo)
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import time

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

ESC = "\033["
RESET = ESC + "0m"


def _w() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def _h() -> int:
    return shutil.get_terminal_size((80, 24)).lines


def _out(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _clear() -> None:
    _out(ESC + "2J" + ESC + "H")


def _at(row: int, col: int) -> str:
    return f"{ESC}{row};{col}H"


def _fg(n: int) -> str:
    return f"{ESC}38;5;{n}m"


def _hide_cursor() -> None:
    _out(ESC + "?25l")


def _show_cursor() -> None:
    _out(ESC + "?25h")


_GOLD, _GREY, _WHITE, _CYAN = 220, 240, 231, 51

# ---------------------------------------------------------------------------
# Once-per-session guard
# ---------------------------------------------------------------------------

def _already_shown() -> bool:
    """True if this shell session already displayed the splash."""
    ppid = os.getppid()
    flag = f"/tmp/.tlc_splash_{ppid}"
    if os.path.exists(flag):
        return True
    try:
        open(flag, "w").close()
    except OSError:
        pass
    return False


def _should_run(force: bool = False) -> bool:
    if force:
        return True
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if _w() <= 20 or _h() <= 10:
        return False
    if _already_shown():
        return False
    return True


# ---------------------------------------------------------------------------
# The animation
# ---------------------------------------------------------------------------

_LOGO = [
    "████████ ██       ██████ ",
    "   ██    ██      ██      ",
    "   ██    ██      ██      ",
    "   ██    ███████  ██████ ",
]

# Jagged bolt: (row-offset-from-top, col-offset-from-centre, glyph)
_BOLT = [
    (0, 0,  "⚡"), (1, 0,  "╲"), (2, -1, "╲"), (3, -2, "╲"),
    (4, -1, "╱"), (5, 0,  "╱"), (6, 1,  "╱"), (7, 2,  "◣"),
    (8, 1,  "╲"), (9, 0,  "╲"), (10, -1,"╲"), (11, -1,"⚡"),
]


def _flash(color: int, rows: int, cols: int, step: int = 1) -> None:
    _out(_fg(color) + ESC + "7m")
    for r in range(1, rows + 1, step):
        _out(_at(r, 1) + " " * cols)
    _out(RESET)


def show(force: bool = False) -> None:
    """Display the Thunderclap splash. No-ops unless _should_run() passes."""
    if not _should_run(force):
        return

    cols, rows = _w(), _h()
    mid = cols // 2
    logo_top = max(2, rows // 2 - 3)
    noise = "▓▒░│┤╡╢╖╕╣║╗╝"

    _hide_cursor()
    try:
        _clear()

        # 1. Distant rumble — faint edge flickers
        for _ in range(2):
            edge = random.choice([1, rows])
            _out(_at(edge, 1) + _fg(_GREY) + ESC + "2m" + "·" * cols + RESET)
            time.sleep(0.12)
            _clear()
            time.sleep(0.18)

        # 2. The strike — full white flash, then dimmer after-image
        _flash(_WHITE, rows, cols)
        time.sleep(0.06)
        _clear()
        time.sleep(0.05)
        _flash(_GREY, rows, cols, step=2)
        time.sleep(0.04)
        _clear()

        # 3. Bolt cracks down the centre
        for (dr, dc, glyph) in _BOLT:
            _out(_at(2 + dr, mid + dc) + _fg(_GOLD) + glyph + RESET)
            time.sleep(0.045)
        # impact flash at the foot
        foot = 2 + _BOLT[-1][0]
        _out(_at(foot, max(1, mid - 8)) + _fg(_WHITE) + ESC + "7m" + " " * 16 + RESET)
        time.sleep(0.06)
        _clear()
        time.sleep(0.04)

        # 4. TLC logo resolves from static
        left = max(1, (cols - len(_LOGO[0])) // 2)
        for frame in range(9):
            for i, line in enumerate(_LOGO):
                shown = "".join(
                    ch if (ch == " " or random.random() < frame / 8)
                    else random.choice(noise)
                    for ch in line
                )
                color = _GREY if frame < 5 else _GOLD
                _out(_at(logo_top + i, left) + _fg(color) + shown + RESET)
            time.sleep(0.07)

        # 5. Caption types in
        caption = "T R A D I N G   L E G E N D S   C O U N C I L"
        cap_left = max(1, (cols - len(caption)) // 2)
        _out(_at(logo_top + len(_LOGO) + 1, cap_left) + _fg(_GOLD))
        for ch in caption:
            _out(ch)
            time.sleep(0.018)
        _out(RESET)

        # 6. Hold
        time.sleep(0.9)

        _clear()

    finally:
        _show_cursor()
        _out(RESET)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> int:
    force = "--force" in sys.argv
    show(force=force)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
