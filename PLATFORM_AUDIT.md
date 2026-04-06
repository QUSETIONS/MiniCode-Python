# MiniCode Python 版 — Linux / macOS 平台适配审计

> 审计日期: 2026-04-06
> 审计范围: `minicode/` 下所有 `.py` 文件的跨平台兼容性

## 总结

**结论：代码已具备良好的跨平台框架，绝大部分平台分支已正确实现。**
发现 **3 个真正的 Bug**、**4 个潜在问题** 和 **2 个增强建议**。

---

## 🔴 真正的 Bug（必须修复）

### Bug 1: Unix raw mode 下 `sys.stdin.read(1)` 阻塞问题

**文件**: `tty_app.py:1366-1382`

```python
# 当前代码:
ready, _, _ = select.select([sys.stdin], [], [], 0.05)
if not ready:
    throttled.flush()
    continue
chunk = ""
while True:
    ready2, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready2:
        break
    ch = sys.stdin.read(1)  # ← 问题在这里
```

**问题**: `tty.setraw()` 把终端设为 raw mode，但 `sys.stdin` 的 Python 层缓冲仍然是行缓冲（或 8KB 块缓冲）。`sys.stdin.read(1)` 可能在 Python 的 `BufferedReader` 内部执行一次大的 `read(8192)`，然后只返回 1 个字节。在 raw mode 下这个底层 `read(8192)` 会阻塞直到有那么多字节可用（或者 EOF）——实际上不会，因为 raw mode 下 read syscall 在有任何字节时就返回，但关键是 **Python 的 `io.TextIOWrapper` 层会在 decode 时尝试读取完整的 UTF-8 多字节序列**。如果用户输入中文/Emoji（需要 3-4 字节的 UTF-8），第一个字节到达后 TextIOWrapper 可能尝试读取后续字节，如果后续字节因为时序原因稍有延迟，就可能短暂阻塞。

更根本的问题：**`sys.stdin` 在 raw mode 下应该使用 `sys.stdin.buffer.read(1)` 读取原始字节，然后自行拼接 UTF-8**。

**修复方案**:
```python
# 用 os.read() 读取原始字节，然后手动 decode
fd = sys.stdin.fileno()
chunk_bytes = os.read(fd, 4096)  # 非阻塞（raw mode下有数据就返回）
chunk = chunk_bytes.decode("utf-8", errors="replace")
```

### Bug 2: Unix raw mode 下 stdout 无法正常输出

**文件**: `tty_app.py` 全局

**问题**: `tty.setraw(sys.stdin.fileno())` 把 stdin 所在的 tty 设置为 raw mode，这同时影响了 stdout 的行为——**raw mode 会禁用 output postprocessing（`OPOST`）**，导致 `\n` 不再被自动翻译为 `\r\n`。结果是所有 `print()` / `sys.stdout.write()` 输出的换行会变成只有 LF 而没有 CR，文本会"阶梯式"偏移。

**修复方案**: 用 `tty.setcbreak()` 替代 `tty.setraw()`，或者手动设置 termios 属性，保留 `OPOST`:

```python
def __enter__(self) -> _RawModeContext:
    if sys.platform == "win32":
        ...
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(fd)
        # 使用 setcbreak 而非 setraw:
        # setcbreak 禁用行缓冲和 echo，但保留 output processing (OPOST)
        # 这样 \n → \r\n 的翻译仍然生效
        tty.setcbreak(fd)
    return self
```

或者如果需要更精细的控制（某些特殊键只有 raw mode 才能捕获）:

```python
import termios
fd = sys.stdin.fileno()
self._old_settings = termios.tcgetattr(fd)
new = termios.tcgetattr(fd)
# iflag: 关闭 ICRNL (CR→NL), IXON (flow control)
new[0] &= ~(termios.ICRNL | termios.IXON)
# lflag: 关闭 ECHO, ICANON (canonical mode), ISIG (signals from keys)
new[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
# oflag: 保留 OPOST (output processing, \n → \r\n)
# new[1] 不动 ← 这是关键！setraw() 会清掉 OPOST
# cc: VMIN=1, VTIME=0 (至少读1字节就返回)
new[6][termios.VMIN] = 1
new[6][termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSAFLUSH, new)
```

