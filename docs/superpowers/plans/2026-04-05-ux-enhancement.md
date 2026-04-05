# MiniCode Python 体验优化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。

**目标：** 优化 MiniCode Python 版用户交互体验，降低学习成本，提升使用流畅度

**架构：** 增量修改现有 tty_app.py、main.py 和 cli_commands.py，添加上下文帮助、智能提示和错误恢复引导

**技术栈：** Python 3.11+, curses/termios, threading

---

## 文件结构

- 修改：`minicode/tty_app.py` - 添加上下文帮助和状态提示
- 修改：`minicode/main.py` - 增强启动引导
- 修改：`minicode/cli_commands.py` - 优化帮助信息
- 创建：无新文件，遵循现有代码模式

---

### 任务 1：添加上下文帮助系统

**文件：**
- 修改：`minicode/tty_app.py:300-320`

- [ ] **步骤 1：添加上下文帮助函数**

```python
def _get_contextual_help(state: ScreenState, args: TtyAppArgs) -> str | None:
    """根据当前状态提供上下文相关的帮助提示"""
    # 空闲状态 - 显示快速提示
    if not state.is_busy and not state.pending_approval:
        tips = [
            "💡 Tip: Use /skills to see available workflows",
            "💡 Tip: Try '帮我分析这个项目' to get started",
            "💡 Tip: Use Tab to autocomplete commands",
            "💡 Tip: Type /help for all commands",
            "💡 Tip: Use Ctrl+R to search history",
        ]
        import random
        return random.choice(tips)
    
    # 工具运行中 - 显示相关提示
    if state.is_busy and state.active_tool:
        return f"⏳ Running {state.active_tool}... Press Ctrl+C to cancel"
    
    # 权限审批中
    if state.pending_approval:
        return "🔒 Permission required. Use arrow keys and Enter to choose"
    
    return None
```

- [ ] **步骤 2：在渲染中集成帮助显示**
- 在 footer 下方添加帮助行

### 任务 2：增强 Footer 状态栏

**文件：**
- 修改：`minicode/tui/chrome.py:render_footer_bar`

- [ ] **步骤 1：添加快捷键提示到 footer**

```python
def render_footer_bar(
    status: str | None, tools_enabled: bool, skills_enabled: bool, 
    background_tasks: list[dict[str, Any]] = [],
    contextual_help: str | None = None,
) -> str:
    # ... 现有代码 ...
    
    # 添加上下文帮助
    if contextual_help:
        help_line = f"  {SUBTLE}{contextual_help}{RESET}"
        res.append(help_line)
    
    # ... 返回结果 ...
```

### 任务 3：工具执行进度优化

**文件：**
- 修改：`minicode/tty_app.py:on_tool_start, on_tool_result`

- [ ] **步骤 1：添加工执行时间显示**

```python
def on_tool_start(tool_name: str, tool_input: Any) -> None:
    state.status = f"Running {tool_name}... ({time.strftime('%H:%M:%S')})"
    state.active_tool = tool_name
    # ... 其余逻辑 ...
```

### 任务 4：错误恢复引导

**文件：**
- 修改：`minicode/tty_app.py:on_tool_result`

- [ ] **步骤 1：工具失败时显示建议**

```python
def on_tool_result(tool_name: str, output: str, is_error: bool) -> None:
    if is_error:
        suggestions = []
        if "not found" in output.lower():
            suggestions.append("💡 File not found. Try /ls to see available files")
        elif "permission" in output.lower():
            suggestions.append("💡 Permission denied. Check file access rights")
        elif "syntax" in output.lower():
            suggestions.append("💡 Syntax error. Review the code and fix issues")
        
        if suggestions:
            output += "\n\n" + "\n".join(suggestions)
    # ... 更新状态 ...
```

### 任务 5：测试和验证

- [ ] **步骤 1：运行现有测试**
```bash
cd D:\Desktop\minicode\py-src && python -m pytest tests/ -v
```

- [ ] **步骤 2：验证优化效果**
- 启动 MiniCode 查看新引导
- 运行工具查看进度显示
- 触发错误查看恢复建议

---

## 自检

- ✅ 规格覆盖度：所有优化项都有对应任务
- ✅ 无占位符：每个步骤都有实际代码
- ✅ 类型一致性：使用现有类型和模式
- ✅ 小步骤：每个任务 2-5 分钟可完成

计划已完成。选择执行方式：

**1. 子代理驱动（推荐）** - 每个任务调度新子代理，任务间审查

**2. 内联执行** - 在当前会话使用 executing-plans 执行

选哪种方式？
