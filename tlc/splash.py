"""TLC session-start splash — Thunderclap animation (~3.5s).

Fires once per session via the UserPromptSubmit hook in .claude/settings.json.
Claude Code runs hooks with stdout piped, so we write directly to /dev/tty
(the controlling terminal) instead of sys.stdout — this is what makes the
animation appear even when launched from a subprocess.

Silently no-ops when:
  - /dev/tty is unavailable (cron, headless claude -p, piped output, CI)
  - NO_COLOR is set
  - the terminal is too small (<= 20 cols or <= 10 rows)
  - the same session already showed the splash (1-hour TTL on a flag file)

CLI:
    python3 -m tlc.splash          # show splash (session guard applies)
    python3 -m tlc.splash --force  # always show (testing / demo)
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import time

# ---------------------------------------------------------------------------
# Terminal helpers — all write to the /dev/tty handle, not sys.stdout
# ---------------------------------------------------------------------------

ESC = "\033["
RESET = ESC + "0m"


def _open_tty():
    """Return a writable handle to the controlling terminal, or None."""
    try:
        return open("/dev/tty", "w")
    except OSError:
        return None


def _w() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def _h() -> int:
    return shutil.get_terminal_size((80, 24)).lines


def _out(s: str, tty) -> None:
    tty.write(s)
    tty.flush()


def _clear(tty) -> None:
    _out(ESC + "2J" + ESC + "H", tty)


def _at(row: int, col: int) -> str:
    return f"{ESC}{row};{col}H"


def _fg(n: int) -> str:
    return f"{ESC}38;5;{n}m"


def _hide_cursor(tty) -> None:
    _out(ESC + "?25l", tty)


def _show_cursor(tty) -> None:
    _out(ESC + "?25h", tty)


_GOLD, _GREY, _WHITE = 220, 240, 231

# ---------------------------------------------------------------------------
# Once-per-session guard (1-hour TTL — proxy for "same session")
# ---------------------------------------------------------------------------

_FLAG = "/tmp/.tlc_splash"
_SESSION_TTL = 3600  # seconds


def _already_shown() -> bool:
    """Return True if the splash fired within the last hour."""
    try:
        if time.time() - os.path.getmtime(_FLAG) < _SESSION_TTL:
            return True
    except OSError:
        pass
    try:
        open(_FLAG, "w").close()
    except OSError:
        pass
    return False


def _should_run(force: bool = False) -> bool:
    if force:
        return True
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
    (0,  0,  "⚡"), (1,  0,  "╲"), (2,  -1, "╲"), (3,  -2, "╲"),
    (4,  -1, "╱"), (5,  0,  "╱"), (6,  1,  "╱"), (7,  2,  "◣"),
    (8,  1,  "╲"), (9,  0,  "╲"), (10, -1, "╲"), (11, -1, "⚡"),
]


def _flash(color: int, rows: int, cols: int, tty, step: int = 1) -> None:
    _out(_fg(color) + ESC + "7m", tty)
    for r in range(1, rows + 1, step):
        _out(_at(r, 1) + " " * cols, tty)
    _out(RESET, tty)


def show(force: bool = False) -> None:
    """Display the Thunderclap splash. No-ops unless _should_run() passes."""
    if not _should_run(force):
        return

    tty = _open_tty()
    if tty is None:
        return

    cols, rows = _w(), _h()
    mid = cols // 2
    logo_top = max(2, rows // 2 - 3)
    noise = "▓▒░│┤╡╢╖╕╣║╗╝"

    _hide_cursor(tty)
    try:
        _clear(tty)

        # 1. Distant rumble — faint edge flickers
        for _ in range(2):
            edge = random.choice([1, rows])
            _out(_at(edge, 1) + _fg(_GREY) + ESC + "2m" + "·" * cols + RESET, tty)
            time.sleep(0.12)
            _clear(tty)
            time.sleep(0.18)

        # 2. The strike — full white flash, then dimmer after-image
        _flash(_WHITE, rows, cols, tty)
        time.sleep(0.06)
        _clear(tty)
        time.sleep(0.05)
        _flash(_GREY, rows, cols, tty, step=2)
        time.sleep(0.04)
        _clear(tty)

        # 3. Bolt cracks down the centre
        for (dr, dc, glyph) in _BOLT:
            _out(_at(2 + dr, mid + dc) + _fg(_GOLD) + glyph + RESET, tty)
            time.sleep(0.045)
        # impact flash at the foot
        foot = 2 + _BOLT[-1][0]
        _out(_at(foot, max(1, mid - 8)) + _fg(_WHITE) + ESC + "7m" + " " * 16 + RESET, tty)
        time.sleep(0.06)
        _clear(tty)
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
                _out(_at(logo_top + i, left) + _fg(color) + shown + RESET, tty)
            time.sleep(0.07)

        # 5. Caption types in
        caption = "T R A D I N G   L E G E N D S   C O U N C I L"
        cap_left = max(1, (cols - len(caption)) // 2)
        _out(_at(logo_top + len(_LOGO) + 1, cap_left) + _fg(_GOLD), tty)
        for ch in caption:
            _out(ch, tty)
            time.sleep(0.018)
        _out(RESET, tty)

        # 6. Hold
        time.sleep(0.9)

        _clear(tty)

    finally:
        _show_cursor(tty)
        _out(RESET, tty)
        tty.close()


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> int:
    force = "--force" in sys.argv
    show(force=force)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
