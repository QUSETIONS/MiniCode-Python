# MiniCode Python - 使用指南

> 版本: v0.2.0
> 更新时间: 2026-04-05

---

## 🚀 快速开始

### 1. 安装（首次使用）

```bash
# 运行交互式安装向导
python -m minicode.main --install
```

安装向导会要求输入：
- **Model name**: 模型名称（如 `claude-sonnet-4-20250514`）
- **ANTHROPIC_BASE_URL**: API 地址（默认 `https://api.anthropic.com`）
- **ANTHROPIC_AUTH_TOKEN**: API 密钥

配置会保存到 `~/.mini-code/settings.json`

### 2. 启动

```bash
# 正常启动
python -m minicode.main

# 或使用 mock 模式（无需 API，用于测试）
set MINI_CODE_MODEL_MODE=mock
python -m minicode.main
```

### 3. 基本使用

启动后你会看到全屏 TUI 界面：

```
╭──────────────────────────────────────────────────────────────╮
│ MiniCode                  │ provider                         │
│                                                                  │
│ Terminal coding assistant for MiniCode.                        │
│                                                                  │
│ minicode                  │ .../Desktop/minicode/py-src        │
│ [provider] offline  [model] mock  [msgs] 0  [events] 0        │
│ cwd: ...                                                           │
╰──────────────────────────────────────────────────────────────╯

╭──────────────────── session feed ────────────────────────╮
│ Ready                                                    │
│                                                          │
│ Type /help for commands.                                 │
╰──────────────────────────────────────────────────────────╯

╭──────────────────── prompt ──────────────────────────────╮
│ >                                                        │
╰──────────────────────────────────────────────────────────╯

tools on | skills on
```

**输入你的问题**，然后按 Enter。Mock 模式下会模拟 AI 响应。

---

## 📋 命令行选项

### 会话管理

```bash
# 列出所有保存的会话
python -m minicode.main --list-sessions

# 恢复最近的会话
python -m minicode.main --resume

# 恢复特定会话
python -m minicode.main --resume abc123def456

# 使用特定会话 ID 启动
python -m minicode.main --session abc123def456
```

### 安装

```bash
# 运行交互式安装
python -m minicode.main --install
```

### 帮助

```bash
# 显示帮助信息
python -m minicode.main --help
```

---

## ⌨️ 键盘快捷键

### 输入编辑

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 提交输入 / 确认选择 |
| `Tab` | 自动补全 slash 命令 |
| `Backspace` | 删除前一个字符 |
| `Delete` | 删除当前字符 |
| `Ctrl-U` | 清空整行 |
| `Ctrl-A` / `Home` | 跳到行首 |
| `Ctrl-E` / `End` | 跳到行尾 |
| `←` / `→` | 左右移动光标 |
| `Escape` | 清空输入 |

### 历史导航

| 快捷键 | 功能 |
|--------|------|
| `↑` / `Ctrl-P` | 上一条历史 |
| `↓` / `Ctrl-N` | 下一条历史 |

### 滚动

| 快捷键 | 功能 |
|--------|------|
| `PageUp` | 向上滚动 |
| `PageDown` | 向下滚动 |
| `鼠标滚轮` | 滚动 transcript |
| `Ctrl-A` (空输入时) | 跳到顶部 |
| `Ctrl-E` (空输入时) | 跳到底部 |

### 权限审批

当 AI 请求权限时：

| 快捷键 | 功能 |
|--------|------|
| `↑` / `↓` | 选择选项 |
| `Enter` | 确认选择 |
| `1`-`7` | 快速选择 |
| `v` | 切换详情展开/折叠 |
| `Ctrl+O` | 切换详情展开/折叠 |
| `PageUp` / `PageDown` | 滚动详情 |
| `Escape` | 拒绝 |

### 通用

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+C` | 退出程序 |

---

## 🔧 Slash 命令

在输入框中输入 `/` 查看可用命令：

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助 |
| `/tools` | 列出可用工具 |
| `/skills` | 列出已加载技能 |
| `/mcp` | 列出 MCP 服务器 |
| `/status` | 显示当前状态 |
| `/model` | 显示当前模型 |
| `/model <name>` | 切换模型 |
| `/config-paths` | 显示配置路径 |
| `/history` | 显示输入历史 |
| `/transcript-save <path>` | 保存转录 |
| `/exit` | 退出程序 |

---

## 💾 会话持久化

### 自动保存

- 每 30 秒自动保存当前会话
- 保存位置：`~/.mini-code/sessions/`
- 包含：消息历史、transcript、权限状态、skills、MCP 配置

### 手动恢复

```bash
# 查看所有会话
python -m minicode.main --list-sessions

# 输出示例：
# Saved sessions:
# 
#   1. [abc123de] 2026-04-05 14:30 - D:\project
#      Messages: 15 | First: 帮我重构这个代码
# 
#   2. [def456gh] 2026-04-05 10:15 - D:\project
#      Messages: 8 | First: 解释一下这个函数
# 
# Total: 2 session(s)