### Bug 3: `_read_raw_char()` / `_read_raw_chunk()` 在 Unix 下使用高层 `sys.stdin.read(1)` 而非底层读取

**文件**: `tty_app.py:749-784`

**问题**: 与 Bug 1 同源。`sys.stdin.read(1)` 经过 Python 的 TextIOWrapper 和 BufferedReader 层，在 raw mode 终端下行为不可靠。特别是：
- `select()` 报告 fd 可读，但 `sys.stdin.read(1)` 可能在 TextIOWrapper 内部阻塞
- 多字节 UTF-8 字符可能被截断
- `_read_raw_chunk()` 的 while 循环中 `select(..., 0)` 检测到无数据就 break，但此时 Python 内部缓冲区可能还有数据

**修复方案**: 统一使用 `os.read(fd, N)` 读原始字节:

```python
def _read_raw_chunk() -> str:
    if sys.platform == "win32":
        ...  # 保持不变
    else:
        fd = sys.stdin.fileno()
        import select
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            return ""
        data = os.read(fd, 4096)
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")
```

---

## 🟡 潜在问题（建议修复）

### 问题 1: `SIGWINCH` 信号处理可能与线程冲突

**文件**: `tty_app.py:1315-1327`

```python
if sys.platform != "win32":
    import signal as _signal
    def _on_sigwinch(_signum: int, _frame: Any) -> None:
        invalidate_terminal_size_cache()
        throttled.request()
    _prev_sigwinch = _signal.signal(_signal.SIGWINCH, _on_sigwinch)
```

**问题**: Python 的信号处理函数只能在主线程中设置。如果 `run_tty_app()` 不在主线程中调用（虽然通常不会），`signal.signal()` 会抛出 `ValueError: signal only works in main thread`。

**建议**: 加一个安全检查:

```python
if sys.platform != "win32" and threading.current_thread() is threading.main_thread():
    ...
```

### 问题 2: macOS 上 `os.get_terminal_size()` 在某些终端模拟器中可能返回 (0, 0)

**文件**: `tui/chrome.py:86`

**问题**: 在某些 macOS 终端（如通过 SSH 连接、或在 tmux 内 pane 刚创建时），`os.get_terminal_size()` 可能返回 `(0, 0)`。当前的 fallback `(100, 40)` 只在异常时触发，不覆盖 `(0, 0)` 的情况。

**建议**:
```python
ts = os.get_terminal_size()
cols, rows = ts.columns, ts.lines
if cols <= 0 or rows <= 0:
    _ts_cache = (100, 40)
else:
    _ts_cache = (cols, rows)
```

### 问题 3: shell 命令构建 — macOS 默认 shell 是 zsh 不是 bash

**文件**: `tools/run_command.py:154`

```python
return "bash", ["-lc", shell_command]
```

**问题**: macOS 从 Catalina (10.15) 起默认 shell 是 zsh。虽然 bash 仍然预装，但用 `bash -lc` 意味着：
1. 如果用户的 `.bashrc` / `.bash_profile` 未配置（因为用户用 zsh），某些环境变量可能缺失
2. 如果系统未安装 bash（极端情况，如容器），会直接报错

**建议**: 使用 `$SHELL` 或 `/bin/sh`:
```python
shell = os.environ.get("SHELL", "/bin/sh")
return shell, ["-lc", shell_command]
```

或者更保守地用 `/bin/sh`（POSIX 兼容）:
```python
return "/bin/sh", ["-c", shell_command]
```

注意 `-l` (login shell) 在 `/bin/sh` 上也有效，但行为因平台而异。

### 问题 4: MCP `allowed_system_dirs` 缺少常见 Linux 路径

**文件**: `mcp.py:65-75`

