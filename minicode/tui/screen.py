from __future__ import annotations

import sys

ENTER_ALT_SCREEN = "\u001b[?1049h"
EXIT_ALT_SCREEN = "\u001b[?1049l"
ERASE_SCREEN_AND_HOME = "\u001b[2J\u001b[H"


def hide_cursor() -> None:
    sys.stdout.write("\u001b[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write("\u001b[?25h")
    sys.stdout.flush()


def enter_alternate_screen() -> None:
    sys.stdout.write(DISABLE_MOUSE_TRACKING + ENTER_ALT_SCREEN + ERASE_SCREEN_AND_HOME + ENABLE_MOUSE_TRACKING)
    sys.stdout.flush()


def exit_alternate_screen() -> None:
    sys.stdout.write(DISABLE_MOUSE_TRACKING + EXIT_ALT_SCREEN)
    sys.stdout.flush()


def clear_screen() -> None:
    sys.stdout.write("\u001b[H\u001b[J")
    sys.stdout.flush()

