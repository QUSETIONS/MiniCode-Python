from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Union, Literal

ParsedKeyName = Literal[
    'return', 'tab', 'backspace', 'delete',
    'up', 'down', 'left', 'right',
    'pageup', 'pagedown', 'home', 'end', 'escape'
]

@dataclass(frozen=True)
class KeyEvent:
    name: str  # ParsedKeyName or 'a', 'c', etc. for ctrl-keys
    ctrl: bool
    meta: bool
    kind: str = "key"

@dataclass(frozen=True)
class TextEvent:
    text: str
    ctrl: bool
    meta: bool
    kind: str = "text"

@dataclass(frozen=True)
class WheelEvent:
    direction: Literal['up', 'down']
    kind: str = "wheel"

ParsedInputEvent = Union[KeyEvent, TextEvent, WheelEvent]

@dataclass(frozen=True)
class ParseResult:
    events: list[ParsedInputEvent]
    rest: str

CTRL_CHAR_TO_NAME: dict[str, str] = {
    '\x01': 'a',
    '\x03': 'c',
    '\x05': 'e',
    '\x0e': 'n',
    '\x0f': 'o',
    '\x10': 'p',
    '\x15': 'u',
}

def maybe_need_more_for_escape_sequence(chunk: str) -> bool:
    if not chunk:
        return False
    if chunk[0] != '\x1b':
        return False
    if len(chunk) == 1:
        return True
    
    # CSI
    if chunk[1] == '[':
        # SGR Mouse: ESC[<button;x;yM/m
        if len(chunk) >= 3 and chunk[2] == '<':
            return not any(c in 'Mm' for c in chunk[3:])
        # Legacy Mouse: ESC[M...
        if len(chunk) >= 3 and chunk[2] == 'M':
            return len(chunk) < 6
        # CSI cursor/tilde: look for terminator char (A-Z, a-z, ~)
        # Only digits, semicolons, and '?' are valid intermediate/parameter bytes
        for i in range(2, len(chunk)):
            c = chunk[i]
            if 'A' <= c <= 'Z' or 'a' <= c <= 'z' or c == '~':
                return False
            if c not in '0123456789;?':
                # Invalid character in CSI — not a valid sequence, stop waiting
                return False
        # All chars so far are parameter bytes, still waiting for terminator
        return True
        
    # SS3
    if chunk[1] == 'O':
        return len(chunk) < 3
        
    # ESC + char (Alt+char)
    # We already checked len(chunk) == 1. For Alt+char, 2 chars is complete.
    return False

