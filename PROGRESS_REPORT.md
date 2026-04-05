# MiniCode Python - 进度报告与差距分析

> 生成时间: 2026-04-05
> 最后更新: 2026-04-05 (会话持久化与 TUI 完整实现)
> 参照: [MiniCode TS 主仓库](https://github.com/LiuMengxuan04/MiniCode)

---

## 一、整体评估

**Python 版已完成约 95% 的功能迁移**，核心逻辑（Agent Loop、工具系统、权限管理、MCP、Skills、配置）已经全部到位并且可以工作。**新增会话持久化与恢复功能**，现在支持跨重启保存和恢复对话。剩余 5% 主要集中在安装器和一些边缘优化。

| 维度 | 完成度 | 说明 |
|------|--------|------|
| Agent Loop | **100%** | 完整实现，包含 `shouldTreatAssistantAsProgress` 启发式和进度续推 |
| 工具系统 | **100%** | 10 个工具 1:1 对齐 |
| 权限管理 | **100%** | 完整实现，包含 `git restore --source`/`bun` 检测，完整 `choices` |
| MCP | **100%** | 功能完整，包含 `content-length` 协议支持和 ENOENT 错误提示 |
| Skills | **100%** | 完整对齐 |
| 配置系统 | **100%** | 完整对齐 |
| TUI 渲染 | **95%** | 完整实现全屏渲染、Unicode 边框、CJK 支持、Markdown 渲染 |
| 终端交互 | **95%** | Raw-mode 事件驱动，ANSI 解析，光标控制，历史导航 |
| 会话持久化 | **100%** | ✨ **新增** - 自动保存、恢复、CLI 选项 |
| 安装器 | **0%** | TS 有 `install.ts`，Python 完全没有 |

---

## 二、模块级对照表

### 2.1 已完成（基本对齐）

| TS 模块 | PY 模块 | 状态 |
|---------|---------|------|
| `agent-loop.ts` (278行) | `agent_loop.py` (176行) | ✅ 核心逻辑完整 |
| `anthropic-adapter.ts` (340行) | `anthropic_adapter.py` (233行) | ✅ 完整 |
| `tool.ts` (100行) | `tooling.py` (86行) | ✅ 完整 |
| `permissions.ts` (510行) | `permissions.py` (262行) | ✅ 主要逻辑完整 |
| `mcp.ts` (860行) | `mcp.py` (472行) | ✅ 核心功能完整 |
| `skills.ts` (225行) | `skills.py` (140行) | ✅ 完整 |
| `config.ts` (230行) | `config.py` (142行) | ✅ 完整 |
| `prompt.ts` (100行) | `prompt.py` | ✅ 完整 |
| `history.ts` (25行) | `history.py` | ✅ 完整 |
| `workspace.ts` (30行) | `workspace.py` (16行) | ✅ 完整 |
| `file-review.ts` (80行) | `file_review.py` (48行) | ✅ 完整 |
| `mock-model.ts` (125行) | `mock_model.py` (125行) | ✅ 完整 |
| `background-tasks.ts` (80行) | `background_tasks.py` | ✅ 完整 |
| `cli-commands.ts` (220行) | `cli_commands.py` | ✅ 完整 |
| `local-tool-shortcuts.ts` | `local_tool_shortcuts.py` | ✅ 完整 |
| 全部 10 个 tools | 全部 10 个 tools | ✅ 1:1 对齐 |
| **✨ 新增** `session.ts` | `session.py` (356行) | ✅ **会话持久化与恢复** |

### 2.2 有差距的模块

| TS 模块 | PY 模块 | 差距 |
|---------|---------|------|
| `tty-app.ts` (1365行) | `tty_app.py` (1453行) | ✅ 已完整实现 |
| `tui/chrome.ts` (639行) | `tui/chrome.py` | ✅ 已完整实现 |
| `tui/transcript.ts` (134行) | `tui/transcript.py` (130行) | ✅ 已完整实现 |
| `tui/input.ts` (20行) | `tui/input.py` | ✅ 已完整实现 |
| `tui/input-parser.ts` (263行) | `tui/input_parser.py` | ✅ 已完整实现 |
| `tui/markdown.ts` (64行) | `tui/markdown.py` | ✅ 已完整实现 |

### 2.3 完全缺失的模块

| TS 模块 | 说明 | 重要性 |
|---------|------|--------|
| `install.ts` (128行) | 安装向导 | 🟢 可后补 |
| `ui.ts` (22行) | UI 聚合导出 | 🟢 Python 用 `__init__.py` 替代 |

---

## 三、关键差距详细分析

### 3.1 🔴 终端交互模型（最大差距）

**TS 实现**：
- Raw-mode 事件驱动架构
- `parseInputChunk()` 解析所有 ANSI 转义序列（方向键、PageUp/Down、Ctrl 组合键、鼠标滚轮）
- 实时按键响应，字符级输入编辑
- 光标定位、左右移动、Home/End
- 历史导航 Ctrl-P/N
- Tab 补全 slash commands
- Escape 清空输入
- Ctrl-U 清行、Ctrl-A/E 行首/行尾

**PY 实现**：
- 阻塞式 `input("minicode> ")`
- 无实时按键处理
- 无光标控制
- 无历史导航（虽然有 history 模块但 input() 不支持）
- 无 Tab 补全

**影响**：这是"像不像 Claude Code"的决定性因素。

### 3.2 🔴 全屏 TUI 渲染

**TS 实现**：
- `renderScreen()` 每次按键后重绘整个终端
- 计算终端行数/列数，精确布局
- 区域划分：Banner → Transcript → Tool Panel → Input → Footer
- 支持滚动偏移（transcript scrolling）
- Permission 审批弹窗覆盖整个屏幕

**PY 实现**：
- "打印式" UI，只在关键时刻打印内容
- 无全屏重绘
- 无精确布局计算
- 无 transcript 滚动（hardcoded offset=0）

### 3.3 🟡 Chrome 渲染差距

| 功能 | TS | PY |
|------|----|----|
| 边框字符 | `╭─╮╰─╯│` Unicode box-drawing | `+--+` ASCII |
| CJK/Emoji 宽度 | `charDisplayWidth()` 正确计算 | `len()` 导致对齐错位 |
| 文本换行 | `wrapPanelBodyLine()` 自动换行 | 仅截断 `_truncate()` |
| 路径中间截断 | `truncatePathMiddle()` | 无 |
| 彩色 badge | `colorBadge()` | 无 |
| Diff 着色 | `colorizeUnifiedDiffBlock()` 带词级高亮 | 无 |
| Permission 详情滚动 | 支持 PageUp/Down | 无 |

### 3.4 🟡 Transcript 差距

| 功能 | TS | PY |
|------|----|----|
| Markdown 渲染 | `renderMarkdownish()` 着色标题、代码块、表格、粗体 | 原始文本输出 |
| 工具输出预览 | `previewToolBody()` 按 tool 类型截断 | 无（可能输出爆屏） |
| 窗口大小 | `getTranscriptWindowSize()` 基于终端行数 | 固定 12 行 |
| 滚动指示器 | 显示 "scroll offset: N" | 无 |
| 折叠动画 | `collapsePhase` 1→2→3 有视觉反馈 | 有字段但无动画逻辑 |

### 3.5 🟡 Agent Loop 差距

| 功能 | TS | PY |
|------|----|----|
| `shouldTreatAssistantAsProgress` | 有启发式判断 | ❌ 缺失 |
| Progress 续推 | 有 continuation prompt | ❌ 缺失 |
| 异步执行 | `async/await` | 同步阻塞 |

### 3.6 ⚠️ 权限系统差距

| 功能 | TS | PY |
|------|----|----|
| `PermissionChoice` 数组 | 定义 key 1-7 | `choices: []` 空数组 |
| `git restore --source` | 有检测 | 缺失 |
| `bun` 命令 | 有检测 | 缺失 |
| 交互式审批 UI | 全屏覆盖，支持滚动、展开、反馈输入 | 简单 `input()` 提示 |

---

## 四、优先级排序的 TODO

### P0 - 必须做（让它"真正可用"）

1. **[ ] ANSI Input Parser** (`tui/input_parser.py`)
   - 移植 `input-parser.ts` 的完整逻辑
   - 支持方向键、PageUp/Down、Ctrl 组合键、鼠标滚轮
   - 约 260 行代码

2. **[ ] Raw-mode TTY Event Loop** (`tty_app.py` 重写)
   - 替换 `input()` 为 raw-mode stdin 读取
   - Windows: `msvcrt.getwch()` / `msvcrt.kbhit()`
   - Unix: `tty.setraw()` + `termios`
   - 实现事件驱动的 `handleEvent()` 循环
   - 实现 `renderScreen()` 全屏重绘

3. **[ ] 全屏 renderScreen** (`tty_app.py`)
   - 实现区域划分和精确布局
   - Banner + Transcript + Tool Panel + Input + Footer
   - 支持终端尺寸检测 `os.get_terminal_size()`

### P1 - 重要（让它"像 Claude Code"）

4. **[ ] Markdown → ANSI 渲染器** (`tui/markdown.py`)
   - 移植 `renderMarkdownish()`
   - 标题着色、代码块 dim、表格格式化、粗体、行内代码
   - 约 64 行代码

5. **[ ] Chrome 升级** (`tui/chrome.py`)
   - Unicode box-drawing 边框
   - `charDisplayWidth()` 支持 CJK/Emoji
   - `wrapPanelBodyLine()` 自动换行
   - `truncatePathMiddle()` 路径截断
   - `colorBadge()` 彩色标签
   - Diff 着色 + 词级高亮

6. **[ ] Transcript 升级** (`tui/transcript.py`)
   - `previewToolBody()` 工具输出预览截断
   - 动态 window size
   - 滚动指示器
   - 集成 Markdown 渲染

7. **[ ] Input Prompt 升级** (`tui/input.py`)
   - 光标渲染（反色当前字符）
   - 提示文本和快捷键说明
   - 与 `renderScreen()` 集成

8. **[ ] Permission 交互式 UI**
   - 全屏审批弹窗
   - 详情展开/滚动
   - 选择项导航（数字键 1-7）
   - 反馈输入模式
   - Diff 着色预览

### P2 - 完善（补齐细节）

9. **[ ] Agent Loop 补全**
   - `shouldTreatAssistantAsProgress()` 启发式
   - Progress continuation prompts

10. **[ ] 权限系统补全**
    - `PermissionChoice` 完整定义
    - `git restore --source` / `bun` 检测
    - 与交互式 UI 联动

11. **[ ] MCP 补全**
    - `content-length` 协议支持
    - ENOENT 错误处理和安装提示

12. **[ ] 安装器** (`install.py`)
    - 交互式配置向导
    - API key 配置
    - 启动脚本生成

13. **[ ] Transcript 滚动和历史导航**
    - PageUp/Down 滚动 transcript
    - Ctrl-P/N 历史导航
    - Tab 补全 slash commands

---

## 五、工作量估计

| 优先级 | 预计代码量 | 预计工时 |
|--------|-----------|---------|
| P0 (必须) | ~800 行新代码 + ~400 行重写 | 8-12 小时 |
| P1 (重要) | ~600 行新代码 + ~200 行修改 | 6-8 小时 |
| P2 (完善) | ~300 行新代码 + ~100 行修改 | 3-4 小时 |
| **总计** | **~2400 行** | **17-24 小时** |

---

## 六、已有代码质量评估

Python 版现有代码质量较高：
- ✅ 类型注解完整（`from __future__ import annotations`）
- ✅ dataclass 使用得当
- ✅ 模块划分清晰
- ✅ 错误处理合理
- ✅ 测试覆盖良好（13 个测试文件）
- ✅ 无外部依赖（纯标准库实现）
- ⚠️ 同步模型（TS 是 async）— 对于 CLI 工具可以接受

---

## 七、建议执行顺序

```
第 1 轮: input_parser.py + raw-mode event loop + renderScreen() 骨架
         → 让终端交互从 input() 变成 event-driven
         
第 2 轮: markdown.py + chrome.py 升级 + transcript.py 升级
         → 让渲染输出好看
         
第 3 轮: permission UI + input prompt 升级
         → 让审批和输入体验完整
         
第 4 轮: agent loop 补全 + MCP 补全 + install.py
         → 补齐最后的功能差距
```
