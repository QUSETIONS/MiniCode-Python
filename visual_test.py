"""Visual test — render each TUI component to verify the enhanced aesthetics."""
import sys
sys.path.insert(0, ".")

from minicode.tui.chrome import (
    render_banner, render_footer_bar, render_panel, render_slash_menu,
    render_tool_panel, render_status_line, render_permission_prompt,
)
from minicode.tui.transcript import render_transcript
from minicode.tui.input import render_input_prompt
from minicode.tui.markdown import render_markdownish
from minicode.tui.types import TranscriptEntry


print("=" * 60)
print("  VISUAL TEST — Enhanced TUI Components")
print("=" * 60)
print()

# 1. Banner
print(">>> BANNER:")
banner = render_banner(
    {"model": "claude-sonnet-4-20250514", "baseUrl": "https://api.anthropic.com/v1"},
    "/home/user/my-project",
    ["read: cwd only", "write: ask", "exec: ask"],
    {"messageCount": 12, "transcriptCount": 8, "skillCount": 5, "mcpCount": 2},
)
print(banner)
print()

# 2. Transcript with entries
print(">>> TRANSCRIPT:")
entries = [
    TranscriptEntry(id=1, kind="user", body="Fix the login bug in auth.py"),
    TranscriptEntry(id=2, kind="assistant", body="I'll look at the auth module and fix the login issue.\n\n**Key changes:**\n1. Fixed token validation\n2. Added error handling\n\n```python\ndef login(user, pwd):\n    token = validate(user, pwd)\n    return token\n```"),
    TranscriptEntry(id=3, kind="tool", body="File edited successfully", toolName="edit_file", status="success", collapsed=True, collapsedSummary="auth.py +5 -2"),
    TranscriptEntry(id=4, kind="tool", body="Running tests...", toolName="run_command", status="running"),
    TranscriptEntry(id=5, kind="progress", body="Waiting for test results..."),
]
transcript = render_transcript(entries, 0, 30)
transcript_panel = render_panel("session feed", transcript, right_title="5 events")
print(transcript_panel)
print()

# 3. Input prompt
print(">>> INPUT PROMPT:")
prompt = render_input_prompt("Fix the bug in", 14)
prompt_panel = render_panel("prompt", prompt)
print(prompt_panel)
print()

# 4. Footer
print(">>> FOOTER:")
footer = render_footer_bar("Thinking...", True, True, [{"status": "running", "label": "bg-task"}])
print(footer)
print()

# 5. Tool panel
print(">>> TOOL PANEL:")
tool = render_tool_panel("read_file", [
    {"name": "list_files", "status": "success"},
    {"name": "grep", "status": "success"},
    {"name": "write_file", "status": "error"},
])
activity = render_panel("activity", tool)
print(activity)
print()

# 6. Status line
print(">>> STATUS LINES:")
print(render_status_line(None))
print(render_status_line("Generating response..."))
print()

# 7. Slash menu
print(">>> SLASH MENU:")
class FakeCmd:
    def __init__(self, usage, description):
        self.usage = usage
        self.description = description
cmds = [
    FakeCmd("/help", "Show available commands"),
    FakeCmd("/clear", "Clear the current session"),
    FakeCmd("/save", "Save transcript to file"),
    FakeCmd("/exit", "Exit MiniCode"),
]
menu = render_slash_menu(cmds, 1)
print(menu)
print()

# 8. Markdown rendering
print(">>> MARKDOWN:")
md = render_markdownish("""# Main Title
## Subtitle
### Section

This is *italic* and **bold** text with `inline code`.

> This is a blockquote
> with multiple lines

- First bullet
- Second bullet
  - Nested bullet

1. First item
2. Second item

```python
def hello():
    print("world")
```

---

| Name | Value |
|------|-------|
| foo  | bar   |
| baz  | qux   |
""")
print(md)
print()

# 9. Permission prompt
print(">>> PERMISSION PROMPT:")
perm = render_permission_prompt(
    {
        "summary": "edit_file wants to modify auth.py",
        "kind": "edit",
        "details": ["--- a/auth.py", "+++ b/auth.py", "@@ -1,3 +1,5 @@"],
        "choices": [
            {"label": "Allow", "key": "y"},
            {"label": "Deny", "key": "n"},
            {"label": "Always allow", "key": "a"},
        ],
    },
    selected_choice_index=0,
)
print(perm)

print()
print("=" * 60)
print("  ALL VISUAL TESTS RENDERED SUCCESSFULLY")
print("=" * 60)
