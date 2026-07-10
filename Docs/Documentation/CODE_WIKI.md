# MiniCode 代码百科 (CODE_WIKI)

> MiniCode —— 轻量、开源、多语言实现的 AI 编码代理（Agent），灵感源自 Claude Code。

> ⚠️ **部分内容过时（2026-06-16）**：本文档的部分目录树与模块清单描述的是早期 `py-src/minicode/` 镜像，该镜像及其 `gateway.py`/`protocol.py`/`safe_execution.py`/`cron_runner.py`/`agent_protocol.py`/`context_isolation.py` 已在产品化中移除。**当前规范实现是仓库根目录的 `minicode/` 包，准确结构见 [`STRUCTURE.md`](STRUCTURE.md)。** 本文档保留作历史参考，不再逐行同步。
>
> `ts-src/`、`MiniCode-fork/`、`MiniCode-main-work/` 等比较材料的当前保留/退休边界以 [`engineering/material-inventory.json`](engineering/material-inventory.json) 和 `engineering/material-burndown/` 为准；本文中的相关路径只作为历史参考索引。

---

## 1. 项目概述 (Project Overview)

### 1.1 项目定位

**MiniCode** 是一个开源的 AI 编码代理（AI Coding Agent），能够在终端中与开发者进行交互式的对话式编程。它支持多种 LLM 后端（Anthropic Claude、OpenAI 兼容模型等），能够理解代码库、执行文件操作、运行命令、搜索代码，并通过工具调用（Tool Use）完成实际开发任务。

### 1.2 核心目标

- **轻量级**：最小化依赖，快速启动，适合日常开发
- **多语言实现**：同时提供 TypeScript 和 Python 两种实现版本，方便不同技术栈的开发者理解和贡献
- **开源替代**：作为 Claude Code 模式的开源参考实现，展示 AI 编码代理的完整架构
- **可扩展**：通过 Skills、MCP Server、Hooks 等机制支持功能扩展

### 1.3 适用场景

- 交互式终端编码助手（TTY/TUI 模式）
- 无头自动化模式（Headless / Auto Mode）
- 代码审查、文件修改、命令执行
- 多 Agent 协调与子任务分解

---

## 2. 整体架构 (Overall Architecture)

### 2.1 高层架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户终端 (TTY/TUI)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │  Input   │  │  Screen  │  │Markdown  │  │ Transcript │  │
│  │ Handler  │  │Renderer  │  │ Renderer │  │  Panel     │  │
│  └────┬─────┘  └──────────┘  └──────────┘  └────────────┘  │
│       │                                                      │
└───────┼──────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                     Agent Loop (核心引擎)                     │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ Prompt       │───▶│ Model        │───▶│ Tool          │  │
│  │ Pipeline     │    │ Adapter      │    │ Registry      │  │
│  └──────────────┘    └──────┬───────┘    └───────┬───────┘  │
│                             │                    │          │
│  ┌──────────────┐    ┌──────▼───────┐    ┌───────▼───────┐  │
│  │ Context      │◀───│ Message      │◀───│ Tool          │  │
│  │ Manager      │    │ History      │    │ Execution     │  │
│  └──────────────┘    └──────────────┘    └───────────────┘  │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ Permissions  │    │ Skills       │    │ MCP Server    │  │
│  │ Manager      │    │ System       │    │ Connector     │  │
│  └──────────────┘    └──────────────┘    └───────────────┘  │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ Memory       │    │ Session      │    │ State         │  │
│  │ System       │    │ Manager      │    │ Manager       │  │
│  └──────────────┘    └──────────────┘    └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
        │                         │                    │
        ▼                         ▼                    ▼
┌───────────────┐       ┌───────────────┐     ┌──────────────┐
│ LLM API       │       │ Local File    │     │ External     │
│ (Claude/      │       │ System &      │     │ MCP Servers  │
│  OpenAI/ etc) │       │ Shell         │     │ & Services   │
└───────────────┘       └───────────────┘     └──────────────┘
```

### 2.2 层级分解

| 层级 | 职责 | 主要模块 |
|------|------|----------|
| **表现层 (Presentation)** | TUI 渲染、用户输入、Markdown 展示 | `tui/`, `tty_app.py`, `tty-app.ts` |
| **应用层 (Application)** | Agent 循环、会话管理、自动模式 | `agent_loop.py`, `agent-loop.ts`, `session.py`, `auto_mode.py` |
| **服务层 (Service)** | 模型适配、工具执行、权限控制、技能系统 | `model_registry.py`, `tooling.py`, `permissions.py`, `skills.py` |
| **基础设施层 (Infrastructure)** | 配置管理、状态持久化、MCP 连接 | `config.py`, `state.py`, `mcp.py`, `hooks.py` |

### 2.3 组件关系

```
TTY App ──▶ Agent Loop ──▶ Model Adapter ──▶ LLM API
   │            │
   │            ▼
   │       Tool Registry ──▶ Built-in Tools
   │            │
   │            ▼
   │       MCP Connector ──▶ External MCP Servers
   │
   ▼
