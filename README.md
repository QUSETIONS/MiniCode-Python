# MiniCode Python

> Python port of [MiniCode](https://github.com/LiuMengxuan04/MiniCode) with enhanced features
>
> **Version**: v0.5.0 | **Status**: Production Ready

A lightweight terminal coding assistant for local development workflows, implemented in Python.

---

## 🔗 Related Projects

| Version | Language | Repository | Maintainer |
|---------|----------|------------|------------|
| **Main** | TypeScript | [MiniCode](https://github.com/LiuMengxuan04/MiniCode) | [@LiuMengxuan04](https://github.com/LiuMengxuan04) |
| **Python** | Python | **This Repository** | [@QUSETIONS](https://github.com/QUSETIONS) |

> 💡 **Note**: This Python version is a companion implementation. Many features originated from the main TypeScript version, with additional enhancements developed independently.

---

## ✨ Features

### Core Capabilities
- ✅ **Agent Loop** - Multi-step tool execution with recovery
- ✅ **Tool System** - 10 built-in tools (1:1 aligned with TS version)
- ✅ **Permission Management** - Interactive approval UI with risk assessment
- ✅ **MCP Integration** - Dynamic tool loading over stdio
- ✅ **Skills System** - Local workflow discovery via `SKILL.md`
- ✅ **Configuration** - Multi-source config loading

### Advanced Features (Python Exclusive)
- 🌟 **Session Persistence** - Auto-save and resume across restarts
- 🌟 **Layered Memory** - User/Project/Local three-tier memory system
- 🌟 **Context Management** - Token tracking with auto-compaction
- 🌟 **Cost Tracking** - Detailed API usage and cost reporting
- 🌟 **Sub-Agents** - Explore/Plan/General specialized agents
- 🌟 **Auto Mode** - Intelligent permission auto-approval
- 🌟 **Hooks System** - Lifecycle event hooks for extensibility

### TUI & UX
- ✅ Full-screen terminal UI with Unicode borders
- ✅ ANSI input parsing (arrow keys, PageUp/Down, Ctrl combinations)
- ✅ Markdown rendering with syntax highlighting
- ✅ CJK/Emoji width support
- ✅ Transcript scrolling and history navigation
- ✅ Interactive permission approval UI

---

## 🚀 Quick Start

### Installation

```bash
# Clone this repository
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python

# Or use as a submodule from main repo
git clone --recurse-submodules https://github.com/LiuMengxuan04/MiniCode.git
cd MiniCode/py-src
```

### Run

```bash
# Interactive installer (first time)
python -m minicode.main --install

# Normal mode
python -m minicode.main

# Mock mode (no API key required, for testing)
export MINI_CODE_MODEL_MODE=mock
python -m minicode.main

# Resume previous session
python -m minicode.main --resume

# List saved sessions
python -m minicode.main --list-sessions
```

### Requirements

- Python 3.11+
- **Zero external dependencies** (stdlib only!)

---

## 📚 Documentation

- [Usage Guide](USAGE_GUIDE.md) - Complete user manual
- [Architecture Learning](CLAUDE_CODE_ARCHITECTURE_LEARNING.md) - Learn from Claude Code's design
- [Integration Guide](INTEGRATION_GUIDE.md) - How to use new features
- [New Features Report](NEW_FEATURES_REPORT.md) - What's new in v0.3.0
- [Completion Report](COMPLETION_REPORT.md) - v0.2.0 completion status
- [Final Audit Report](FINAL_AUDIT_REPORT.md) - Complete code audit

---

## 📊 Project Stats

| Metric | Value |
|--------|-------|
| **Code Lines** | ~10,000 |
| **Test Coverage** | 92 tests, 100% pass |
| **External Dependencies** | 0 |
| **Claude Code Alignment** | 93.5% |
| **Feature Completeness** | 98% |

---

## 🛠️ Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/status` | Show application state summary |
| `/cost` | Show API cost and usage report |
| `/context` | Show context window usage |
| `/tasks` | Show current task list |
| `/memory` | Show memory system status |
| `/tools` | List available tools |
| `/skills` | List discovered skills |
| `/mcp` | Show MCP server status |
| `/model` | Show/change current model |
| `/history` | Show recent history |
| `/exit` | Exit the application |

---

## 🏗️ Architecture

MiniCode Python follows Claude Code's core architecture patterns:

```
MiniCode Python Architecture
├── Store State Management (Zustand-style)
├── Tool Protocol (declarative lifecycle)
├── Polyorphic Commands (Prompt/Local/Interactive)
├── Async Context Collector (parallelized I/O)
├── Sub-Agent System (Explore/Plan/General)
├── Auto Mode (risk assessment engine)
└── Hooks System (lifecycle events)
```

See [CLAUDE_CODE_ARCHITECTURE_LEARNING.md](CLAUDE_CODE_ARCHITECTURE_LEARNING.md) for detailed analysis.

---

## 🧪 Development

```bash
# Run tests
python -m pytest tests/ -v

# Run integration tests
python test_integration.py

# Check code style
python -m py_compile minicode/*.py
```

### Project Structure

```
py-src/
├── minicode/
│   ├── agent_loop.py          # Core agent loop
│   ├── tooling.py             # Tool system + Protocol
│   ├── permissions.py         # Permission management
│   ├── mcp.py                 # MCP client
│   ├── skills.py              # Skill discovery
│   ├── config.py              # Configuration system
│   ├── state.py               # Store state management
│   ├── cost_tracker.py        # API cost tracking
│   ├── context_manager.py     # Context window management
│   ├── memory.py              # Layered memory system
│   ├── task_tracker.py        # Task tracking
│   ├── poly_commands.py       # Polyorphic commands
│   ├── async_context.py       # Async context collector
│   ├── sub_agents.py          # Sub-agent system
│   ├── auto_mode.py           # Auto mode engine
│   ├── hooks.py               # Hooks event system
│   ├── session.py             # Session persistence
│   ├── api_retry.py           # API retry mechanism
│   ├── install.py             # Interactive installer
│   ├── tty_app.py             # Main TUI application
│   └── tui/                   # Terminal UI components
├── tests/                     # Test suite (92 tests)
└── docs/                      # Documentation
```

---

## 📝 License

This project follows the same license as the main MiniCode repository.

---

## 🙏 Acknowledgments

- **[@LiuMengxuan04](https://github.com/LiuMengxuan04)** - Creator of MiniCode, architecture reference
- **Claude Code** - Design patterns and architecture inspiration (via leaked source analysis)
- All contributors to the MiniCode ecosystem

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Keep implementations lightweight and pragmatic
2. Align design with Claude Code's direction where possible
3. Write tests for new features
4. Follow existing code style (type hints, dataclasses, etc.)

See the main repository's [Contributing Guidelines](https://github.com/LiuMengxuan04/MiniCode/blob/main/CONTRIBUTING.md) for details.

---

**MiniCode Python** - A feature-complete, production-ready terminal coding assistant. 🚀
