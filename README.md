# MiniCode Python

> Python implementation of the [MiniCode](https://github.com/LiuMengxuan04/MiniCode) ecosystem.

## MiniCode Ecosystem

- Main repository: [LiuMengxuan04/MiniCode](https://github.com/LiuMengxuan04/MiniCode)
- Python version: [QUSETIONS/MiniCode-Python](https://github.com/QUSETIONS/MiniCode-Python)
- Rust version: [harkerhand/MiniCode-rs](https://github.com/harkerhand/MiniCode-rs)
- Submodule sync guide: [docs/SUBMODULE_SYNC.md](docs/SUBMODULE_SYNC.md)

## Project Positioning

This repository is the Python version of MiniCode, maintained as a language-specific subproject in the broader MiniCode ecosystem.

If you came here from the main MiniCode repository, the important thing to know is:

- the main repository syncs a submodule commit
- it does not automatically mirror the full live state of this repository
- so the submodule pointer in the main repo may lag behind the latest changes here

In other words, what gets synced upstream is a specific commit, not the whole repository state. If the main repo has not updated its submodule pointer yet, the content shown there can be older than what you see here.

For the exact maintainer workflow, see [docs/SUBMODULE_SYNC.md](docs/SUBMODULE_SYNC.md).

## Related Repositories

| Repository | Role |
| --- | --- |
| [MiniCode](https://github.com/LiuMengxuan04/MiniCode) | Main project entry and ecosystem hub |
| [MiniCode-Python](https://github.com/QUSETIONS/MiniCode-Python) | Python implementation |
| [MiniCode-rs](https://github.com/harkerhand/MiniCode-rs) | Rust implementation |

## What This Repository Provides

MiniCode Python is a terminal AI coding assistant implemented in Python, focused on:

- terminal-first coding workflows
- tool calling and agent loop execution
- TUI-based interactive experience
- session persistence and recovery
- permission-gated local execution
- MCP integration

## Current Status

This repository is an actively developed Python implementation, not just a mirror of the main repository.

It includes ongoing work in areas such as:

- Python-side feature parity with the main MiniCode experience
- TUI architecture cleanup
- transcript and rendering performance improvements
- MCP and tool execution improvements
- session, context, and memory handling

## Quick Start

```bash
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python
python -m minicode.main --install
```

Run directly:

```bash
python -m minicode.main
```

## Configuration

Configure your model in `~/.mini-code/settings.json`:

```json
{
  "model": "claude-sonnet-4-20250514",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "your-token-here"
  }
}
```

## Development

Install dev dependencies and run tests:

```bash
pip install -e ".[dev]"
pytest
```

Mock mode:

```bash
MINI_CODE_MODEL_MODE=mock python -m minicode.main
```

## Sync Note For Main Repository Maintainers

If this repository is consumed as a submodule from the main MiniCode repository:

1. update the submodule pointer in the main repository
2. commit that submodule pointer update upstream
3. do not assume new commits here are automatically reflected there

This distinction matters for README visibility, feature status, and release communication.

## Acknowledgments

- MiniCode main project: [LiuMengxuan04/MiniCode](https://github.com/LiuMengxuan04/MiniCode)
- Rust implementation: [harkerhand/MiniCode-rs](https://github.com/harkerhand/MiniCode-rs)