Session ──▶ State ──▶ Memory
```

---

## 3. 多语言实现版本 (Multi-Language Implementations)

### 3.1 TypeScript 版本 (ts-src/)

| 特性 | 说明 |
|------|------|
| **运行时** | Node.js (ESM 模块) |
| **包管理** | npm, package.json |
| **编译** | TypeScript (tsconfig.json) |
| **入口** | `src/index.ts` → `bin/minicode` |
| **TUI 框架** | 自研终端渲染（ink 模式） |
| **优势** | 类型安全、与 Claude Code 生态兼容、异步性能优秀 |

### 3.2 Python 版本 (py-src/)

| 特性 | 说明 |
|------|------|
| **运行时** | Python 3.10+ |
| **包管理** | pip/pyproject.toml |
| **安装** | `pip install -e .` |
| **入口** | `minicode/main.py` |
| **TUI 框架** | Rich / 自研终端渲染 |
| **优势** | 开发效率高、AI/ML 生态丰富、易于原型开发 |

### 3.3 功能对比表

| 功能模块 | TypeScript | Python | 说明 |
|----------|:----------:|:------:|------|
| Agent Loop | `agent-loop.ts` | `agent_loop.py` | 核心循环逻辑 |
| Tool System | `tool.ts` + `tools/` | `tooling.py` + `tools/` | 工具注册与执行 |
| TUI | `tty-app.ts` + `tui/` | `tty_app.py` + `tui/` | 终端界面 |
| Config | `config.ts` | `config.py` | 配置加载 |
| MCP | `mcp.ts` | `mcp.py` | MCP 协议支持 |
| Permissions | `permissions.ts` | `permissions.py` | 权限管理 |
| Skills | `skills.ts` | `skills.py` | 技能系统 |
| Model Adapters | `anthropic-adapter.ts` | `anthropic_adapter.py` / `openai_adapter.py` | LLM 适配 |
| Context Manager | - | `context_manager.py` | 上下文管理 |
| Memory | - | `memory.py` | 长期记忆 |
| State | - | `state.py` | 状态管理 |
| Session | - | `session.py` | 会话管理 |
| Hooks | - | `hooks.py` | 钩子系统 |
| Auto Mode | - | `auto_mode.py` | 自动执行 |
| Prompt Pipeline | `prompt.ts` | `prompt.py` + `prompt_pipeline.py` | 提示词处理 |
| File Review | `file-review.ts` | `file_review.py` | 代码审查 |

---

## 4. 项目目录结构 (Directory Structure)

```
minicode/
├── ts-src/                          # TypeScript 主版本
│   ├── src/                         # 源代码
│   │   ├── index.ts                 # 入口文件
│   │   ├── agent-loop.ts            # Agent 循环引擎
│   │   ├── tool.ts                  # 工具注册与执行
│   │   ├── tty-app.ts               # TTY 应用主入口
│   │   ├── config.ts                # 配置管理
│   │   ├── permissions.ts           # 权限管理器
│   │   ├── skills.ts                # 技能系统
│   │   ├── mcp.ts                   # MCP 服务器连接
│   │   ├── mcp-status.ts            # MCP 状态管理
│   │   ├── prompt.ts                # 提示词构建
│   │   ├── anthropic-adapter.ts     # Anthropic API 适配器
│   │   ├── mock-model.ts            # 模拟模型（测试用）
│   │   ├── types.ts                 # 类型定义
│   │   ├── history.ts               # 消息历史
│   │   ├── file-review.ts           # 文件审查
│   │   ├── workspace.ts             # 工作区管理
│   │   ├── ui.ts                    # UI 组件
│   │   ├── cli-commands.ts          # CLI 命令
│   │   ├── install.ts               # 安装脚本
│   │   ├── manage-cli.ts            # CLI 管理
│   │   ├── local-tool-shortcuts.ts  # 本地工具快捷方式
│   │   ├── background-tasks.ts      # 后台任务
│   │   ├── tools/                   # 内置工具集
│   │   │   ├── index.ts
│   │   │   ├── read-file.ts
│   │   │   ├── write-file.ts
│   │   │   ├── edit-file.ts
│   │   │   ├── modify-file.ts
│   │   │   ├── patch-file.ts
│   │   │   ├── grep-files.ts
│   │   │   ├── list-files.ts
│   │   │   ├── run-command.ts
│   │   │   ├── ask-user.ts
│   │   │   ├── web-fetch.ts
│   │   │   ├── web-search.ts
│   │   │   └── load-skill.ts
│   │   ├── tui/                     # TUI 组件
│   │   │   ├── index.ts
│   │   │   ├── screen.ts
│   │   │   ├── input.ts
│   │   │   ├── input-parser.ts
│   │   │   ├── markdown.ts
│   │   │   ├── transcript.ts
│   │   │   ├── chrome.ts
│   │   │   └── types.ts
│   │   └── utils/                   # 工具函数
│   │       ├── errors.ts
│   │       └── web.ts
│   ├── bin/                         # 可执行脚本
│   │   ├── minicode
│   │   ├── minicode.cmd
│   │   └── minicode.ps1
│   ├── package.json
│   ├── tsconfig.json
│   ├── ARCHITECTURE.md              # 架构文档
│   ├── ARCHITECTURE_ZH.md           # 架构文档（中文）
│   ├── README.md
│   └── README.zh-CN.md
│
├── py-src/                          # Python 版本
│   ├── minicode/                    # 核心包
│   │   ├── __init__.py
│   │   ├── main.py                  # 入口文件
│   │   ├── agent_loop.py            # Agent 循环引擎
│   │   ├── agent_protocol.py        # Agent 协议
│   │   ├── tooling.py               # 工具注册与执行
│   │   ├── tty_app.py               # TTY 应用
│   │   ├── config.py                # 配置管理
│   │   ├── permissions.py           # 权限管理器
│   │   ├── skills.py                # 技能系统
│   │   ├── mcp.py                   # MCP 服务器连接
│   │   ├── model_registry.py        # 模型注册表
│   │   ├── anthropic_adapter.py     # Anthropic 适配器
│   │   ├── openai_adapter.py        # OpenAI 适配器
│   │   ├── mock_model.py            # 模拟模型
│   │   ├── context_manager.py       # 上下文管理器
│   │   ├── memory.py                # 长期记忆系统
│   │   ├── state.py                 # 状态管理
│   │   ├── session.py               # 会话管理
│   │   ├── hooks.py                 # 钩子系统
│   │   ├── auto_mode.py             # 自动模式
│   │   ├── prompt.py                # 提示词构建
│   │   ├── prompt_pipeline.py       # 提示词流水线
│   │   ├── file_review.py           # 文件审查
│   │   ├── history.py               # 消息历史
│   │   ├── workspace.py             # 工作区管理
│   │   ├── types.py                 # 类型定义
│   │   ├── cost_tracker.py          # 成本追踪
│   │   ├── cli_commands.py          # CLI 命令
│   │   ├── install.py               # 安装脚本
│   │   ├── manage_cli.py            # CLI 管理
│   │   ├── local_tool_shortcuts.py  # 本地工具快捷方式
│   │   ├── background_tasks.py      # 后台任务
│   │   ├── api_retry.py             # API 重试
│   │   ├── headless.py              # 无头模式
│   │   ├── gateway.py               # 网关
│   │   ├── logging_config.py        # 日志配置
│   │   ├── working_memory.py        # 工作记忆
│   │   ├── user_profile.py          # 用户配置
│   │   ├── context_isolation.py     # 上下文隔离
│   │   ├── safe_execution.py        # 安全执行
│   │   ├── task_tracker.py          # 任务追踪
│   │   ├── task_graph.py            # 任务图
│   │   ├── cron_runner.py           # 定时任务执行器
│   │   ├── tools/                   # 内置工具集
│   │   │   ├── __init__.py
│   │   │   ├── read_file.py
│   │   │   ├── write_file.py
│   │   │   ├── edit_file.py
│   │   │   ├── modify_file.py
│   │   │   ├── patch_file.py
│   │   │   ├── grep_files.py
│   │   │   ├── list_files.py
│   │   │   ├── run_command.py
│   │   │   ├── ask_user.py
│   │   │   ├── web_fetch.py
│   │   │   ├── web_search.py
│   │   │   ├── load_skill.py
│   │   │   ├── git.py
│   │   │   ├── file_tree.py
│   │   │   ├── code_nav.py          # 代码导航
│   │   │   ├── code_review.py       # 代码审查
│   │   │   ├── test_runner.py       # 测试运行器
│   │   │   ├── todo_write.py        # 任务写入
│   │   │   ├── task.py              # 任务工具
│   │   │   ├── http_utils.py        # HTTP 工具
│   │   │   ├── json_utils.py        # JSON 工具
│   │   │   ├── csv_utils.py         # CSV 工具
│   │   │   ├── crypto_utils.py      # 加密工具
│   │   │   ├── encoding_utils.py    # 编码工具
│   │   │   ├── regex_utils.py       # 正则工具
│   │   │   ├── text_utils.py        # 文本工具
│   │   │   ├── diff_viewer.py       # Diff 查看器
│   │   │   ├── archive_utils.py     # 归档工具
│   │   │   └── batch_ops.py         # 批量操作
│   │   └── tui/                     # TUI 组件
│   │       ├── __init__.py
│   │       ├── screen.py
│   │       ├── input.py
│   │       ├── input_handler.py
│   │       ├── input_parser.py
│   │       ├── markdown.py
│   │       ├── transcript.py
│   │       ├── renderer.py
│   │       ├── chrome.py
│   │       ├── theme.py
│   │       ├── types.py
│   │       ├── navigation.py
│   │       ├── ui_hints.py
│   │       ├── event_flow.py
│   │       ├── session_flow.py
│   │       ├── runtime_control.py
│   │       ├── tool_helpers.py
│   │       └── tool_lifecycle.py
│   ├── tests/                       # 测试
│   │   ├── fixtures/
│   │   │   └── fake_mcp_server.py
│   │   ├── test_agent_loop.py
│   │   ├── test_anthropic_adapter.py
│   │   ├── test_cli_commands.py
│   │   ├── test_config.py
│   │   ├── test_integration.py
│   │   ├── test_mcp.py
│   │   ├── test_mock_model.py
│   │   ├── test_permissions.py
│   │   ├── test_prompt.py
│   │   ├── test_session.py
│   │   ├── test_skills.py
│   │   ├── test_tools.py
│   │   ├── test_tty_app.py
│   │   ├── test_tui.py
│   │   └── ...（更多测试）
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── README.md
│
├── superpowers-zh/                  # 中文 Superpowers 插件
│   ├── skills/                      # 技能定义
│   │   ├── brainstorming/
│   │   ├── chinese-code-review/
│   │   ├── chinese-git-workflow/
│   │   ├── executing-plans/
│   │   ├── mcp-builder/
│   │   ├── systematic-debugging/
│   │   ├── using-git-worktrees/
│   │   ├── using-superpowers/
│   │   ├── workflow-runner/
│   │   ├── writing-plans/
│   │   └── writing-skills/
│   ├── commands/                    # 命令定义
│   │   ├── brainstorm.md
│   │   ├── execute-plan.md
│   │   └── write-plan.md
│   ├── hooks/                       # 钩子
│   ├── agents/                      # Agent 角色
│   │   └── code-reviewer.md
│   ├── Docs/Documentation/                        # 多平台适配文档
│   ├── tests/                       # 测试
│   ├── package.json
│   └── README.md
│
├── claude-code-src/                 # Claude Code 参考源码
│   └── claude-code/src/             # Claude Code 原始实现（参考用）
│
├── MiniCode-fork/                   # MiniCode 上游 fork（参考用）
│
├── .mcp.json                        # 项目级 MCP 配置
│
└── [安全/优化报告]                   # 各类审计和优化报告
    ├── SECURITY_AND_COMPATIBILITY_AUDIT.md
    ├── SECURITY_FIXES_REPORT.md
    ├── SECURITY_TESTS.md
    ├── DEEP_OPTIMIZATION_REPORT.md
    └── ...