# 恢复会话
python -m minicode.main --resume abc123de
```

### 会话文件结构

```
~/.mini-code/
├── settings.json          # 用户设置
├── history.json           # 输入历史（最近 200 条）
├── permissions.json       # 权限规则
├── mcp.json              # MCP 服务器配置
├── sessions_index.json   # 会话索引
└── sessions/             # 会话数据
    ├── abc123de.json
    └── def456gh.json
```

---

## 🛠️ 管理命令

### MCP 服务器

```bash
# 列出所有 MCP 服务器
python -m minicode.main mcp list

# 添加用户级服务器
python -m minicode.main mcp add myserver -- uvx my-mcp-server

# 添加项目级服务器
python -m minicode.main mcp add filesystem --project -- npx -y @modelcontextprotocol/server-filesystem .

# 移除服务器
python -m minicode.main mcp remove myserver
```

### Skills

```bash
# 列出所有技能
python -m minicode.main skills list

# 添加技能
python -m minicode.main skills add ~/skills/frontend-dev --name frontend-dev

# 移除技能
python -m minicode.main skills remove frontend-dev
```

---

## 🎯 使用示例

### 示例 1: 简单问答

```
> 解释一下什么是递归

assistant
  递归是一种编程技术，函数在其中调用自身...
```

### 示例 2: 文件操作

```
> 读取 README.md 并总结

tool read_file running
  path=README.md
  
tool read_file ok
  文件内容...

assistant
  README.md 的主要内容是...
```

### 示例 3: 代码修改

```
> 把 main.py 中的所有 print 改成 logging

Action Required              │ Permission
───────────────────────────────────────────
mini-code wants to apply a file modification

target: D:\project\main.py

--- a/main.py
+++ b/main.py
@@ -1,5 +1,6 @@
-print("Hello")
+import logging
+logging.info("Hello")

 1 apply once (1) 
 2 allow this file in this turn (2) 
 3 allow all edits in this turn (3) 
 4 always allow this file (4) 
 5 reject once (5) 
 6 reject and send guidance to model (6) 
 7 always reject this file (7)
```

---

## ⚙️ 配置

### 配置文件优先级

1. `~/.mini-code/settings.json` - 用户级设置
2. `~/.mini-code/mcp.json` - 用户级 MCP 配置
3. `.mcp.json` - 项目级 MCP 配置
4. 环境变量

### 示例配置

`~/.mini-code/settings.json`:

```json
{
  "model": "claude-sonnet-4-20250514",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "your-token-here",
    "ANTHROPIC_MODEL": "claude-sonnet-4-20250514"
  }
}
```

---

## 🧪 测试模式

### Mock 模式

无需 API 密钥，用于测试和开发：

```bash
# Windows
set MINI_CODE_MODEL_MODE=mock
python -m minicode.main

# Unix/Linux/macOS
export MINI_CODE_MODEL_MODE=mock
python -m minicode.main
```

Mock 模式会：
- 使用内置的模拟模型
- 响应固定的测试消息
- 支持所有工具调用
- 完整测试 TUI 功能

### 运行测试

```bash
cd py-src
python -m pytest tests/ -v
```

---

## 📊 状态指示器

底部状态栏显示：

```
tools on | skills on
```

- **tools**: 工具系统状态（on/off）
- **skills**: 技能系统状态（on/off）
- **bg**: 后台任务数量（如有）

---

## 🐛 故障排除

### 问题：启动报错 "No model configured"

**解决**: 运行安装向导或手动配置：

```bash
python -m minicode.main --install
```

或创建 `~/.mini-code/settings.json`：

```json
{
  "model": "your-model",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "your-token"
  }
}
```

### 问题：TUI 显示异常

**解决**: 确保终端支持：
- 最小 80x24 字符
- 支持 ANSI 转义序列
- Windows 10+ 推荐使用 Windows Terminal

### 问题：会话无法恢复

**解决**: 检查会话文件：

```bash
ls ~/.mini-code/sessions/
cat ~/.mini-code/sessions_index.json
```

---

## 📚 更多资源

- [架构说明](../ts-src/ARCHITECTURE_ZH.md)
- [贡献指南](../ts-src/CONTRIBUTING_ZH.md)
- [路线图](../ts-src/ROADMAP_ZH.md)
- [Claude Code 设计模式](../ts-src/CLAUDE_CODE_PATTERNS_ZH.md)

---

## 🎉 享受使用！

MiniCode Python 是一个轻量级但功能完整的终端编码助手。

**主要特性**:
- ✅ 完整的 Agent Loop
- ✅ 强大的 TUI 交互
- ✅ 会话持久化与恢复
- ✅ 权限管理系统
- ✅ MCP 集成
- ✅ Skills 系统
- ✅ 零外部依赖

有问题？欢迎反馈！
