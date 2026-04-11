"""Terminal markdown renderer with syntax highlighting for code blocks.

Provides rich rendering of markdown content in the terminal:
- Headings with visual hierarchy
- Code blocks with basic syntax highlighting
- Inline code with background color
- Bold, italic, strikethrough
- Lists with colored bullets/numbers
- Blockquotes with visual bars
- Tables with aligned columns
- Horizontal rules
- Links with underline

Inspired by Claude Code's markdown rendering quality.
"""
from __future__ import annotations

import re
from typing import Match

# ---------------------------------------------------------------------------
# ANSI escape codes
# ---------------------------------------------------------------------------

RESET = "\u001b[0m"
BOLD = "\u001b[1m"
DIM = "\u001b[2m"
ITALIC = "\u001b[3m"
UNDERLINE = "\u001b[4m"
STRIKETHROUGH = "\u001b[9m"

# Foreground colors
BLACK = "\u001b[30m"
RED = "\u001b[31m"
GREEN = "\u001b[32m"
YELLOW = "\u001b[33m"
BLUE = "\u001b[34m"
MAGENTA = "\u001b[35m"
CYAN = "\u001b[36m"
WHITE = "\u001b[37m"
BRIGHT_RED = "\u001b[91m"
BRIGHT_GREEN = "\u001b[92m"
BRIGHT_YELLOW = "\u001b[93m"
BRIGHT_BLUE = "\u001b[94m"
BRIGHT_MAGENTA = "\u001b[95m"
BRIGHT_CYAN = "\u001b[96m"
BRIGHT_WHITE = "\u001b[97m"

# 256-color palette
SUBTLE = "\u001b[38;5;243m"
CODE_BG = "\u001b[48;5;236m"
CODE_FG = "\u001b[38;5;215m"
QUOTE_BAR = "\u001b[38;5;243m"
HEADING_ACCENT = "\u001b[38;5;39m"

# Syntax highlighting colors
SYN_KEYWORD = "\u001b[38;5;141m"      # purple for keywords
SYN_STRING = "\u001b[38;5;106m"       # green for strings
SYN_COMMENT = "\u001b[38;5;245m"      # gray for comments
SYN_NUMBER = "\u001b[38;5;208m"       # orange for numbers
SYN_FUNCTION = "\u001b[38;5;153m"     # blue for functions
SYN_TYPE = "\u001b[38;5;178m"         # yellow for types
SYN_OPERATOR = "\u001b[38;5;180m"     # light orange for operators
SYN_DECORATOR = "\u001b[38;5;203m"    # salmon for decorators
SYN_PROPERTY = "\u001b[38;5;153m"     # blue for properties
SYN_PUNCTUATION = "\u001b[38;5;246m"  # gray for punctuation


# ---------------------------------------------------------------------------
# Pre-compiled regexes
# ---------------------------------------------------------------------------

_RE_TABLE_SEP = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")
_RE_TABLE_ROW = re.compile(r"^\|.*\|$")
_RE_LIST_ITEM = re.compile(r"^(\s*)[-*+]\s+")
_RE_NUMBERED_LIST = re.compile(r"^(\s*)(\d+)\.\s+")
_RE_TASK_ITEM = re.compile(r"^(\s*)- \[([ xX])\]\s+")

# Combined inline pattern: match code, bold, italic, strikethrough, links
_RE_INLINE = re.compile(
    r"`([^`]+)`"                          # group 1: inline code
    r"|\*\*([^*]+)\*\*"                   # group 2: bold
    r"|~~([^~]+)~~"                       # group 3: strikethrough
    r"|(?<!\*)\*([^*]+)\*(?!\*)"          # group 4: italic
    r"|\[([^\]]+)\]\(([^)]+)\)"          # group 5: link text, group 6: link url
)


# ---------------------------------------------------------------------------
# Syntax highlighting
# ---------------------------------------------------------------------------

# Language-specific keyword sets
_KEYWORDS = {
    "python": {
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield",
    },
    "javascript": {
        "async", "await", "break", "case", "catch", "class", "const",
        "continue", "debugger", "default", "delete", "do", "else", "export",
        "extends", "false", "finally", "for", "function", "if", "import",
        "in", "instanceof", "let", "new", "null", "of", "return", "static",
        "super", "switch", "this", "throw", "true", "try", "typeof",
        "undefined", "var", "void", "while", "with", "yield",
    },
    "typescript": {
        "async", "await", "break", "case", "catch", "class", "const",
        "continue", "debugger", "default", "delete", "do", "else", "enum",
        "export", "extends", "false", "finally", "for", "function", "if",
        "implements", "import", "in", "instanceof", "interface", "let",
        "new", "null", "of", "package", "private", "protected", "public",
        "readonly", "return", "static", "super", "switch", "this", "throw",
        "true", "try", "type", "typeof", "undefined", "var", "void",
        "while", "with", "yield",
    },
    "rust": {
        "as", "async", "await", "break", "const", "continue", "crate",
        "dyn", "else", "enum", "extern", "false", "fn", "for", "if",
        "impl", "in", "let", "loop", "match", "mod", "move", "mut",
        "pub", "ref", "return", "self", "Self", "static", "struct",
        "super", "trait", "true", "type", "unsafe", "use", "where",
        "while",
    },
    "go": {
        "break", "case", "chan", "const", "continue", "default", "defer",
        "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
        "interface", "map", "package", "range", "return", "select", "struct",
        "switch", "type", "var",
    },
    "java": {
        "abstract", "assert", "boolean", "break", "byte", "case", "catch",
        "char", "class", "const", "continue", "default", "do", "double",
        "else", "enum", "extends", "final", "finally", "float", "for",
        "if", "implements", "import", "instanceof", "int", "interface",
        "long", "native", "new", "package", "private", "protected", "public",
        "return", "short", "static", "strictfp", "super", "switch",
        "synchronized", "this", "throw", "throws", "transient", "try",
        "void", "volatile", "while",
    },
}