```

---

## 5. 核心模块详解 (Core Modules)

### 5.1 Agent Loop (agent_loop.py / agent-loop.ts)

**职责**：Agent 的核心执行引擎，实现 感知→思考→行动→观察 的循环。

**核心流程**：

```
用户输入 → 构建消息列表 → 调用 LLM → 解析响应
    ├── 有 tool_call → 执行工具 → 获取结果 → 继续循环
    ├── 有 assistant 文本 → 返回给用户 → 结束本轮
    ├── progress 消息 → 显示进度 → 继续循环
    └── 空响应 → 重试或结束
```

**关键特性**（TypeScript 版本 [agent-loop.ts](file:///d:/Desktop/minicode/ts-src/src/agent-loop.ts)）：

- **最大步骤限制**：默认 `maxSteps = 50`，防止无限循环
- **空响应重试**：最多重试 2 次空响应
- **思考中断恢复**：`pause_turn` 或 `max_tokens` 中断时，最多重试 3 次
- **Progress 消息**：区分中间进度和最终回复
- **回调机制**：`onToolStart`、`onToolResult`、`onAssistantMessage`、`onProgressMessage`
- **错误计数**：跟踪工具错误次数，影响错误恢复策略

**Python 版本**（[agent_loop.py](file:///d:/Desktop/minicode/minicode/agent_loop.py)）：

- 与 TS 版本逻辑对等，使用 Python 异步编程模式
- 额外支持：成本追踪、工作记忆集成、上下文压缩

### 5.2 Tool System (tooling.py / tool.ts, tools/)

**职责**：管理所有内置工具和外部工具的注册、权限校验和执行。

**核心接口**：

| 方法 | 说明 |
|------|------|
| `register(name, handler)` | 注册工具 |
| `execute(name, input, context)` | 执行工具 |
| `list()` | 列出所有可用工具 |

**工具执行上下文**：
```python
ToolContext:
  cwd: str              # 当前工作目录
  permissions: PermissionManager  # 权限管理器
  config: dict          # 配置
  session: Session      # 会话引用
