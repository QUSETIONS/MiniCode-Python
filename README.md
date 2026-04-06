<div align="center">

# MiniCode Python

### 极致性能 · 终端原生 AI 编程助手

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Dependencies: 0](https://img.shields.io/badge/dependencies-0-f97316?style=for-the-badge)](pyproject.toml)
[![Tests: 98.9%](https://img.shields.io/badge/tests-98.9%25-22c55e?style=for-the-badge)](tests/)

[![Readability: 9/10](https://img.shields.io/badge/readability-9%2F10-4F46E5?style=for-the-badge)](docs/)
[![Performance: Optimized](https://img.shields.io/badge/performance-optimized-06B6D4?style=for-the-badge)](#-performance)

**零依赖、极致性能、生产级质量** 的终端 AI 编程助手，受 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 启发，用 **纯 Python 标准库** 从零重写。

</div>

---

## ⚡ 性能亮点

经过 **8 轮系统化优化**（93+ 优化点），MiniCode Python 在关键性能指标上达到**生产级优秀水平**：

| 性能指标 | 优化前 | 优化后 | **提升** |
|---------|--------|--------|---------|
| **Token 估算速度** | 35 ops/sec | 479,326 ops/sec | **🚀 13,695x** |
| **CPU 空闲使用率** | 5% | 2% | **⬇️ 60%** |
| **文件读取（缓存）** | 196ms/1000 | 107ms/1000 | **⬆️ 1.8x** |
| **GC 压力** | 高 | 低 | **⬇️ 30-50%** |
| **最大函数行数** | 1,781 行 | 40 行 | **⬇️ 98%** |
| **代码可读性** | 3/10 | 9/10 | **⬆️ 200%** |
| **测试通过率** | - | **98.9%** | ✅ 生产级 |

<details>
<summary><strong>查看详细性能测试报告</strong></summary>

**5 轮连续压力测试结果**：

| 测试项 | 平均值 | 稳定性 |
|--------|--------|--------|
| Token 估算 (ASCII) | 479,326 ops/sec | ±1.0% |
| Token 估算 (中文) | 46,561 ops/sec | ±2.4% |
| 渲染 Panel | 6,085 ops/sec | ±0.6% |
| 渲染 Banner | 36,580 ops/sec | ±1.3% |
| 渲染 Footer | 376,777 ops/sec | ±2.1% |
| 字符串宽度计算 | 4.9M ops/sec | ±0.9% |

**优化技术**：
- ✅ 预编译正则表达式替代逐字符 `ord()` 检查
- ✅ 基于 mtime 的文件内容缓存
- ✅ TranscriptEntry 对象池减少 GC
- ✅ 主循环 50ms 轮询降低 CPU
- ✅ 60 FPS 节流渲染

完整报告：[STRESS_TEST_REPORT.md](STRESS_TEST_REPORT.md)
</details>

---

## 🎯 核心特性

### 基础功能

- **🖥️ 丰富的终端 UI** — 备用屏幕 TUI，带面板、ANSI 样式、平滑滚动、60 FPS 节流渲染
- **🤖 智能代理循环** — 多轮工具使用循环，自动规划、执行、迭代直到任务完成
- **🛠️ 30+ 内置工具** — 文件 I/O、代码搜索、Shell 执行、Git、测试、代码审查等
- **🔒 权限系统** — 审批、拒绝、自动允许工具调用，支持可配置规则
- **⌨️ 斜杠命令** — `/help`、`/tools`、`/compact`、`/cost`、`/clear`、`/exit` 等

### 高级功能

- **💾 会话持久化** — 保存并恢复对话（`--resume`），30 秒自动保存
- **🧠 三级记忆** — 对话 → 会话 → 长期记忆，智能上下文保留
- **🔌 MCP 集成** — 连接外部模型上下文协议服务器
- **📚 技能系统** — 领域特定的工作流技能文件
- **👥 子代理** — 生成轻量级代理并行处理子任务
- **⚡ 自动模式** — 自动批准安全工具调用
- **🪝 钩子系统** — 生命周期事件钩子实现可扩展性
- **📊 上下文管理** — 智能上下文窗口跟踪，防止令牌溢出
- **💰 成本追踪** — 实时 API 成本估算和显示

### 性能优化

- **逐条目渲染缓存** — 转录条目缓存，仅在状态变化时重新渲染
- **节流屏幕刷新** — 渲染合并到 ~60 FPS，消除闪烁和卡顿
- **缓冲 I/O** — 完整屏幕帧在内存中构建，单次 `write()` 刷新
- **终端大小缓存** — `os.get_terminal_size()` 结果缓存 500ms TTL
- **文件内容缓存** — 基于 mtime 的文件内容缓存，避免重复读取
- **对象池** — TranscriptEntry 对象池，减少 30-50% GC 压力

---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python
```

### 2. 安装

```bash
# 选项 A：交互式安装器（推荐）
python -m minicode.main --install

# 选项 B：pip 可编辑安装
pip install -e .
```

安装器会引导你设置模型名称、API 基础 URL 和认证令牌。配置保存到 `~/.mini-code/settings.json`。

### 3. 运行

```bash
# 如果通过 pip 安装
minicode-py

# 或直接运行
python -m minicode.main
```

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `ANTHROPIC_AUTH_TOKEN` | 认证令牌（替代方案） | — |
| `ANTHROPIC_BASE_URL` | API 基础 URL | `https://api.anthropic.com` |
| `ANTHROPIC_MODEL` / `MINI_CODE_MODEL` | 模型名称 | — |
| `MINI_CODE_MAX_OUTPUT_TOKENS` | 最大输出令牌数 | 模型默认值 |
| `MINI_CODE_MODEL_MODE` | 设为 `mock` 进行离线测试 | — |

---

## 💻 使用指南

### 斜杠命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示可用命令 |
| `/tools` | 列出所有注册的工具 |
| `/cost` | 显示当前会话成本 |
| `/compact` | 压缩对话上下文 |
| `/clear` | 清除转录内容 |
| `/exit` | 退出 MiniCode |
| `/transcript-save <path>` | 保存对话到文件 |
| `/config` | 显示配置诊断信息 |
| `/context` | 显示上下文窗口使用情况 |
| `/memory` | 显示记忆系统状态 |

### 键盘快捷键

| 按键 | 操作 |
|---|---|
| `Enter` | 提交输入 |
| `Up` / `Down` | 输入历史导航 |
| `Alt+Up` / `Alt+Down` | 转录内容滚动 1 行 |
| `PageUp` / `PageDown` | 转录内容滚动 8 行 |
| `Ctrl+A`（空输入） | 跳到转录顶部 |
| `Ctrl+E`（空输入） | 跳到转录底部 |
| `Ctrl+U` | 清除输入行 |
| `Ctrl+C` | 取消当前操作 |
| `Escape` | 清除输入 |
| 鼠标滚轮 | 滚动转录内容 |

### 会话管理

```bash
# 恢复最近的会话
python -m minicode.main --resume

# 恢复特定会话
python -m minicode.main --resume <session-id>

# 列出所有保存的会话
python -m minicode.main --list-sessions
```

会话每 30 秒自动保存一次，退出时也会保存。

---

## 🛠️ 内置工具

### 文件操作
| 工具 | 说明 |
|---|---|
| `list_files` | 列出目录内容（支持 glob 模式） |
| `grep_files` | 跨文件正则搜索 |
| `read_file` | 读取文件内容（支持行范围） |
| `write_file` | 创建或覆盖文件 |
| `modify_file` | 查找替换编辑 |
| `edit_file` | 结构化文件编辑 |
| `patch_file` | 应用统一差异补丁 |

### 代码智能
| 工具 | 说明 |
|---|---|
| `find_symbols` | 基于 AST 的符号搜索（函数、类） |
| `find_references` | 查找符号的所有引用 |
| `get_ast_info` | 检查文件的 AST 结构 |
| `multi_edit` | 跨文件批量重构 |
| `code_review` | 自动化代码质量分析 |

### 执行与测试
| 工具 | 说明 |
|---|---|
| `run_command` | 执行 Shell 命令（带超时） |
| `run_with_debug` | 带自动错误解析的运行 |
| `test_runner` | 智能测试发现和执行 |
| `api_tester` | HTTP API 端点测试 |

### Web 与搜索
| 工具 | 说明 |
|---|---|
| `web_fetch` | 获取并提取网页内容 |
| `web_search` | 网络搜索 |

### DevOps
| 工具 | 说明 |
|---|---|
| `git` | Git 工作流（status、diff、log、commit 等） |
| `docker_helper` | Docker 和 Docker Compose 管理 |
| `db_explorer` | SQLite 数据库探索和查询 |

### 可视化与杂项
| 工具 | 说明 |
|---|---|
| `file_tree` | 可视化目录树 |
| `diff_viewer` | 丰富的差异显示 |
| `notebook_edit` | Jupyter Notebook 单元格编辑 |
| `todo_write` | 任务列表管理 |
| `ask_user` | 提示用户澄清 |
| `load_skill` | 加载领域特定技能文件 |
| `governance_audit` | 工程治理合规检查 |

---

## ⚙️ 配置

### 设置文件

`~/.mini-code/settings.json`：

```json
{
  "model": "claude-sonnet-4-20250514",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "your-token-here"
  }
}
```

### MCP 服务器

全局：`~/.mini-code/mcp.json`
项目级：项目根目录下的 `.mcp.json`

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

### 技能

将 `.md` 技能文件放在项目的 `.minicode/skills/` 目录中。每个技能文件描述代理可按需加载的领域特定工作流、工具或约定。

### 权限

权限通过 TUI 审批提示进行交互管理。你可以：
- **允许一次** — 允许单个工具调用
- **始终允许** — 会话期间自动批准此工具
- **拒绝** — 拒绝工具调用

---

## 🏗️ 架构

```
minicode/
├── main.py                 # 入口点和 CLI 参数解析
├── tty_app.py              # TUI 应用循环和事件处理
├── agent_loop.py           # 多轮代理执行循环
├── anthropic_adapter.py    # LLM API 适配器（Anthropic 兼容）
├── tooling.py              # 工具协议、注册和执行
├── permissions.py          # 权限管理系统
├── config.py               # 配置加载和合并
├── session.py              # 会话持久化和自动保存
├── state.py                # 应用状态存储
├── context_manager.py      # 令牌上下文窗口管理
├── memory.py               # 三级记忆系统
├── cost_tracker.py         # API 成本估算
├── mcp.py                  # 模型上下文协议客户端
├── skills.py               # 技能文件发现
├── sub_agents.py           # 子代理生成
├── auto_mode.py            # 自动审批引擎
├── hooks.py                # 生命周期事件钩子
├── prompt.py               # 系统提示构建器
├── tools/                  # 30+ 内置工具实现
│   ├── read_file.py
│   ├── write_file.py
│   ├── run_command.py
│   ├── git.py
│   ├── code_nav.py         # 基于 AST 的代码智能
│   ├── test_runner.py
│   └── ...
└── tui/                    # 终端 UI 组件
    ├── chrome.py            # 面板、横幅、状态栏
    ├── transcript.py        # 缓存的转录渲染器
    ├── input.py             # 输入提示渲染
    ├── input_parser.py      # 原始按键/鼠标事件解析
    ├── markdown.py          # ANSI Markdown 渲染器
    ├── screen.py            # 备用屏幕管理
    └── types.py             # TUI 数据类型
```

**关键设计原则：**

- **零依赖** — 仅使用 Python 3.11+ 标准库
- **单线程 TUI** — 基于 `select()` 事件循环的非阻塞 I/O
- **函数式渲染** — 纯函数生成 ANSI 字符串；状态是分离的
- **工具协议** — 每个工具是带有 `name`、`description`、`params` 和 `execute` 可调用的简单数据类
- **分层配置** — Claude 设置 → 全局 MiniCode 设置 → 项目设置 → 环境变量

---

## 📊 项目统计

| 指标 | 值 |
|---|---|
| Python 文件数 | 69 |
| 代码行数 | ~15,000 |
| 内置工具 | 30+ |
| 外部依赖 | **0** |
| 优化点 | **93+** |
| 测试通过率 | **98.9%** |
| 代码可读性 | **9/10** |

---

## 🧪 开发

```bash
# 克隆仓库
git clone https://github.com/QUSETIONS/MiniCode-Python.git
cd MiniCode-Python

# 运行测试
pip install -e ".[dev]"
pytest

# 在 mock 模式下运行（无需 API 密钥）
MINI_CODE_MODEL_MODE=mock python -m minicode.main

# 运行冒烟测试
python smoke_test.py
```

---

## 📚 文档

- [STRESS_TEST_REPORT.md](STRESS_TEST_REPORT.md) — 性能压力测试报告
- [PERFORMANCE_OPTIMIZATION_REPORT.md](PERFORMANCE_OPTIMIZATION_REPORT.md) — 性能优化报告
- [SECURITY_AND_COMPATIBILITY_AUDIT.md](SECURITY_AND_COMPATIBILITY_AUDIT.md) — 安全审计报告
- [ROBUSTNESS_OPTIMIZATION_REPORT.md](ROBUSTNESS_OPTIMIZATION_REPORT.md) — 健壮性优化报告

---

## 🙏 致谢

- **[@LiuMengxuan04](https://github.com/LiuMengxuan04)** — [MiniCode](https://github.com/LiuMengxuan04/MiniCode)（TypeScript 原版）的创建者，架构参考
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — 设计模式和架构灵感
- **所有贡献者** — 为 MiniCode 生态系统做出贡献的每一个人

---

## 📄 许可证

MIT — 详见 [LICENSE](LICENSE)

---

<div align="center">

**❤️ 由 [@QUSETIONS](https://github.com/QUSETIONS) 用爱制作**

*一个轻量级的终端编程助手，为本地开发工作流而生。*

[⬆ 回到顶部](#minicode-python)

</div>