# Map aliases
_KEYWORDS["js"] = _KEYWORDS["javascript"]
_KEYWORDS["ts"] = _KEYWORDS["typescript"]
_KEYWORDS["py"] = _KEYWORDS["python"]
_KEYWORDS["rs"] = _KEYWORDS["rust"]


# Regex for syntax tokenization (applied inside code blocks)
_RE_SYNTAX = re.compile(
    r"(?P<comment>#.*|//.*|/\*[\s\S]*?\*/|<!--[\s\S]*?-->)"
    r"|(?P<string>(?:\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`))"
    r"|(?P<decorator>@\w+)"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<word>\b\w+\b)"
    r"|(?P<operator>[+\-*/%=<>!&|^~]+)"
    r"|(?P<punctuation>[{}()\[\],;:.])"
)


def _highlight_code(line: str, lang: str = "") -> str:
    """Apply basic syntax highlighting to a single line of code.
    
    Uses a simple regex-based tokenizer. Not a full parser, but
    good enough for terminal display.
    """
    if not lang:
        return f"{CODE_BG}{DIM} {line} {RESET}"
    
    keywords = _KEYWORDS.get(lang.lower(), set())
    result = []
    last_end = 0
    
    for match in _RE_SYNTAX.finditer(line):
        # Add any plain text before this match
        if match.start() > last_end:
            result.append(f"{CODE_BG}{DIM}{line[last_end:match.start()]}{RESET}")
        
        if match.group("comment"):
            result.append(f"{CODE_BG}{SYN_COMMENT}{match.group('comment')}{RESET}")
        elif match.group("string"):
            result.append(f"{CODE_BG}{SYN_STRING}{match.group('string')}{RESET}")
        elif match.group("decorator"):
            result.append(f"{CODE_BG}{SYN_DECORATOR}{match.group('decorator')}{RESET}")
        elif match.group("number"):
            result.append(f"{CODE_BG}{SYN_NUMBER}{match.group('number')}{RESET}")
        elif match.group("word"):
            word = match.group("word")
            if word in keywords:
                result.append(f"{CODE_BG}{SYN_KEYWORD}{BOLD}{word}{RESET}")
            elif word[0].isupper():
                # Possible type/class name
                result.append(f"{CODE_BG}{SYN_TYPE}{word}{RESET}")
            elif match.end() < len(line) and line[match.end()] == "(":
                # Function call
                result.append(f"{CODE_BG}{SYN_FUNCTION}{word}{RESET}")
            else:
                result.append(f"{CODE_BG}{DIM}{word}{RESET}")
        elif match.group("operator"):
            result.append(f"{CODE_BG}{SYN_OPERATOR}{match.group('operator')}{RESET}")
        elif match.group("punctuation"):
            result.append(f"{CODE_BG}{SYN_PUNCTUATION}{match.group('punctuation')}{RESET}")
        else:
            result.append(f"{CODE_BG}{DIM}{match.group(0)}{RESET}")
        
        last_end = match.end()
    
    # Add any remaining plain text
    if last_end < len(line):
        result.append(f"{CODE_BG}{DIM}{line[last_end:]}{RESET}")
    
    # If no matches were found, return the whole line dimmed
    if not result:
        return f"{CODE_BG}{DIM} {line} {RESET}"
    
    return "".join(result)


# ---------------------------------------------------------------------------
# Inline formatting
# ---------------------------------------------------------------------------

def _inline_replace(m: Match) -> str:
    """Single-pass replacement callback for inline markdown."""
    if m.group(1) is not None:
        # Inline code
        return f"{CODE_BG}{CODE_FG}{m.group(1)}{RESET}"
    if m.group(2) is not None:
        # Bold
        return f"{BOLD}{m.group(2)}{RESET}"
    if m.group(3) is not None:
        # Strikethrough
        return f"{STRIKETHROUGH}{DIM}{m.group(3)}{RESET}"
    if m.group(4) is not None:
        # Italic
        return f"{ITALIC}{m.group(4)}{RESET}"
    if m.group(5) is not None:
        # Link
        return f"{UNDERLINE}{BRIGHT_CYAN}{m.group(5)}{RESET}{DIM}({m.group(6)}){RESET}"
    return m.group(0)


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

