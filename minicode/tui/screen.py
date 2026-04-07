from __future__ import annotations

import os
import sys

ENTER_ALT_SCREEN = "\u001b[?1049h"
EXIT_ALT_SCREEN = "\u001b[?1049l"
ERASE_SCREEN_AND_HOME = "\u001b[2J\u001b[H"
# Mouse tracking sequence breakdown:
#   ?1000h  — basic X10 mouse reporting (button press/release)
#   ?1002h  — button-event tracking (only reports while button pressed, can interfere)
#   ?1003h  — any-event tracking (reports all mouse events including scroll without button)
#   ?1006h  — SGR extended encoding (supports coordinates > 223, required for modern terminals)
# Strategy: use ?1000h (basic) + ?1003h (any-event for reliable scroll) + ?1006h (SGR format)
# This matches the TypeScript mini-code version behavior (?1000h + ?1006h) but adds
# ?1003h for better SSH/remote terminal scroll wheel support.
ENABLE_MOUSE_TRACKING = "\u001b[?1000h\u001b[?1003h\u001b[?1006h"
DISABLE_MOUSE_TRACKING = "\u001b[?1006l\u001b[?1003l\u001b[?1000l"

# Terminal types that do not support alternate screen or mouse tracking.
_DUMB_TERMS = frozenset({"dumb", "linux", ""})


# ---------------------------------------------------------------------------
# Windows VT processing
# ---------------------------------------------------------------------------

_vt_enabled = False


def _enable_windows_vt_processing() -> None:
    """Enable ANSI / VT escape sequence processing on Windows 10+.

    Without this call the console ignores escape codes for colours,
    alternate-screen, cursor visibility, mouse tracking, etc.
    The function is a no-op on non-Windows platforms or when the
    underlying API call is unavailable.
    """
    global _vt_enabled
    if _vt_enabled:
        return

    if sys.platform != "win32":
        _vt_enabled = True
        return

    try:
        import ctypes
        import ctypes.wintypes as wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_PROCESSED_OUTPUT = 0x0001

        for handle_id in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            handle = kernel32.GetStdHandle(handle_id)
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT
                kernel32.SetConsoleMode(handle, new_mode)

        # Also enable VT input processing so the console sends ANSI
        # escape sequences for special keys instead of Windows-native
        # key events (useful for ConPTY / Windows Terminal).
        STD_INPUT_HANDLE = -10
        ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
        h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode_in = wintypes.DWORD()
        if kernel32.GetConsoleMode(h_in, ctypes.byref(mode_in)):
            kernel32.SetConsoleMode(h_in, mode_in.value | ENABLE_VIRTUAL_TERMINAL_INPUT)

        _vt_enabled = True
    except Exception:
        # If ctypes is unavailable or the call fails (e.g. old Windows),
        # fall through silently — ANSI codes will simply not render.
        _vt_enabled = True


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def hide_cursor() -> None:
    _enable_windows_vt_processing()
    sys.stdout.write("\u001b[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write("\u001b[?25h")
    sys.stdout.flush()


def _is_dumb_terminal() -> bool:
    """Return True if the terminal likely doesn't support escape sequences."""
    return os.environ.get("TERM", "") in _DUMB_TERMS


def enter_alternate_screen() -> None:
    _enable_windows_vt_processing()
    if _is_dumb_terminal():
        # Dumb terminals (e.g. 'linux' console, 'dumb', piped output)
        # don't support alternate screen or mouse tracking.
        return
    sys.stdout.write(DISABLE_MOUSE_TRACKING + ENTER_ALT_SCREEN + ERASE_SCREEN_AND_HOME + ENABLE_MOUSE_TRACKING)
    sys.stdout.flush()


def exit_alternate_screen() -> None:
    if _is_dumb_terminal():
        return
    sys.stdout.write(DISABLE_MOUSE_TRACKING + EXIT_ALT_SCREEN)
    sys.stdout.flush()


def clear_screen() -> None:
    sys.stdout.write("\u001b[H\u001b[J")
    sys.stdout.flush()
