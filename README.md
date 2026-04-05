<div align="center">

# MiniCode Python

### Terminal-native AI coding assistant — pure Python, zero dependencies

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Dependencies: 0](https://img.shields.io/badge/dependencies-0-f97316?style=for-the-badge)](pyproject.toml)
[![Tools: 30](https://img.shields.io/badge/tools-30-8b5cf6?style=for-the-badge)](#-built-in-tools)

A full-featured terminal coding assistant inspired by [Claude Code](https://docs.anthropic.com/en/docs/claude-code), rebuilt from scratch in **pure Python** with the standard library alone. Rich TUI, 30 built-in tools, session persistence, MCP integration, and more — all in ~15 000 lines of dependency-free code.

</div>

---

## Demo

```
╭────────────────────────────── MiniCode ───────────────────────────────╮
│ provider: anthropic    model: claude-sonnet-4    cwd: ~/my-project  │
╰───────────────────────────────────────────────────────────────────────╯

╭──────────────────────── session feed ── 6 events ─────────────────────╮
│ 👤 you                                                                │
│   帮我实现一个快速排序算法，加上单元测试                              │
│ · ─── ·                                                               │
│ 🤖 assistant                                                          │
│   我来为你实现快速排序，并编写完整的测试用例。                        │
│ · ─── ·                                                               │
│ 🔧 tool write_file ✔ ok                                               │
│   FILE: quicksort.py — Successfully wrote 42 lines                    │
│ · ─── ·                                                               │
│ 🔧 tool run_command ✔ ok                                              │
│   ✓ All 8 tests passed in 0.03s                                       │
╰───────────────────────────────────────────────────────────────────────╯

╭──────────────────────── prompt ────────────────────────────────────────╮
│ > _                                                                   │
╰───────────────────────────────────────────────────────────────────────╯
 tools on │ skills on │ /help for commands
```

---

## Features

### Core

- **Rich Terminal UI** — Alternate-screen TUI with panels, ANSI styling, smooth scrolling, and 60 FPS throttled rendering
- **Agent Loop** — Multi-turn tool-use loop that plans, executes, and iterates until the task is done
- **30 Built-in Tools** — File I/O, code search, shell execution, git, testing, code review, and more
- **Permission System** — Approve, deny, or auto-allow tool calls with configurable rules
- **Slash Commands** — `/help`, `/tools`, `/compact`, `/cost`, `/clear`, `/exit`, and more

### Advanced

- **Session Persistence** — Save & resume conversations across restarts (`--resume`)
- **3-Tier Memory** — Conversation → session → long-term memory for context retention
- **MCP Integration** — Connect external Model Context Protocol servers for extended capabilities
- **Skills System** — Drop-in skill files for domain-specific workflows
- **Sub-Agents** — Spawn lightweight agents for parallel sub-tasks
- **Auto Mode** — Automatically approve safe tool calls without human interaction
- **Hooks System** — Lifecycle event hooks for extensibility
- **Context Management** — Smart context window tracking to stay within token limits
- **Cost Tracking** — Real-time API cost estimation and display

### Performance

- **Per-entry Render Cache** — Transcript entries are cached and only re-rendered when their state changes
- **Throttled Screen Refresh** — Renders are coalesced at ~60 FPS to eliminate flicker and lag
- **Buffered I/O** — Full screen frames are built in memory and flushed in a single `write()` call
- **Terminal Size Caching** — `os.get_terminal_size()` results are cached with a 500 ms TTL

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python
```

### 2. Install

```bash
# Option A: interactive installer (recommended)
python -m minicode.main --install

# Option B: pip editable install
pip install -e .
```

The installer will walk you through setting your model name, API base URL, and auth token. Configuration is saved to `~/.mini-code/settings.json`.

### 3. Run

```bash
# If installed via pip
minicode-py

# Or run directly
python -m minicode.main
```

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_AUTH_TOKEN` | Auth token (alternative) | — |
| `ANTHROPIC_BASE_URL` | API base URL | `https://api.anthropic.com` |
| `ANTHROPIC_MODEL` / `MINI_CODE_MODEL` | Model name | — |
| `MINI_CODE_MAX_OUTPUT_TOKENS` | Max output tokens | Model default |
| `MINI_CODE_MODEL_MODE` | Set to `mock` for offline testing | — |

---

## Usage

### Slash commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/tools` | List all registered tools |
| `/cost` | Display current session cost |
| `/compact` | Compact conversation context |
| `/clear` | Clear transcript |
| `/exit` | Exit MiniCode |
| `/transcript-save <path>` | Save conversation to file |

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Enter` | Submit input |
| `Up` / `Down` | Input history |
| `Alt+Up` / `Alt+Down` | Scroll transcript by 1 line |
| `PageUp` / `PageDown` | Scroll transcript by 8 lines |
| `Ctrl+A` (empty input) | Jump to top of transcript |
| `Ctrl+E` (empty input) | Jump to bottom |
| `Ctrl+U` | Clear input line |
| `Ctrl+C` | Cancel current operation |
| `Escape` | Clear input |
| Mouse wheel | Scroll transcript |

### Sessions

```bash
# Resume the most recent session
python -m minicode.main --resume

# Resume a specific session
python -m minicode.main --resume <session-id>

# List all saved sessions
python -m minicode.main --list-sessions
```

Sessions auto-save every 30 seconds and on exit.

---

## Built-in Tools

### File Operations
| Tool | Description |
|---|---|
| `list_files` | List directory contents with glob patterns |
| `grep_files` | Regex search across files |
| `read_file` | Read file contents with line ranges |
| `write_file` | Create or overwrite files |
| `modify_file` | Find-and-replace edits |
| `edit_file` | Structured file editing |
| `patch_file` | Apply unified diff patches |

### Code Intelligence
| Tool | Description |
|---|---|
| `find_symbols` | AST-based symbol search (functions, classes) |
| `find_references` | Find all references to a symbol |
| `get_ast_info` | Inspect AST structure of a file |
| `multi_edit` | Cross-file batch refactoring |
| `code_review` | Automated code quality analysis |

### Execution & Testing
| Tool | Description |
|---|---|
| `run_command` | Execute shell commands with timeout |
| `run_with_debug` | Run with automatic error parsing & diagnostics |
| `test_runner` | Smart test discovery and execution |
| `api_tester` | HTTP API endpoint testing |

### Web & Search
| Tool | Description |
|---|---|
| `web_fetch` | Fetch and extract web page content |
| `web_search` | Web search via API |

### DevOps
| Tool | Description |
|---|---|
| `git` | Git workflow (status, diff, log, commit, etc.) |
| `docker_helper` | Docker & Docker Compose management |
| `db_explorer` | SQLite database exploration & queries |

### Visualization & Misc
| Tool | Description |
|---|---|
| `file_tree` | Visual directory tree |
| `diff_viewer` | Rich diff visualization |
| `notebook_edit` | Jupyter notebook cell editing |
| `todo_write` | Task list management |
| `ask_user` | Prompt user for clarification |
| `load_skill` | Load domain-specific skill files |
| `governance_audit` | Engineering governance compliance checks |

---

## Configuration

### Settings file

`~/.mini-code/settings.json`:

```json
{
  "model": "claude-sonnet-4-20250514",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "your-token-here"
  }
}
```

### MCP servers

Global: `~/.mini-code/mcp.json`  
Per-project: `.mcp.json` in project root

```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["path/to/server.js"],
      "env": {}
    }
  }
}
```

### Skills

Place `.md` skill files in your project's `.minicode/skills/` directory. Each skill file describes domain-specific workflows, tools, or conventions that the agent can load on demand via the `load_skill` tool.

### Permissions

Permissions are managed interactively via the TUI approval prompt. You can:
- **Allow once** — permit a single tool call
- **Allow always** — auto-approve this tool for the session
- **Deny** — reject the tool call

---

## Architecture

```
minicode/
├── main.py                 # Entry point & CLI arg parsing
├── tty_app.py              # TUI application loop & event handling
├── agent_loop.py           # Multi-turn agent execution loop
├── anthropic_adapter.py    # LLM API adapter (Anthropic-compatible)
├── tooling.py              # Tool protocol, registry & execution
├── permissions.py          # Permission management system
├── config.py               # Configuration loading & merging
├── session.py              # Session persistence & autosave
├── state.py                # Application state store
├── context_manager.py      # Token context window management
├── memory.py               # 3-tier memory system
├── cost_tracker.py         # API cost estimation
├── mcp.py                  # Model Context Protocol client
├── skills.py               # Skill file discovery
├── sub_agents.py           # Sub-agent spawning
├── auto_mode.py            # Auto-approval engine
├── hooks.py                # Lifecycle event hooks
├── prompt.py               # System prompt builder
├── tools/                  # 30 built-in tool implementations
│   ├── read_file.py
│   ├── write_file.py
│   ├── run_command.py
│   ├── git.py
│   ├── code_nav.py         # AST-based code intelligence
│   ├── test_runner.py
│   └── ...
└── tui/                    # Terminal UI components
    ├── chrome.py            # Panels, banners, status bar
    ├── transcript.py        # Cached transcript renderer
    ├── input.py             # Input prompt rendering
    ├── input_parser.py      # Raw key/mouse event parsing
    ├── markdown.py          # ANSI markdown renderer
    ├── screen.py            # Alternate screen management
    └── types.py             # TUI data types