def parse_escape_sequence(chunk: str) -> tuple[ParsedInputEvent | None, int]:
    if not chunk or chunk[0] != '\x1b':
        return None, 0
        
    if len(chunk) == 1:
        return KeyEvent(name='escape', ctrl=False, meta=False), 1

    # SGR Mouse: ESC[<button;x;yM/m
    sgr_match = re.match(r'^\x1b\[<(\d+);(\d+);(\d+)([Mm])', chunk)
    if sgr_match:
        button = int(sgr_match.group(1))
        # wheel events (button & 0x43 == 0x40 → up, 0x41 → down)
        if (button & 0x43) == 0x40:
            return WheelEvent(direction='up'), sgr_match.end()
        elif (button & 0x43) == 0x41:
            return WheelEvent(direction='down'), sgr_match.end()
        return None, sgr_match.end()

    # Legacy mouse: ESC[M...
    if chunk.startswith('\x1b[M') and len(chunk) >= 6:
        button = ord(chunk[3])
        if (button & 0x43) == 0x40:
            return WheelEvent(direction='up'), 6
        elif (button & 0x43) == 0x41:
            return WheelEvent(direction='down'), 6
        return None, 6

    # CSI cursor: ESC[{1;modifier}A/B/C/D/H/F
    csi_cursor_match = re.match(r'^\x1b\[(?:1;(\d+))?([A-DF-H])', chunk)
    if csi_cursor_match:
        mod_str = csi_cursor_match.group(1)
        key_char = csi_cursor_match.group(2)
        mod = int(mod_str) if mod_str else 1
        
        # Modifier logic: 2=Shift, 3=Alt, 4=Shift+Alt, 5=Ctrl, 6=Shift+Ctrl, 7=Alt+Ctrl, 8=Shift+Alt+Ctrl
        # 1=None. 
        # (mod - 1) & 4 -> Ctrl
        # (mod - 1) & 2 -> Alt/Meta
        ctrl = bool((mod - 1) & 4)
        meta = bool((mod - 1) & 2)
        
        name_map: dict[str, str] = {
            'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left', 'H': 'home', 'F': 'end'
        }
        return KeyEvent(name=name_map[key_char], ctrl=ctrl, meta=meta), csi_cursor_match.end()

    # CSI tilde: ESC[N~
    csi_tilde_match = re.match(r'^\x1b\[(\d+)~', chunk)
    if csi_tilde_match:
        n = int(csi_tilde_match.group(1))
        # 1=home,3=delete,4=end,5=pageup,6=pagedown,7=home,8=end
        tilde_map: dict[int, str] = {
            1: 'home', 3: 'delete', 4: 'end', 5: 'pageup', 6: 'pagedown', 7: 'home', 8: 'end'
        }
        if n in tilde_map:
            return KeyEvent(name=tilde_map[n], ctrl=False, meta=False), csi_tilde_match.end()
        return None, csi_tilde_match.end()

    # SS3: ESC O A/B/C/D/H/F
    ss3_match = re.match(r'^\x1bO([A-DF-H])', chunk)
    if ss3_match:
        key_char = ss3_match.group(1)
        name_map: dict[str, str] = {
            'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left', 'H': 'home', 'F': 'end'
        }
        return KeyEvent(name=name_map[key_char], ctrl=False, meta=False), ss3_match.end()

    # ESC+Tab
    if chunk.startswith('\x1b\t'):
        return KeyEvent(name='tab', ctrl=False, meta=True), 2

    # ESC+char (Alt+char)
    esc_char_match = re.match(r'^\x1b([^\x1b\[O])', chunk)
    if esc_char_match:
        char = esc_char_match.group(1)
        return TextEvent(text=char, ctrl=False, meta=True), 2
        
    # Default to bare escape if nothing else matches and we are not waiting for more
    return KeyEvent(name='escape', ctrl=False, meta=False), 1

def parse_input_chunk(chunk: str) -> ParseResult:
    events: list[ParsedInputEvent] = []
    i = 0
    while i < len(chunk):
        if maybe_need_more_for_escape_sequence(chunk[i:]):
            break
            
        char = chunk[i]
        
        # Escape sequence
        if char == '\x1b':
            event, consumed = parse_escape_sequence(chunk[i:])
            if event:
                events.append(event)
            i += consumed
            continue

        # CR, LF, CR+LF -> return
        if char == '\r':
            if i + 1 < len(chunk) and chunk[i+1] == '\n':
                i += 2
            else:
                i += 1
            events.append(KeyEvent(name='return', ctrl=False, meta=False))
            continue
            
        if char == '\n':
            events.append(KeyEvent(name='return', ctrl=False, meta=False))
            i += 1
            continue
            
        # Tab
        if char == '\t':
            events.append(KeyEvent(name='tab', ctrl=False, meta=False))
            i += 1
            continue
            
        # Backspace (0x7f, 0x08)
        if char in ('\x7f', '\x08'):
            events.append(KeyEvent(name='backspace', ctrl=False, meta=False))
            i += 1
            continue
            
        # Ctrl chars (0x01-0x1a)
        if '\x01' <= char <= '\x1a':
            if char in CTRL_CHAR_TO_NAME:
                events.append(KeyEvent(name=CTRL_CHAR_TO_NAME[char], ctrl=True, meta=False))
            # Swallow other control characters
            i += 1
            continue

        # Regular text
        events.append(TextEvent(text=char, ctrl=False, meta=False))
        i += 1
        
    return ParseResult(events=events, rest=chunk[i:])
