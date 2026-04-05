# 🚀 MiniCode Python

> **A terminal coding assistant that writes, thinks, and engineers like Claude Code — but in pure Python with zero dependencies.**

<div align="center">

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)
[![Tests: 92 passed](https://img.shields.io/badge/tests-92%20passed-brightgreen.svg?style=for-the-badge)](https://github.com/QUSETIONS/MiniCode-Python)
[![Dependencies: 0](https://img.shields.io/badge/dependencies-0-orange.svg?style=for-the-badge)](https://github.com/QUSETIONS/MiniCode-Python)
[![Claude Code Alignment: 93.5%](https://img.shields.io/badge/claude%20code%20alignment-93.5%25-purple.svg?style=for-the-badge)](https://github.com/QUSETIONS/MiniCode-Python)
[![Version: 0.5.0](https://img.shields.io/badge/version-0.5.0-red.svg?style=for-the-badge)](https://github.com/QUSETIONS/MiniCode-Python)

</div>

---

## 🎬 Demo

```
╭────────────────────────────────────────────────────────────────────────╮
│ MiniCode                               │ provider: offline             │
│ Terminal coding assistant for MiniCode.                                │
│                                                                          │
│ minicode                  │ .../Desktop/project                        │
│ [provider] offline  [model] claude-sonnet-4  [msgs] 15  [events] 8    │
│ cwd: D:\Desktop\project                                               │
╰────────────────────────────────────────────────────────────────────────╯

╭──────────────────── session feed ──────────────────────────────────────╮
│ you                                                                    │
│   帮我实现一个快速排序算法                                             │
│ ·                                                                      │
│ assistant                                                              │
│   我来为你实现快速排序算法，并添加测试。                               │
│ ·                                                                      │
│ tool write_file ok                                                     │
│   FILE: sort.py                                                        │
│   Successfully wrote 45 lines                                          │
│ ·                                                                      │
│ tool run_command ok                                                    │
│   ✓ All 5 tests passed in 0.12s                                        │
╰────────────────────────────────────────────────────────────────────────╯

╭──────────────────── prompt ────────────────────────────────────────────╮
│ > 再帮我优化一下时间复杂度                                             │
╰────────────────────────────────────────────────────────────────────────╯

tools on | skills on | memory: 3 entries
```

---

## ✨ Why MiniCode Python?

| Feature | Claude Code | Other CLI Tools | **MiniCode Python** |
|---------|-------------|-----------------|---------------------|
| **Terminal-First UI** | ✅ | ❌ | ✅ |
| **Full Agent Loop** | ✅ | Partial | ✅ |
| **Tool System** | ~40 tools | ~5 tools | **30 tools** |
| **Permission System** | ✅ | ❌ | ✅ |
| **MCP Integration** | ✅ | ❌ | ✅ |
| **Skills System** | ✅ | ❌ | ✅ |
| **Session Persistence** | ❌ | ❌ | ✅ **Exclusive** |
| **Layered Memory** | Basic | ❌ | ✅ **3-Tier** |
| **Context Management** | ✅ | ❌ | ✅ |
| **Auto Mode** | ✅ | ❌ | ✅ |
| **Sub-Agents** | ✅ | ❌ | ✅ **Lightweight** |
| **Governance Rules** | ❌ | ❌ | ✅ **Built-in** |
| **External Dependencies** | npm | Varies | **0 (stdlib only!)** |
| **Startup Time** | ~2s | ~1s | **<1s** |
| **Language** | TypeScript | Various | **Python 3.11+** |

---

## 🧠 Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MiniCode Python v0.5.0                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Agent Loop  │──│ Tool System  │──│ Permission Manager   │  │
│  │  (Recovery)  │  │ (18 Tools)   │  │ (Interactive UI)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────────▼───────────┐  │
│  │ MCP Client   │──│ Skills Sys   │──│ Config System        │  │
│  │ (Dynamic)    │  │ (Discovery)  │  │ (Multi-Source)       │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────▼─────────────────▼──────────────────────▼───────────┐  │
│  │                    TUI Engine                             │  │
│  │  • Full-Screen Rendering  • ANSI Input Parser             │  │
│  │  • Unicode Borders        • CJK/Emoji Width Support       │  │
│  │  • Markdown Rendering       • Transcript Scrolling        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Advanced Features (Python Exclusive)          │  │
│  │  ┌────────────┐ ┌───────────┐ ┌──────────────────────┐   │  │
│  │  │ Session    │ │ Layered   │ │ Context Management   │   │  │
│  │  │ Persistence│ │ Memory    │ │ (Auto-Compaction)    │   │  │
│  │  └────────────┘ └───────────┘ └──────────────────────┘   │  │
│  │  ┌────────────┐ ┌───────────┐ ┌──────────────────────┐   │  │
│  │  │ Cost       │ │ Sub-      │ │ Auto Mode            │   │  │
│  │  │ Tracking   │ │ Agents    │ │ (Risk Assessment)    │   │  │
│  │  └────────────┘ └───────────┘ └──────────────────────┘   │  │
│  │  ┌────────────┐ ┌───────────┐ ┌──────────────────────┐   │  │
│  │  │ Governance │ │ Hooks     │ │ Task Tracking        │   │  │
│  │  │ Rules      │ │ System    │ │ (Auto-Detect)        │   │  │
│  │  └────────────┘ └───────────┘ └──────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tool Ecosystem (30 Tools)

<div align="center">

| Category | Tools | Count |
|----------|-------|-------|
| **📁 File Operations** | `read_file` `write_file` `edit_file` `patch_file` `modify_file` `list_files` `grep_files` | 7 |
| **🔍 Code Intelligence** | `find_symbols` `find_references` `get_ast_info` `multi_edit` `code_review` | 5 |
| **💻 Command Execution** | `run_command` `run_with_debug` | 2 |
| **🧪 Testing & Debugging** | `test_runner` | 1 |
| **🎨 Visualization** | `file_tree` `diff_viewer` | 2 |
| **🌐 Web & API** | `web_fetch` `web_search` `api_tester` | 3 |
| **🗄️ Database** | `db_explorer` (SQLite) | 1 |
| **🐳 Docker** | `docker_helper` (containers & compose) | 1 |
| **📋 Task Management** | `todo_write` | 1 |
| **🔧 Git Workflow** | `git` (status/diff/log/commit/review) | 1 |
| **📓 Notebook** | `notebook_edit` | 1 |
| **🏗️ Governance** | `governance_audit` | 1 |
| **🤖 User Interaction** | `ask_user` | 1 |
| **🧩 Skills** | `load_skill` | 1 |
| **🔌 MCP** | Dynamic (as configured) | ∞ |

</div>

---

## 🚀 Quick Start

### One-Line Install & Run

```bash
# Clone and run (no dependencies needed!)
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python
python -m minicode.main
```

### Interactive Setup

```bash
# First-time setup wizard
python -m minicode.main --install

# It will ask for:
# - Model name (e.g., claude-sonnet-4-20250514)
# - API base URL (default: https://api.anthropic.com)
# - Auth token (your API key)
```

### Test Mode (No API Key Required)

```bash
# Mock mode for testing UI and features
export MINI_CODE_MODEL_MODE=mock  # Linux/macOS
set MINI_CODE_MODEL_MODE=mock     # Windows
python -m minicode.main
```

### Session Management

```bash
# Resume last session
python -m minicode.main --resume

# List all sessions
python -m minicode.main --list-sessions

# Resume specific session
python -m minicode.main --resume <session-id>
```

---

## 📊 Project Stats

<div align="center">

| Metric | Value | Badge |
|--------|-------|-------|
| **Code Lines** | ~16,000 | 📝 |
| **Test Cases** | 92 (100% pass) | ✅ |
| **External Dependencies** | 0 | 🎯 |
| **Tools Available** | 30 | 🛠️ |
| **Slash Commands** | 20+ | ⌨️ |
| **Startup Time** | <1 second | ⚡ |
| **Memory Usage** | ~15MB | 💾 |
| **Claude Code Alignment** | 93.5% | 🎯 |
| **Python Version** | 3.11+ | 🐍 |

</div>

---

## 🎮 Slash Commands

Type `/` in the TUI to see all available commands:

| Command | Description | Category |
|---------|-------------|----------|
| `/help` | Show all available commands | 📖 Help |
| `/status` | Application state summary | 📊 Status |
| `/cost` | API cost and usage report | 💰 Cost |
| `/context` | Context window usage | 🧠 Context |
| `/tasks` | Current task list | ✅ Tasks |
| `/memory` | Memory system status | 🧩 Memory |
| `/tools` | List all available tools | 🛠️ Tools |
| `/skills` | List discovered skills | 🎯 Skills |
| `/mcp` | MCP server status | 🔌 MCP |
| `/model` | Show/change model | ⚙️ Config |
| `/history` | Recent input history | 📜 History |
| `/permissions` | Permission storage path | 🔒 Security |
| `/config-paths` | Config file locations | ⚙️ Config |
| `/exit` | Exit application | 🚪 Exit |

---

## 🏗️ Architecture Deep Dive

### State Management (Zustand-Style)

```python
from minicode.state import create_app_store, set_busy, set_idle

# Create store
app_state = create_app_store({"model": "claude-sonnet-4"})

# Subscribe to changes
def on_change(new_state, old_state):
    print(f"State changed: {old_state.is_busy} → {new_state.is_busy}")

app_state.subscribe(on_change)

# Update state
app_state.set_state(set_busy("read_file"))
# → "State changed: False → True"
```

### Engineering Governance (Built-in)

Every code generation automatically follows:

```
Iron Laws (8):
1. Theory first          5. Audit loop
2. Requirements first    6. Single sink (business/src/ = 1)
3. 1:1 binding           7. One-way dependencies (zero cycles)
4. Design-driven         8. No skipping phases

Package Structure:
my_package/
├── port/
│   ├── port_entry/      # Entry points (can import anything)
│   └── port_exit/       # Exit points (export interface)
├── wrap/
│   ├── src/             # External library adapters
│   └── config/          # Adapter configuration (zero deps)
├── business/
│   ├── src/             # Business logic (CORE - exactly 1 sink)
│   └── config/          # Business configuration (zero deps)
├── test/
│   ├── src/             # Test code
│   └── config/          # Test configuration (zero deps)
└── docs/
    ├── requirements/    # User scenarios (pure, no implementation)
    ├── knowledge/       # Business rules & constraints (1:1 with requirements)
    └── design/          # Technical design (maps to code structure)

Dependency Flow:
vendor/ → port_entry → wrap/src → business/src → port_exit
              ↑                      ↑
         (external libs)      (business config last)

Audit Checklist (Auto-Executed):
✓ Audit 0: Knowledge ↔ Requirements 1:1
✓ Audit 1: Design ← Requirements + Knowledge coverage
✓ Audit 2: Code ← Design isomorphism + Dependency compliance
✓ Audit 3: business/src/ single sink + Package DAG
```

Use the `governance_audit` tool to check your code:

```python
# AI automatically runs this after code changes
governance_audit(action="full", path="my_package")

# Output:
# Governance Audit Result
# ==================================================
# ✓ PASSED - All governance rules satisfied
# 
# Dependencies: 12 edges
# Sink files:
#   business_src: 1 sink
#     - src/service.py
```

### Session Persistence

```python
# Sessions are auto-saved every 30 seconds
~/.mini-code/
├── sessions/
│   ├── abc123.json    # Full session data
│   └── def456.json
└── sessions_index.json # Session metadata
```

---

## 🔗 Related Projects

| Version | Language | Repository | Maintainer |
|---------|----------|------------|------------|
| **Main** | TypeScript | [MiniCode](https://github.com/LiuMengxuan04/MiniCode) | [@LiuMengxuan04](https://github.com/LiuMengxuan04) |
| **Python** | Python | **[This Repository](https://github.com/QUSETIONS/MiniCode-Python)** | **[@QUSETIONS](https://github.com/QUSETIONS)** |

> 💡 **Note**: This Python version is a companion implementation. Many features originated from the main TypeScript version, with additional exclusive features developed independently.

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Usage Guide](USAGE_GUIDE.md) | Complete user manual with examples |
| [Architecture Learning](CLAUDE_CODE_ARCHITECTURE_LEARNING.md) | Learn from Claude Code's design patterns |
| [Integration Guide](INTEGRATION_GUIDE.md) | How to use new features |
| [Features Report](NEW_FEATURES_REPORT.md) | What's new in v0.3.0+ |
| [Completion Report](COMPLETION_REPORT.md) | v0.2.0 completion status |
| [Audit Report](FINAL_AUDIT_REPORT.md) | Complete code audit results |
| [Progress Report](PROGRESS_REPORT.md) | Development progress tracking |

---

## 🧪 Development

```bash
# Run all tests
python -m pytest tests/ -v

# Run integration tests
python test_integration.py

# Run specific test file
python -m pytest tests/test_agent_loop.py -v

# Check code compilation
python -m py_compile minicode/*.py
```

### Project Structure

```
MiniCode-Python/
├── minicode/
│   ├── agent_loop.py          # 🔄 Core agent loop with recovery
│   ├── tooling.py             # 🛠️ Tool system + Protocol
│   ├── permissions.py         # 🔒 Permission management
│   ├── mcp.py                 # 🔌 MCP client
│   ├── skills.py              # 🎯 Skill discovery
│   ├── config.py              # ⚙️ Configuration system
│   ├── state.py               # 📊 Store state management
│   ├── cost_tracker.py        # 💰 API cost tracking
│   ├── context_manager.py     # 🧠 Context window management
│   ├── memory.py              # 🧩 Layered memory system
│   ├── task_tracker.py        # ✅ Task tracking
│   ├── poly_commands.py       # ⌨️ Polyorphic commands
│   ├── async_context.py       # ⚡ Async context collector
│   ├── sub_agents.py          # 🤖 Sub-agent system
│   ├── auto_mode.py           # 🔄 Auto mode engine
│   ├── hooks.py               # 🔗 Hooks event system
│   ├── session.py             # 💾 Session persistence
│   ├── api_retry.py           # 🔁 API retry mechanism
│   ├── install.py             # 📦 Interactive installer
│   ├── prompt.py              # 📝 System prompt builder
│   ├── tty_app.py             # 🖥️ Main TUI application
│   ├── tools/                 # 🛠️ 30 built-in tools
│   │   ├── code_nav.py            # 🔍 Code intelligence (AST analysis)
│   │   ├── code_review.py         # 📝 Automated code quality checks
│   │   ├── multi_edit.py          # ✏️ Cross-file refactoring
│   │   ├── file_tree.py           # 🌳 Visual file browser
│   │   ├── diff_viewer.py         # 🔀 Diff visualization
│   │   ├── run_with_debug.py      # 🐛 Error parsing & diagnostics
│   │   ├── test_runner.py         # 🧪 Smart test discovery
│   │   ├── api_tester.py          # 🌐 HTTP API testing
│   │   ├── db_explorer.py         # 🗄️ SQLite database explorer
│   │   ├── docker_helper.py       # 🐳 Docker & Compose manager
│   │   ├── git.py                 # 🔧 Git workflow tools
│   │   ├── governance_audit.py    # 🏗️ Governance compliance
│   │   └── ... (18 more tools)
│   └── tui/                   # 🎨 Terminal UI components
├── tests/                     # 🧪 92 test cases
└── docs/                      # 📚 Documentation
```

---

## 🏆 Key Achievements

<div align="center">

| Achievement | Description | Icon |
|-------------|-------------|------|
| **Zero Dependencies** | Pure Python standard library only | 🎯 |
| **93.5% Claude Code Alignment** | Architecturally aligned | 🎯 |
| **100% Test Pass Rate** | 92 tests, zero failures | ✅ |
| **Session Persistence** | Exclusive feature not in TS version | 💾 |
| **Layered Memory** | 3-tier memory system | 🧩 |
| **Governance Rules** | Built-in engineering standards | 🏗️ |
| **Sub-Agents** | Lightweight specialized agents | 🤖 |
| **Auto Mode** | Intelligent permission handling | 🔄 |
| **Hooks System** | Lifecycle event extensibility | 🔗 |

</div>

---

## 🙏 Acknowledgments

- **[@LiuMengxuan04](https://github.com/LiuMengxuan04)** — Creator of MiniCode, architecture reference
- **Claude Code** — Design patterns and architecture inspiration
- **All Contributors** — Everyone who contributed to the MiniCode ecosystem

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with ❤️ by [@QUSETIONS](https://github.com/QUSETIONS)**

*A lightweight terminal coding assistant for local development workflows.*

[⬆ Back to Top](#-minicode-python)

</div>