```

**内置工具**（详见第 7 节）：

文件操作：`read_file`, `write_file`, `edit_file`, `modify_file`, `patch_file`, `list_files`, `grep_files`, `file_tree`

命令执行：`run_command`

用户交互：`ask_user`

网络：`web_fetch`, `web_search`

开发工具：`git`, `code_nav`, `code_review`, `test_runner`, `todo_write`

### 5.3 TUI (tty_app.py / tty-app.ts, tui/)

**职责**：终端用户界面，负责输入处理和输出渲染。

**架构**：

```
TTY App
├── Input Handler     → 读取用户键盘输入
├── Input Parser      → 解析斜杠命令（/help, /clear, /model, /quit）
├── Screen Renderer   → 管理终端缓冲区
├── Markdown Renderer → 渲染 Markdown 格式的 AI 回复
├── Transcript Panel  → 显示对话历史
└── Chrome            → 终端标题栏和状态栏
```

**Python 版本 TUI 组件**：

| 文件 | 职责 |
|------|------|
| `screen.py` | 终端屏幕缓冲区管理 |
| `input.py` / `input_handler.py` | 用户输入处理 |
| `input_parser.py` | 斜杠命令解析 |
| `markdown.py` | Markdown 渲染 |
| `transcript.py` | 对话历史面板 |
| `renderer.py` | 主渲染器 |
| `chrome.py` | 顶部状态栏 |
| `theme.py` | 颜色主题 |
| `types.py` | TUI 类型定义 |
| `navigation.py` | 面板导航 |
| `ui_hints.py` | UI 提示 |
| `event_flow.py` | 事件流处理 |
| `session_flow.py` | 会话流程 |
| `runtime_control.py` | 运行时控制 |
| `tool_helpers.py` | 工具辅助 |
| `tool_lifecycle.py` | 工具生命周期 |

### 5.4 Configuration (config.py / config.ts)

**职责**：管理配置文件的加载、合并和访问。

**配置层级**（从低到高优先级）：

1. 默认配置（代码内置）
2. 系统级配置（`~/.minicode/config.json`）
3. 项目级配置（`.minicode/config.json`）
4. 环境变量（`MINICODE_*`）
5. CLI 参数

**核心配置项**：

```yaml
model: claude-sonnet-4-20250514    # 默认模型
api_key: ...                        # API 密钥
max_steps: 50                       # 最大工具调用步数
max_tokens: 8192                    # 最大输出 token
permissions:                        # 权限策略
  run_command: ask                  # ask | allow | deny
  file_edit: ask
  web_fetch: allow
mcp_servers:                        # MCP 服务器列表
  - name: ...
    command: ...
    args: [...]
```

### 5.5 MCP Integration (mcp.py / mcp.ts)

**职责**：通过 Model Context Protocol 连接外部服务。

**支持的 MCP 传输方式**：

| 类型 | 说明 |
|------|------|
| `stdio` | 标准输入输出管道 |
| `SSE` | Server-Sent Events |
| `HTTP` | HTTP 请求/响应 |
| `WebSocket` | 双向 WebSocket 连接 |

**配置方式**（`.mcp.json`）：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

**MCP 工具发现**：启动时自动连接所有配置的 MCP Server，发现其提供的工具，注册到本地 Tool Registry。

### 5.6 Permission System (permissions.py / permissions.ts)

**职责**：控制工具的访问权限，防止未经授权的操作。

**权限级别**：

| 级别 | 说明 |
|------|------|
| `allow` | 自动允许，无需确认 |
| `ask` | 每次执行前询问用户 |
| `deny` | 始终拒绝 |

**权限维度**：

- **命令白名单/黑名单**：限制可执行的 shell 命令
- **文件路径隔离**：限制可访问的文件路径范围
- **网络访问控制**：限制 web_fetch/web_search 的目标
- **会话级权限缓存**：用户选择 "always allow" 后，本次会话内不再询问

**权限检查流程**：
```
工具执行请求 → 检查权限策略 → allow: 直接执行
                              ask:  弹出确认 → 用户同意 → 执行
                              deny: 返回错误
```

### 5.7 Skills System (skills.py / skills.ts)

**职责**：管理和加载可复用的技能（Skills），每个技能是一组预定义的指令和上下文。

**技能结构**：

```
skills/
  └── <skill-name>/
      └── SKILL.md          # 技能定义文件
```

**SKILL.md 格式**：

```markdown
---
name: brainstorming
description: 头脑风暴和创意生成
---

# Brainstorming Skill

## Instructions
...（具体的技能指令）...
```

**生命周期**：

1. 启动时扫描项目 `.claude/skills/` 和全局技能目录
2. 根据用户输入自动匹配和触发相关技能
3. 技能指令注入到系统提示词中
4. 可通过 `load_skill` 工具手动加载

### 5.8 Model Registry & Adapters

**职责**：管理多种 LLM 后端，提供统一的调用接口。

**模型注册表**（Python [model_registry.py](file:///d:/Desktop/minicode/minicode/model_registry.py)）：

```python
ModelRegistry:
  register(model_id, adapter)    # 注册模型适配器
  get(model_id) → ModelAdapter   # 获取模型适配器
  list() → List[ModelInfo]       # 列出所有可用模型
  set_default(model_id)          # 设置默认模型
```

**适配器实现**：

| 适配器 | 文件 | 支持的模型 |
|--------|------|------------|
| Anthropic | `anthropic_adapter.py` / `anthropic-adapter.ts` | Claude 3/4 全系列 |
| OpenAI | `openai_adapter.py` | GPT-4, GPT-4o, o1, o3 等 |
| Mock | `mock_model.py` | 测试用模拟模型 |

**统一接口**：

```python
ModelAdapter:
  next(messages) → ModelResponse    # 发送消息，获取响应
  stream(messages) → AsyncIterator  # 流式输出
  get_usage() → UsageInfo           # 获取 token 用量
```

### 5.9 Context Management (context_manager.py)

**职责**：管理对话上下文，包括上下文窗口优化、上下文压缩和上下文隔离。

**核心功能**：

- **上下文窗口管理**：跟踪当前上下文大小，接近限制时触发压缩
- **上下文压缩**：保留关键信息，压缩历史消息
- **上下文隔离**（[context_isolation.py](file:///d:/Desktop/minicode/minicode/context_isolation.py)）：不同会话/任务的上下文隔离

### 5.10 Memory System (memory.py)

**职责**：提供长期记忆能力，跨会话持久化重要信息。

**存储结构**：

```
.mini-code-memory/
  └── advanced_memory.json      # 高级记忆数据