```

**Key design principles:**

- **Zero dependencies** — Only Python 3.11+ standard library
- **Single-threaded TUI** — Non-blocking I/O with `select()`-based event loop
- **Functional rendering** — Pure functions produce ANSI strings; state is separate
- **Tool protocol** — Every tool is a simple dataclass with `name`, `description`, `params`, and an `execute` callable
- **Layered config** — Claude settings → global MiniCode settings → project settings → environment variables

---

## Development

```bash
# Clone the repo
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python

# Run tests
pip install -e ".[dev]"
pytest

# Run in mock mode (no API key needed)
MINI_CODE_MODEL_MODE=mock python -m minicode.main

# Run smoke tests
python smoke_test.py
```

### Project stats

| Metric | Value |
|---|---|
| Python files | 69 |
| Lines of code | ~15 000 |
| Built-in tools | 30 |
| External dependencies | 0 |

---

## Acknowledgments

- **[@LiuMengxuan04](https://github.com/LiuMengxuan04)** — Creator of [MiniCode](https://github.com/LiuMengxuan04/MiniCode) (TypeScript original), architecture reference
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Design patterns and architecture inspiration
- **All Contributors** — Everyone who contributed to the MiniCode ecosystem

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Made with ❤️ by [@QUSETIONS](https://github.com/QUSETIONS)**

*A lightweight terminal coding assistant for local development workflows.*

[⬆ Back to Top](#minicode-python)

</div>