# Rendering cache: hash(input) → rendered output
# This avoids re-rendering the same markdown on every frame when
# the transcript hasn't changed.
_md_cache: dict[int, str] = {}
_MD_CACHE_MAX = 300


def render_markdownish(input_text: str) -> str:
    """Render markdown text with terminal formatting and syntax highlighting.
    
    Supports:
    - Fenced code blocks with language-specific syntax highlighting
    - Inline code, bold, italic, strikethrough, links
    - Headings (H1-H3) with visual hierarchy
    - Unordered, ordered, and task lists
    - Blockquotes with visual bars
    - Tables with aligned columns
    - Horizontal rules
    
    Results are cached by content hash to avoid redundant re-rendering.
    """
    # Check cache
    content_hash = hash(input_text)
    cached = _md_cache.get(content_hash)
    if cached is not None:
        return cached
    
    lines = input_text.split("\n")
    in_code_block = False
    code_lang = ""
    result_lines: list[str] = []

    for line in lines:
        # ---- Fenced code blocks ----
        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line[3:].strip()
                if code_lang:
                    result_lines.append(f"{CODE_BG}{SUBTLE} {code_lang} {RESET}")
                else:
                    result_lines.append(f"{SUBTLE}{'─' * 4}{RESET}")
            else:
                in_code_block = False
                result_lines.append(f"{SUBTLE}{'─' * 4}{RESET}")
            continue

        if in_code_block:
            result_lines.append(_highlight_code(line, code_lang))
            continue

        trimmed_line = line.strip()

        # ---- Horizontal rule ----
        if trimmed_line in ("---", "***", "___"):
            result_lines.append(f"{SUBTLE}{'─' * 20}{RESET}")
            continue

        # ---- Table separator ----
        if _RE_TABLE_SEP.match(trimmed_line):
            result_lines.append(f"{SUBTLE}{trimmed_line.replace('|', ' ').strip()}{RESET}")
            continue

        # ---- Table data row ----
        if _RE_TABLE_ROW.match(trimmed_line):
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            result_lines.append(f" {SUBTLE}│{RESET} ".join(cells))
            continue

        # ---- Headings ----
        if line.startswith("### "):
            result_lines.append(f"{HEADING_ACCENT}{BOLD}  {line[4:]}{RESET}")
            continue
        if line.startswith("## "):
            result_lines.append(f"{HEADING_ACCENT}{BOLD}{UNDERLINE} {line[3:]}{RESET}")
            continue
        if line.startswith("# "):
            result_lines.append(f"{BRIGHT_CYAN}{BOLD}{UNDERLINE} {line[2:]}{RESET}")
            continue

        # ---- Blockquote ----
        if line.startswith("> "):
            result_lines.append(f"{QUOTE_BAR}▎{RESET} {ITALIC}{DIM}{line[2:]}{RESET}")
            continue

        # ---- Task list ----
        task_match = _RE_TASK_ITEM.match(line)
        if task_match:
            indent = task_match.group(1)
            checked = task_match.group(2).lower() == "x"
            rest = line[task_match.end():]
            checkbox = f"{BRIGHT_GREEN}✓{RESET}" if checked else f"{SUBTLE}○{RESET}"
            formatted = f"{indent}{checkbox} {rest}"
            formatted = _RE_INLINE.sub(_inline_replace, formatted)
            result_lines.append(formatted)
            continue

        # ---- Unordered list ----
        list_match = _RE_LIST_ITEM.match(line)
        if list_match:
            indent = list_match.group(1)
            rest = line[list_match.end():]
            formatted = f"{indent}{BRIGHT_YELLOW}•{RESET} {rest}"
            formatted = _RE_INLINE.sub(_inline_replace, formatted)
            result_lines.append(formatted)
            continue

        # ---- Numbered list ----
        num_match = _RE_NUMBERED_LIST.match(line)
        if num_match:
            indent = num_match.group(1)
            num = num_match.group(2)
            rest = line[num_match.end():]
            formatted = f"{indent}{BRIGHT_CYAN}{num}.{RESET} {rest}"
            formatted = _RE_INLINE.sub(_inline_replace, formatted)
            result_lines.append(formatted)
            continue

        # ---- Plain text with inline formatting ----
        formatted = _RE_INLINE.sub(_inline_replace, line)
        result_lines.append(formatted)

    result = "\n".join(result_lines)
    
    # Cache management
    if len(_md_cache) >= _MD_CACHE_MAX:
        # Evict oldest half (simple strategy)
        keys = list(_md_cache.keys())
        for k in keys[:len(keys) // 2]:
            del _md_cache[k]
    _md_cache[content_hash] = result
    
    return result