```

**记忆类型**：

| 类型 | 说明 | 存储位置 |
|------|------|----------|
| 工作记忆 | 当前会话的短期上下文 | `working_memory.py` |
| 长期记忆 | 跨会话持久化的重要信息 | `memory.py` |
| 会话记忆 | 会话级记忆 | `.mini-code-session-memory/` |

### 5.11 State Management (state.py)

**职责**：管理 Agent 的运行状态，提供持久化和恢复能力。

**状态内容**：

- 当前模型配置
- 权限策略缓存
- 会话状态
- 工具使用统计

### 5.12 Session Management (session.py)

**职责**：管理对话会话，包括会话创建、恢复和持久化。

**核心功能**：

- 会话 ID 生成和管理
- 消息历史持久化
- 会话恢复（重启后恢复上次会话）
- 会话间隔离

### 5.13 Hooks System (hooks.py)

**职责**：提供生命周期钩子，允许在关键事件发生时执行自定义逻辑。

**可用钩子**：

| 钩子名称 | 触发时机 |
|----------|----------|
| `session-start` | 会话开始时 |
| `session-end` | 会话结束时 |
| `tool-before` | 工具执行前 |
| `tool-after` | 工具执行后 |
| `user-message` | 收到用户消息时 |
| `assistant-message` | 生成助手消息时 |

### 5.14 Auto Mode (auto_mode.py)

**职责**：支持无头自动化执行模式，无需用户交互。

**运行模式**：

| 模式 | 说明 |
|------|------|
| TUI 模式 | 交互式终端界面 |
| Auto 模式 | 自动执行所有任务，无需确认 |
| Headless 模式 | 无界面模式，通过 API 交互 |

### 5.15 Prompt Pipeline (prompt.py, prompt_pipeline.py)

**职责**：构建和管理发送给 LLM 的提示词。

**提示词组成**：

```
System Prompt (系统指令)
├── Agent 角色定义
├── 可用工具列表
├── 工作区上下文
├── 技能指令（如果激活）
└── 安全约束

Conversation History (对话历史)
├── 用户消息
├── 助手回复
├── 工具调用
└── 工具结果

Current User Message (当前用户输入)
```

### 5.16 File Review (file_review.py)

**职责**：自动审查文件内容，识别潜在问题。

**审查维度**：

- 代码质量和风格
- 安全问题
- 性能问题
- 潜在 bug

---

## 6. 关键类与数据结构 (Key Classes & Data Structures)

| 类/类型 | 所在文件 | 语言 | 说明 |
|---------|----------|------|------|
| `runAgentTurn()` | agent-loop.ts | TS | Agent 单轮执行函数 |
| `AgentLoop` | agent_loop.py | Py | Agent 循环类 |
| `ToolRegistry` | tool.ts / tooling.py | TS/Py | 工具注册表 |
| `ToolResult` | tool.ts / tooling.py | TS/Py | 工具执行结果 |
| `PermissionManager` | permissions.ts / permissions.py | TS/Py | 权限管理器 |
| `PermissionPolicy` | permissions.ts / permissions.py | TS/Py | 权限策略 |
| `ModelAdapter` | types.ts / model_registry.py | TS/Py | 模型适配器接口 |
| `AnthropicAdapter` | anthropic-adapter.ts / anthropic_adapter.py | TS/Py | Anthropic 适配器 |
| `OpenAIAdapter` | openai_adapter.py | Py | OpenAI 适配器 |
| `ModelRegistry` | model_registry.py | Py | 模型注册表 |
| `ChatMessage` | types.ts / types.py | TS/Py | 聊天消息 |
| `ModelResponse` | types.ts / types.py | TS/Py | 模型响应 |
| `Config` | config.ts / config.py | TS/Py | 配置对象 |
| `SkillManager` | skills.ts / skills.py | TS/Py | 技能管理器 |
| `MCPManager` | mcp.ts / mcp.py | TS/Py | MCP 管理器 |
| `ContextManager` | context_manager.py | Py | 上下文管理器 |
| `MemoryManager` | memory.py | Py | 记忆管理器 |
| `StateManager` | state.py | Py | 状态管理器 |
| `SessionManager` | session.py | Py | 会话管理器 |
| `HooksManager` | hooks.py | Py | 钩子管理器 |
| `AutoMode` | auto_mode.py | Py | 自动模式 |
| `CostTracker` | cost_tracker.py | Py | 成本追踪器 |
| `TTYApp` | tty-app.ts / tty_app.py | TS/Py | TTY 应用主类 |
| `ScreenRenderer` | screen.ts / screen.py | TS/Py | 屏幕渲染器 |
| `MarkdownRenderer` | markdown.ts / markdown.py | TS/Py | Markdown 渲染器 |
| `TranscriptPanel` | transcript.ts / transcript.py | TS/Py | 对话面板 |
| `InputParser` | input-parser.ts / input_parser.py | TS/Py | 输入解析器 |
| `Workspace` | workspace.ts / workspace.py | TS/Py | 工作区 |
| `TaskTracker` | task_tracker.py | Py | 任务追踪器 |
| `TaskGraph` | task_graph.py | Py | 任务图 |
| `PromptPipeline` | prompt_pipeline.py | Py | 提示词流水线 |
| `FileReviewer` | file-review.ts / file_review.py | TS/Py | 文件审查器 |
| `HistoryManager` | history.ts / history.py | TS/Py | 历史管理器 |

---

## 7. 工具列表 (Tools Catalog)

### 7.1 核心工具

| 工具名称 | 说明 | 需要权限 |
|----------|------|----------|
| `read_file` | 读取文件内容 | 否 |
| `write_file` | 写入文件（覆盖） | 是 |
| `edit_file` | 编辑文件（查找替换） | 是 |
| `modify_file` | 修改文件内容 | 是 |
| `patch_file` | 对文件应用 Patch/差分 | 是 |
| `list_files` | 列出目录中的文件 | 否 |
| `grep_files` | 在文件中搜索文本模式 | 否 |
| `file_tree` | 生成目录树结构 | 否 |

### 7.2 命令执行

| 工具名称 | 说明 | 需要权限 |
|----------|------|----------|
| `run_command` | 执行 shell 命令 | 是 |

### 7.3 用户交互

| 工具名称 | 说明 | 需要权限 |
|----------|------|----------|
| `ask_user` | 向用户提问，等待回答 | 否 |

### 7.4 网络工具

| 工具名称 | 说明 | 需要权限 |
|----------|------|----------|
| `web_fetch` | 获取网页内容 | 是 |
| `web_search` | 执行网络搜索 | 是 |

### 7.5 开发工具（Python 版额外工具）

| 工具名称 | 说明 | 需要权限 |
|----------|------|----------|
| `git` | Git 操作 | 是 |
| `code_nav` | 代码导航（跳转定义、引用） | 否 |
| `code_review` | 代码审查 | 否 |
| `test_runner` | 运行测试 | 是 |
| `todo_write` | 写入/更新任务列表 | 否 |
| `task` | 任务管理 | 否 |

### 7.6 工具函数（Python 版）

| 工具名称 | 说明 |
|----------|------|
| `http_utils` | HTTP 请求工具 |
| `json_utils` | JSON 处理工具 |
| `csv_utils` | CSV 处理工具 |
| `crypto_utils` | 加密/解密工具 |
| `encoding_utils` | 编码转换工具 |
| `regex_utils` | 正则表达式工具 |
| `text_utils` | 文本处理工具 |
| `diff_viewer` | Diff 查看器 |
| `archive_utils` | 归档/压缩工具 |
| `batch_ops` | 批量操作工具 |

### 7.7 系统工具

| 工具名称 | 说明 |
|----------|------|
| `load_skill` | 加载指定技能 |

---

## 8. 依赖关系 (Dependencies)

### 8.1 TypeScript 版本外部依赖

```json
{
  "dependencies": {
    "@anthropic-ai/sdk": "Anthropic 官方 SDK",
    "openai": "OpenAI 官方 SDK",
    "@modelcontextprotocol/sdk": "MCP 协议 SDK",
    "chalk": "终端颜色",
    "glob": "文件匹配",
    "ignore": ".gitignore 解析"
  },
  "devDependencies": {
    "typescript": "TypeScript 编译器",
    "vitest": "测试框架"
  }
}
```

### 8.2 Python 版本外部依赖

```toml
[project.dependencies]
anthropic = "Anthropic 官方 SDK"
openai = "OpenAI 官方 SDK"
rich = "终端渲染（表格、颜色、进度条）"
mcp = "MCP 协议 SDK"
pydantic = "数据验证"
pyyaml = "YAML 解析"
httpx = "HTTP 客户端"
aiofiles = "异步文件操作"
```

### 8.3 内部模块依赖关系

```
agent_loop
├── model_registry (AnthropicAdapter, OpenAIAdapter)
├── tooling (ToolRegistry + 所有内置工具)
├── permissions (PermissionManager)
├── prompt (PromptBuilder)
└── types (ChatMessage, ModelResponse)

