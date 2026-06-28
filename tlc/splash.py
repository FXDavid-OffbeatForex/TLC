"""TLC splash — the optional Thunderclap intro animation (~3.5s).

Played by the `tlc` launcher script (repo root) *before* it hands off to your
coding agent. It is deliberately NOT wired into any agent hook: a
UserPromptSubmit/SessionStart hook runs detached from the controlling terminal
(no /dev/tty) and its stdout is captured as model context, so a hook simply
cannot render a terminal animation. A launcher running in your real shell can.

The animation writes to /dev/tty and silently no-ops anywhere there is no
controlling terminal (cron, headless `claude -p`, piped output, CI), when
NO_COLOR is set, or when the window is too small. The per-session TLC banner —
shown in every client — is handled separately by CLAUDE.md / AGENTS.md.

    python3 -m tlc.splash      # play it (no-ops without a real terminal)
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import time

# ---------------------------------------------------------------------------
# Terminal plumbing — everything writes to the /dev/tty handle, not sys.stdout
# ---------------------------------------------------------------------------

ESC = "\033["
RESET = ESC + "0m"


def _open_tty():
    """A writable handle to the controlling terminal, or None if there isn't one."""
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


_GOLD, _GREY, _WHITE = 220, 240, 231


def _should_run() -> bool:
    """Cheap pre-checks before we bother opening the terminal."""
    if os.environ.get("NO_COLOR"):
        return False
    if _w() <= 20 or _h() <= 10:
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


def show() -> None:
    """Play the Thunderclap. No-ops without a real terminal."""
    if not _should_run():
        return
    tty = _open_tty()
    if tty is None:
        return

    cols, rows = _w(), _h()
    mid = cols // 2
    logo_top = max(2, rows // 2 - 3)
    noise = "▓▒░│┤╡╢╖╕╣║╗╝"

    _out(ESC + "?25l", tty)  # hide cursor
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
        _out(ESC + "?25h" + RESET, tty)  # show cursor
        tty.close()


def _main() -> int:
    show()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