```python
allowed_system_dirs = [
    '/usr/bin', '/usr/local/bin', '/usr/sbin', '/opt',
    '/opt/homebrew/bin', '/opt/homebrew/sbin',  # macOS Homebrew (Apple Silicon)
    '/usr/local/Cellar',  # macOS Homebrew (Intel)
]
```

**缺少**:
- `/snap/bin` — Ubuntu Snap 包
- `/home/linuxbrew/.linuxbrew/bin` — Linux Homebrew
- `/usr/local/sbin` — 常见 sbin 路径
- `~/.local/bin` — pip install --user / pipx 安装路径
- `~/.cargo/bin` — Rust 工具链
- `~/.nvm/` — Node.js via nvm (变种路径)

**建议**: 扩展列表，或者改为更宽松的策略（只禁止已知危险的 shell，不限制可执行文件路径）。

---

## 🟢 已正确处理的跨平台分支

| 模块 | 平台分支 | 状态 |
|---|---|---|
| `tui/screen.py` | Windows VT processing 启用 | ✅ 正确，非 Windows 跳过 |
| `tty_app.py` | `_RawModeContext` Windows/Unix 分支 | ✅ 结构正确（但有 Bug 2） |
| `tty_app.py` | `_win_read_one_key()` Windows 专用 | ✅ 正确隔离 |
| `tty_app.py` | `SIGWINCH` 仅 Unix | ✅ 正确判断 |
| `background_tasks.py` | `_is_process_alive()` Windows ctypes / Unix kill(0) | ✅ 正确 |
| `mcp.py` | `CREATE_NO_WINDOW` 仅 Windows | ✅ 正确 |
| `mcp.py` | `close()` Windows taskkill / Unix SIGTERM+SIGKILL | ✅ 正确 |
| `tools/run_command.py` | `split_command_line()` posix=True/False | ✅ 正确 |
| `tools/run_command.py` | `_build_execution_command()` cmd/bash 分支 | ✅ 正确（但见问题 3） |
| `tools/run_command.py` | background process isolation flags | ✅ 正确 |
| `install.py` | 三平台 launcher script | ✅ 正确 |
| `install.py` | PATH 添加指引 (zshrc/bashrc/sysdm) | ✅ 正确 |
| `config.py` | `Path.home()` 跨平台 | ✅ 正确 |
| `workspace.py` | `Path.resolve()` 跨平台 | ✅ 正确 |
| `tui/input_parser.py` | 纯 ANSI 解析，平台无关 | ✅ 正确 |

---

## 💡 增强建议

### 建议 1: 添加 `TERM` 环境变量检测

在 `enter_alternate_screen()` 之前检测 `$TERM`。某些终端（如 `dumb`、`linux` console）不支持 alternate screen 或鼠标追踪，强制启用会导致乱码:

```python
def _term_supports_alt_screen() -> bool:
    term = os.environ.get("TERM", "")
    return term not in ("dumb", "linux", "")
```

### 建议 2: macOS 上 Homebrew Python 路径处理

`install.py:60` 中 `sys.executable` 在 macOS Homebrew 安装的 Python 下可能返回 symlink 路径如 `/opt/homebrew/bin/python3`。这没有错，但如果用户通过 pyenv / asdf 管理 Python 版本，`sys.executable` 可能指向 shim 而非真实路径。建议在 launcher script 中使用 `$(command -v python3)` 而非硬编码路径。

---

## 修复优先级

| 优先级 | 项目 | 影响 |
|---|---|---|
| **P0** | Bug 2: raw mode 禁用 OPOST → 输出阶梯式 | Linux/macOS 上完全无法正常使用 |
| **P0** | Bug 1 & 3: stdin.read(1) 替换为 os.read() | 多字节输入可能卡死 |
| **P1** | 问题 3: bash → $SHELL or /bin/sh | macOS 用户环境变量缺失 |
| **P2** | 问题 2: terminal size (0,0) 检测 | 边缘 case |
| **P2** | 问题 4: MCP 允许路径扩展 | 安全策略松紧度 |
| **P3** | 问题 1: SIGWINCH 线程安全 | 极端 case |
| **P3** | 建议 1 & 2 | 体验优化 |