tty_app
├── tui/* (Screen, Input, Markdown, Transcript)
├── agent_loop
├── session
├── state
└── config

tooling
├── permissions
├── config
├── skills (load_skill)
└── mcp (外部工具)

mcp
├── config
└── tooling (工具注册)

session
├── state
├── memory
└── history

prompt
├── config
├── workspace
├── skills
└── prompt_pipeline
```

---

## 9. 数据流 (Data Flow)

### 9.1 Agent Loop 数据流

```
                    ┌──────────────┐
  用户输入 ────────▶│  Prompt      │
                    │  Builder     │
                    └──────┬───────┘
                           │ 消息列表 [Message[]]
                           ▼
                    ┌──────────────┐
                    │  Model       │
                    │  Adapter     │
                    └──────┬───────┘
                           │ ModelResponse
                           ▼
                    ┌──────────────┐
               ┌────│  响应解析    │────┐
               │    └──────────────┘    │
               ▼                        ▼
        ┌──────────────┐         ┌──────────────┐
        │  文本回复    │         │  Tool Calls  │
        │  (结束本轮)  │         │  [待执行]     │
        └──────────────┘         └──────┬───────┘
                                        │
                                        ▼
                               ┌──────────────┐
                               │  权限检查    │
                               └──────┬───────┘
                                      │
                               ┌──────▼───────┐
                               │  工具执行    │
                               └──────┬───────┘
                                      │ ToolResult
                                      ▼
                               ┌──────────────┐
                               │  结果注入    │
                               │  消息列表    │
                               └──────┬───────┘
                                      │
                                      ▼
                              (回到 Model Adapter，继续下一轮)
```

### 9.2 工具执行流程

```
runAgentTurn 调用 tools.execute(name, input, context)
        │
        ▼
ToolRegistry.lookup(name) → 找到工具处理器
        │
        ▼
PermissionManager.check(name, input, context)
        │
        ├── deny  → 返回错误结果
        │
        ├── ask   → TUI 显示确认 → 用户同意/拒绝
        │
        └── allow → 继续执行
                │
                ▼
        工具处理器执行实际逻辑
                │
                ▼
        构造 ToolResult { ok, output, awaitUser }
                │
                ▼
        返回给 Agent Loop → 注入消息列表
```

### 9.3 消息流

```
UserMessage ──▶ Prompt Pipeline ──▶ [user, content]
                                       │
                                       ▼
                              ModelAdapter.next(messages)
                                       │
                                       ▼
                              ModelResponse {
                                type: "assistant",
                                content: "...",
                                calls: [ToolCall, ...]
                              }
                                       │
                          ┌────────────┼────────────┐
                          ▼            ▼            ▼
                    [assistant,    [assistant_   [assistant_
                     content]       tool_call,   progress,
                                    input]       content]
                          │            │            │
                          ▼            ▼            ▼
                    显示给用户   执行工具    显示进度
                                 │
                                 ▼
                          [tool_result,
                           content,
                           isError]
                                 │
                                 ▼
                          回到 Model → 下一轮
```

---

## 10. 设计模式 (Design Patterns)

| 模式 | 应用场景 | 说明 |
|------|----------|------|
| **适配器模式 (Adapter)** | ModelAdapter | 将不同 LLM API 统一为相同接口 |
| **注册表模式 (Registry)** | ToolRegistry, ModelRegistry | 集中管理可插拔组件 |
| **策略模式 (Strategy)** | PermissionPolicy | 不同权限级别使用不同策略 |
| **观察者模式 (Observer)** | 回调机制 (onToolStart, onToolResult) | 事件通知 |
| **管道模式 (Pipeline)** | PromptPipeline | 提示词构建的流水线处理 |
| **状态模式 (State)** | StateManager | Agent 状态管理 |
| **模板方法 (Template Method)** | 工具执行流程 | 定义通用流程，子类实现细节 |
| **单例模式 (Singleton)** | Config, Session | 全局唯一实例 |
| **工厂模式 (Factory)** | ModelRegistry.get() | 根据模型 ID 创建对应适配器 |
| **责任链模式 (Chain of Responsibility)** | 权限检查 | 多级权限策略链式检查 |
| **发布-订阅模式 (Pub/Sub)** | Hooks 系统 | 钩子事件的发布与订阅 |

---

## 11. 安全机制 (Security Mechanisms)

### 11.1 权限系统

- **工具级权限**：每个工具可配置 `allow` / `ask` / `deny`
- **命令白名单**：限制 `run_command` 可执行的命令范围
- **会话级权限缓存**：用户确认后，本次会话内不再重复询问

### 11.2 MCP 安全

- **传输隔离**：MCP Server 通过独立进程通信（stdio）或网络连接
- **工具沙箱**：MCP 暴露的工具同样受权限系统约束
- **配置验证**：启动时验证 `.mcp.json` 配置合法性

### 11.3 路径隔离

- **工作目录限制**：文件操作限制在当前工作目录及其子目录
- **路径遍历防护**：防止 `../` 等路径逃逸攻击
- **符号链接处理**：安全处理符号链接

### 11.4 命令验证

- **命令白名单/黑名单**：控制可执行的 shell 命令
- **参数注入防护**：防止命令注入攻击
- **SSRF 防护**：`web_fetch` / `web_search` 限制可访问的目标地址

### 11.5 上下文隔离

- **会话隔离**：不同会话的上下文互不影响
- **内存隔离**：敏感信息不会跨会话泄露
- **环境变量控制**：敏感环境变量不会传递给子进程

---

## 12. 运行方式 (How to Run)

### 12.1 TypeScript 版本

**安装**：

```bash
cd ts-src
npm install
npm run build
```

**运行**：

```bash
# 通过 bin 脚本
./bin/minicode

# 或直接运行
npx tsx src/index.ts
```

**配置**：

```bash
# 设置 API 密钥
export ANTHROPIC_API_KEY="sk-..."

# 或使用 OpenAI 兼容模型
export OPENAI_API_KEY="sk-..."
export MINICODE_MODEL="gpt-4o"
```

**常用命令**：

| 命令 | 说明 |
|------|------|
| `minicode` | 启动交互式 TUI |
| `minicode --model <model>` | 指定模型 |
| `minicode --auto` | 自动模式 |
| `minicode --help` | 帮助信息 |

### 12.2 Python 版本

**安装**：

```bash
cd py-src
pip install -e .
```

**运行**：

```bash
# 启动交互式 TUI
minicode

# 或直接运行
python -m minicode.main
```

**配置**：

```bash
# 设置 API 密钥
export ANTHROPIC_API_KEY="sk-..."

# 或使用 .env 文件
cp .env.example .env
# 编辑 .env 填入 API 密钥
```

**Docker 运行**：

```bash
docker-compose up
```

**常用命令**：

| 命令 | 说明 |
|------|------|
| `minicode` | 启动交互式 TUI |
| `minicode --auto "修改xxx"` | 自动执行任务 |
| `minicode --headless` | 无头模式 |
| `minicode --model <model>` | 指定模型 |
| `minicode --version` | 版本信息 |

### 12.3 测试命令

```bash
# Python 版本测试
cd py-src
pytest

# TypeScript 版本测试
cd ts-src
npm test
```

---

## 13. 测试 (Testing)

### 13.1 Python 测试文件

| 测试文件 | 测试内容 |
|----------|----------|
| [test_agent_loop.py](file:///d:/Desktop/minicode/py-src/tests/test_agent_loop.py) | Agent 循环逻辑 |
| [test_anthropic_adapter.py](file:///d:/Desktop/minicode/py-src/tests/test_anthropic_adapter.py) | Anthropic 适配器 |
| [test_cli_commands.py](file:///d:/Desktop/minicode/py-src/tests/test_cli_commands.py) | CLI 命令 |
| [test_config.py](file:///d:/Desktop/minicode/py-src/tests/test_config.py) | 配置加载 |
| [test_integration.py](file:///d:/Desktop/minicode/py-src/tests/test_integration.py) | 集成测试 |
| [test_mcp.py](file:///d:/Desktop/minicode/py-src/tests/test_mcp.py) | MCP 连接 |
| [test_mock_model.py](file:///d:/Desktop/minicode/py-src/tests/test_mock_model.py) | 模拟模型 |
| [test_permissions.py](file:///d:/Desktop/minicode/py-src/tests/test_permissions.py) | 权限系统 |
| [test_prompt.py](file:///d:/Desktop/minicode/py-src/tests/test_prompt.py) | 提示词构建 |
| [test_session.py](file:///d:/Desktop/minicode/py-src/tests/test_session.py) | 会话管理 |
| [test_skills.py](file:///d:/Desktop/minicode/py-src/tests/test_skills.py) | 技能系统 |
| [test_tools.py](file:///d:/Desktop/minicode/py-src/tests/test_tools.py) | 工具执行 |
| [test_tty_app.py](file:///d:/Desktop/minicode/py-src/tests/test_tty_app.py) | TTY 应用 |
| [test_tui.py](file:///d:/Desktop/minicode/py-src/tests/test_tui.py) | TUI 渲染 |
| [test_functional_completeness.py](file:///d:/Desktop/minicode/py-src/tests/test_functional_completeness.py) | 功能完整性 |
| [test_packaging.py](file:///d:/Desktop/minicode/py-src/tests/test_packaging.py) | 打包测试 |
| [test_renderer_performance.py](file:///d:/Desktop/minicode/py-src/tests/test_renderer_performance.py) | 渲染性能 |
| [test_transcript_layout.py](file:///d:/Desktop/minicode/py-src/tests/test_transcript_layout.py) | Transcript 布局 |

### 13.2 测试夹具

- [fake_mcp_server.py](file:///d:/Desktop/minicode/py-src/tests/fixtures/fake_mcp_server.py)：模拟 MCP Server，用于 MCP 相关测试

### 13.3 测试方法

- **单元测试**：测试单个模块的功能
- **集成测试**：测试多个模块协作
- **功能测试**：端到端功能验证
- **性能测试**：渲染和响应性能
- **压力测试**：多轮对话压力测试

### 13.4 基准测试

| 文件 | 内容 |
|------|------|
| [performance_benchmark.py](file:///d:/Desktop/minicode/py-src/benchmarks/performance_benchmark.py) | 性能基准测试 |
| [multi_round_stress_test.py](file:///d:/Desktop/minicode/py-src/benchmarks/multi_round_stress_test.py) | 多轮压力测试 |

---

## 14. 扩展机制 (Extension Mechanisms)

### 14.1 Skills（技能）

**添加新技能**：

1. 在 `skills/<skill-name>/` 目录下创建 `SKILL.md`
2. SKILL.md 包含技能的名称、描述和指令
3. Agent 会自动发现并根据用户输入匹配触发

**技能触发**：

- **自动触发**：用户输入包含关键词时自动激活
- **手动加载**：通过 `load_skill` 工具手动加载
- **预加载**：在配置中指定始终加载的技能

### 14.2 MCP Server

**添加外部服务**：

在 `.mcp.json` 中配置：

```json
{
  "mcpServers": {
    "my-service": {
      "command": "npx",
      "args": ["-y", "@my-org/my-mcp-server"],
      "env": {
        "API_KEY": "${MY_API_KEY}"
      }
    }
  }
}
```

**支持的传输类型**：`stdio`（进程管道）、`SSE`、`HTTP`、`WebSocket`

### 14.3 Hooks（钩子）

**配置钩子**：

在 `.minicode/hooks.json` 中配置：

```json
{
  "hooks": {
    "session-start": ["echo 'Session started'"],
    "tool-before": ["echo 'Running tool: $TOOL_NAME'"],
    "tool-after": ["echo 'Tool completed'"]
  }
}
```

### 14.4 插件系统

**superpowers-zh 插件**：

一个完整的中文增强插件，包含：

- **11 个技能**：头脑风暴、中文代码审查、中文 Git 工作流、计划执行、MCP 构建器、系统化调试、Git Worktree、工作流运行器、计划编写、技能编写等
- **3 个命令**：`/brainstorm`、`/execute-plan`、`/write-plan`
- **钩子定义**：`hooks.json` + `hooks-cursor.json`
- **Agent 角色**：`code-reviewer.md`
- **多平台适配**：支持 Claude Code、Cursor、Codex、OpenCode、Qwen、Gemini、Windsurf、VS Code 等

---

## 15. 子项目 (Sub-projects)

### 15.1 superpowers-zh 插件

**定位**：为中文用户提供完整增强体验的插件包。

**核心内容**：

| 目录 | 内容 |
|------|------|
| `skills/` | 11 个中文优化技能 |
| `commands/` | 3 个自定义命令 |
| `hooks/` | 会话钩子 |
| `agents/` | 预定义 Agent 角色 |
| `Docs/Documentation/` | 多平台适配指南 |
| `tests/` | 插件测试 |

**支持平台**：

Claude Code、Cursor、Codex、OpenCode、Qwen、Gemini CLI、Windsurf、VS Code、Aider、Antigravity、Deerflow、Kiro、OpenClaw、Trae

### 15.2 claude-code-src 参考源码

**定位**：Claude Code 的原始源码，作为架构参考和学习材料。

**用途**：

- 理解 Claude Code 的设计模式和架构
- 对比 MiniCode 的实现差异
- 学习终端 TUI 的高级实现技巧

**核心模块**：

| 模块 | 说明 |
|------|------|
| `bootstrap/state.ts` | 启动状态 |
| `bridge/` | 桥接 API |
| `ink/` | Ink 终端渲染引擎 |
| `tools/` | 工具实现 |
| `services/mcp/` | MCP 服务 |
| `commands/` | 内置命令 |
| `utils/` | 工具函数库 |

### 15.3 MiniCode-fork 上游 fork

**定位**：MiniCode 项目的上游参考版本。

**内容**：

- 与 ts-src 结构相似
- 包含 Python 子模块（`external/MiniCode-Python/`）
- 提供架构文档（ARCHITECTURE.md、ROADMAP.md 等）

---

## 附录

### A. 消息角色类型

| 角色 | 说明 |
|------|------|
| `user` | 用户消息 |
| `assistant` | 助手回复 |
| `assistant_progress` | 助手进度更新 |
| `assistant_tool_call` | 助手工具调用记录 |
| `tool_result` | 工具执行结果 |
| `system` | 系统指令 |

### B. 工具结果结构

```typescript
interface ToolResult {
  ok: boolean;          // 是否成功
  output: string;       // 输出内容
  awaitUser?: boolean;  // 是否需要等待用户输入
}
```

### C. 模型响应结构

```typescript
interface ModelResponse {
  type: 'assistant' | 'stream';
  content: string;
  contentKind?: 'progress';
  kind?: 'final' | 'progress';
  calls?: ToolCall[];
  diagnostics?: {
    stopReason?: string;
    blockTypes?: string[];
    ignoredBlockTypes?: string[];
  };
}
```

### D. 项目关键文件索引

| 文件 | 路径 |
|------|------|
| TS 入口 | [ts-src/src/index.ts](file:///d:/Desktop/minicode/ts-src/src/index.ts) |
| TS Agent Loop | [ts-src/src/agent-loop.ts](file:///d:/Desktop/minicode/ts-src/src/agent-loop.ts) |
| TS 工具 | [ts-src/src/tools/](file:///d:/Desktop/minicode/ts-src/src/tools/) |
| TS TUI | [ts-src/src/tty-app.ts](file:///d:/Desktop/minicode/ts-src/src/tty-app.ts) |
| Python 入口 | [minicode/main.py](file:///d:/Desktop/minicode/minicode/main.py) |
| Python Agent Loop | [minicode/agent_loop.py](file:///d:/Desktop/minicode/minicode/agent_loop.py) |
| Python 工具 | [minicode/tools/](file:///d:/Desktop/minicode/minicode/tools/) |
| Python TUI | [minicode/tty_app.py](file:///d:/Desktop/minicode/minicode/tty_app.py) |
| 插件 | [superpowers-zh/](file:///d:/Desktop/minicode/superpowers-zh/) |
| MCP 配置 | [.mcp.json](file:///d:/Desktop/minicode/.mcp.json) |

### E. 相关报告

| 报告 | 内容 |
|------|------|
| [SECURITY_AND_COMPATIBILITY_AUDIT.md](file:///d:/Desktop/minicode/SECURITY_AND_COMPATIBILITY_AUDIT.md) | 安全性和兼容性审计 |
| [SECURITY_FIXES_REPORT.md](file:///d:/Desktop/minicode/SECURITY_FIXES_REPORT.md) | 安全修复报告 |
| [SECURITY_TESTS.md](file:///d:/Desktop/minicode/SECURITY_TESTS.md) | 安全测试 |
| [DEEP_OPTIMIZATION_REPORT.md](file:///d:/Desktop/minicode/DEEP_OPTIMIZATION_REPORT.md) | 深度优化报告 |
| [FINAL_VERIFICATION_REPORT.md](file:///d:/Desktop/minicode/FINAL_VERIFICATION_REPORT.md) | 最终验证报告 |
| [ROBUSTNESS_OPTIMIZATION_REPORT.md](file:///d:/Desktop/minicode/ROBUSTNESS_OPTIMIZATION_REPORT.md) | 健壮性优化报告 |
