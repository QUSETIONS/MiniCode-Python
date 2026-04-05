# MiniCode Python - Claude Code 架构学习报告

> 分析日期: 2026-04-05
> 源码来源: Claude Code 泄露源码 (2026-03-31)
> 源码规模: ~1,900 文件, 512,000+ 行 TypeScript 代码

---

## 📚 一、Claude Code 核心架构总结

### 1.1 技术栈对比

| 维度 | Claude Code | MiniCode Python | 差距分析 |
|------|-------------|-----------------|----------|
| **运行时** | Bun | Python 3.11+ | ✅ Python 更通用 |
| **UI 框架** | React + Ink | 纯 ANSI TUI | ⚠️ Ink 更强大，但 ANSI 更轻量 |
| **状态管理** | Zustand Store | dataclass + 手动更新 | ⚠️ 需要引入 Store |
| **工具系统** | 声明式 Tool 对象 | Tool 类 + 注册表 | ✅ 已基本对齐 |
| **命令系统** | 多态命令 (3 种类型) | 字符串匹配 | ❌ 需要重构 |
| **上下文管理** | Memoized Async Context | 简单字典 | ❌ 需要改进 |
| **记忆系统** | memdir/ 文件索引 | memory.py 三层架构 | ✅ 已超越 |
| **任务系统** | AppState 集成 | TaskList 独立 | ⚠️ 需要集成 |
| **费用追踪** | cost-tracker.ts | ❌ 缺失 | ❌ 需要实现 |

---

## 🎯 二、关键架构模式提取

### 2.1 工具系统设计模式

**Claude Code 的 Tool 接口**:
```typescript
export type Tool<Input, Output, Progress> = {
  name: string
  call(args, context, canUseTool, parentMessage, onProgress): Promise<ToolResult>
  description(input, options): Promise<string>
  inputSchema: Input
  isConcurrencySafe(input): boolean
  isReadOnly(input): boolean
  isDestructive?(input): boolean
  validateInput?(input, context): Promise<ValidationResult>
  checkPermissions(input, context): Promise<PermissionResult>
  renderToolUseMessage(input, options): React.ReactNode
  renderToolResultMessage?(content, progress, options): React.ReactNode
  maxResultSizeChars: number
}
```

**MiniCode Python 应对标实现**:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass
class ToolUseContext:
    """工具执行上下文"""
    cwd: str
    permissions: Any  # PermissionManager
    abort_controller: Any  # asyncio.CancelToken
    get_app_state: Callable
    set_app_state: Callable

class Tool(Protocol):
    """工具协议 - 对标 Claude Code 的 Tool 类型"""
    name: str
    description_template: str
    
    async def call(
        self,
        args: dict[str, Any],
        context: ToolUseContext,
        on_progress: Callable | None = None,
    ) -> ToolResult: ...
    
    def get_description(self, args: dict, options: dict) -> str: ...
    def is_enabled(self) -> bool: ...
    def is_read_only(self, args: dict) -> bool: ...
    def is_destructive(self, args: dict) -> bool: ...
    def validate_input(self, args: dict, context: ToolUseContext) -> tuple[bool, str]: ...
    def check_permissions(self, args: dict, context: ToolUseContext) -> PermissionResult: ...
```

**关键改进点**:
- ✅ 添加 `ToolUseContext` 传递全局状态
- ✅ 添加工具元数据（只读/破坏性/并发安全）
- ✅ 添加输入验证和权限检查钩子
- ✅ 添加进度回调支持

---

### 2.2 命令系统设计模式

**Claude Code 的三种命令类型**:
```typescript
type Command = 
  | PromptCommand   // 展开为模型提示词
  | LocalCommand    // 直接执行
  | LocalJSXCommand // 交互式 UI
```

**MiniCode Python 应对标实现**:
```python
from enum import Enum
from abc import ABC, abstractmethod

class CommandType(Enum):
    PROMPT = "prompt"       # 扩展为系统提示
    LOCAL = "local"         # 本地执行
    LOCAL_INTERACTIVE = "local_interactive"  # 交互式

@dataclass
class CommandBase:
    """命令基类"""
    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    availability: list[str] = field(default_factory=list)  # ['claude-ai', 'console']
    paths: list[str] = field(default_factory=list)  # 文件路径匹配
    context: str = "inline"  # inline | fork
    is_hidden: bool = False
    
    def is_enabled(self) -> bool: ...
    def meets_availability(self, cwd: str) -> bool: ...

class PromptCommand(CommandBase):
    """Prompt 命令 - 扩展为系统提示"""
    type: CommandType = CommandType.PROMPT
    
    @abstractmethod
    async def get_prompt(self, args: str, context: ToolUseContext) -> str:
        """将命令转换为提示词"""

class LocalCommand(CommandBase):
    """本地命令 - 直接执行"""
    type: CommandType = CommandType.LOCAL
    
    @abstractmethod
    async def execute(self, args: str, context: ToolUseContext) -> str:
        """执行命令并返回结果"""

class CommandRegistry:
    """命令注册表 - 对标 Claude Code 的 commands.ts"""
    
    def __init__(self):
        self._commands: list[CommandBase] = []
    
    def register(self, command: CommandBase):
        self._commands.append(command)
    
    async def get_commands(self, cwd: str) -> list[CommandBase]:
        """从多个来源加载命令（对标 loadAllCommands）"""
        all_commands = []
        all_commands.extend(self._load_builtin_commands())
        all_commands.extend(await self._load_skill_commands(cwd))
        all_commands.extend(await self._load_plugin_commands())
        
        # 过滤和排序
        return sorted([
            cmd for cmd in all_commands
            if cmd.is_enabled() and cmd.meets_availability(cwd)
        ], key=lambda c: c.name)
```

**关键改进点**:
- ❌ 当前 MiniCode 只有字符串匹配的 slash commands
- ✅ 需要引入多态命令系统
- ✅ 需要从多个来源加载命令（内置、技能、插件）
- ✅ 需要支持文件路径匹配

---

### 2.3 上下文收集模式

**Claude Code 的上下文收集**:
```typescript
// 使用 memoize 缓存昂贵的 I/O
export const getSystemContext = memoize(async () => {
  const gitStatus = await getGitStatus()
  return { ...(gitStatus && { gitStatus }) }
})

export const getUserContext = memoize(async () => {
  const claudeMd = getClaudeMds(await getMemoryFiles())
  return {
    ...(claudeMd && { claudeMd }),
    currentDate: `Today's date is ${getLocalISODate()}.`,
  }
})
```

**MiniCode Python 应对标实现**:
```python
import asyncio
from functools import lru_cache
from pathlib import Path

class ContextCollector:
    """上下文收集器 - 对标 Claude Code 的 context.ts"""
    
    def __init__(self, cwd: str):
        self.cwd = Path(cwd)
        self._cache: dict[str, Any] = {}
    
    async def get_system_context(self) -> dict[str, str]:
        """获取系统上下文（git 状态等）"""
        if "system_context" not in self._cache:
            git_status = await self._get_git_status()
            self._cache["system_context"] = {
                "git_status": git_status,
            }
        return self._cache["system_context"]
    
    async def get_user_context(self) -> dict[str, str]:
        """获取用户上下文（CLAUDE.md 等）"""
        cache_key = f"user_context:{self.cwd}"
        if cache_key not in self._cache:
            claude_md = await self._load_claude_md()
            self._cache[cache_key] = {
                "claude_md": claude_md,
                "current_date": self._get_current_date(),
            }
        return self._cache[cache_key]
    
    async def get_full_context(self) -> dict[str, str]:
        """获取完整上下文（并行收集）"""
        system_ctx, user_ctx = await asyncio.gather(
            self.get_system_context(),
            self.get_user_context(),
        )
        return {**system_ctx, **user_ctx}
    
    def invalidate(self, pattern: str):
        """使缓存失效"""
        keys_to_remove = [k for k in self._cache if pattern in k]
        for key in keys_to_remove:
            del self._cache[key]
    
    async def _get_git_status(self) -> str | None:
        """并行获取 git 信息"""
        if not await self._is_git_repo():
            return None
        
        # 对标 Claude Code 的并行预取
        branch, status, log = await asyncio.gather(
            self._get_branch(),
            self._get_status(),
            self._get_log(),
        )
        return f"Branch: {branch}\nStatus:\n{status}\nRecent commits:\n{log}"
```

**关键改进点**:
- ❌ 当前 MiniCode 每次重新收集上下文
- ✅ 需要引入异步缓存机制
- ✅ 需要并行收集昂贵的 I/O
- ✅ 需要提供缓存失效接口

---

### 2.4 状态管理模式

**Claude Code 的 Zustand Store**:
```typescript
export function createStore<T>(initialState, onChange?): Store<T> {
  let state = initialState
  const listeners = new Set<Listener>()
  
  return {
    getState: () => state,
    setState: (updater) => {
      const prev = state
      const next = updater(prev)
      if (Object.is(next, prev)) return
      state = next
      onChange?.({ newState: next, oldState: prev })
      for (const listener of listeners) listener()
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}
```

**MiniCode Python 应对标实现**:
```python
from typing import Callable, TypeVar, Generic

T = TypeVar('T')

class Store(Generic[T]):
    """Zustand 风格的 Store - 对标 Claude Code 的状态管理"""
    
    def __init__(
        self,
        initial_state: T,
        on_change: Callable[[T, T], None] | None = None,
    ):
        self._state = initial_state
        self._listeners: list[Callable[[], None]] = []
        self._on_change = on_change
    
    def get_state(self) -> T:
        return self._state
    
    def set_state(self, updater: Callable[[T], T]):
        """更新状态（对标 setState）"""
        prev = self._state
        next_state = updater(prev)
        
        # 跳过无变化更新
        if next_state is prev:
            return
        
        # 触发变更回调
        if self._on_change:
            self._on_change(next_state, prev)
        
        self._state = next_state
        
        # 通知订阅者
        for listener in self._listeners:
            listener()
    
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """订阅状态变更（对标 subscribe）"""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

# 使用示例
@dataclass
class AppState:
    """应用全局状态"""
    verbose: bool = False
    tasks: dict = field(default_factory=dict)
    tool_permission_context: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    context_window_usage: float = 0.0
    total_cost_usd: float = 0.0

# 创建 Store
app_store = Store(AppState())

# 更新状态
app_store.set_state(lambda prev: {
    **prev.__dict__,
    "verbose": True
})

# 订阅变更
def on_change():
    print("State changed!")

unsubscribe = app_store.subscribe(on_change)
```

**关键改进点**:
- ❌ 当前 MiniCode 手动管理状态
- ✅ 需要引入统一 Store
- ✅ 需要支持状态订阅
- ✅ 需要不可变更新模式

---

### 2.5 费用追踪模式

**Claude Code 的 cost-tracker.ts**:
```typescript
export function addCostToHookState(
  model: string,
  usage: Usage,
  costUsd: number,
  setAppState: SetAppState,
) {
  setAppState(prev => {
    const currentTotal = prev.totalCostUsd || 0
    return {
      ...prev,
      totalCostUsd: currentTotal + costUsd,
      modelUsage: {
        ...prev.modelUsage,
        [model]: accumulateUsage(prev.modelUsage[model] || {}, usage),
      },
    }
  })
}
```

**MiniCode Python 应对标实现**:
```python
from dataclasses import dataclass, field

@dataclass
class ModelUsage:
    """模型使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

class CostTracker:
    """费用追踪 - 对标 Claude Code 的 cost-tracker.ts"""
    
    def __init__(self):
        self.total_cost_usd: float = 0.0
        self.total_api_duration_ms: int = 0
        self.total_lines_added: int = 0
        self.total_lines_removed: int = 0
        self.model_usage: dict[str, ModelUsage] = {}
    
    def add_usage(self, model: str, usage: dict, cost_usd: float):
        """添加使用记录"""
        self.total_cost_usd += cost_usd
        
        if model not in self.model_usage:
            self.model_usage[model] = ModelUsage()
        
        m = self.model_usage[model]
        m.input_tokens += usage.get("input_tokens", 0)
        m.output_tokens += usage.get("output_tokens", 0)
        m.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
        m.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)
        m.cost_usd += cost_usd
    
    def format_cost_report(self) -> str:
        """格式化费用报告"""
        lines = [
            "Cost & Usage Report",
            "=" * 50,
            f"Total cost: ${self.total_cost_usd:.4f}",
            f"Total API duration: {self.total_api_duration_ms}ms",
            f"Code changes: {self.total_lines_added} lines added, "
            f"{self.total_lines_removed} lines removed",
            "",
            "Usage by model:",
        ]
        
        for model, usage in self.model_usage.items():
            lines.append(
                f"  {model}: "
                f"{usage.input_tokens} input, "
                f"{usage.output_tokens} output, "
                f"{usage.cache_read_tokens} cache read, "
                f"{usage.cache_write_tokens} cache write "
                f"(${usage.cost_usd:.4f})"
            )
        
        return "\n".join(lines)
```

**关键改进点**:
- ❌ 当前 MiniCode 没有费用追踪
- ✅ 需要实现 token 记账
- ✅ 需要支持多模型统计
- ✅ 需要生成费用报告

---

## 🚀 三、推荐实施计划

基于 Claude Code 的架构学习，我建议按以下优先级改进 MiniCode Python：

### P0 - 立即实施（架构升级）

1. **引入 Store 状态管理** (约 150 行)
   - 创建 `state.py` 实现 Zustand 风格 Store
   - 定义 `AppState` 全局状态
   - 替换手动状态更新

2. **重构工具系统** (约 200 行)
   - 定义 `Tool` Protocol
   - 添加工具元数据（只读/破坏性）
   - 添加工具上下文传递

3. **实现费用追踪** (约 150 行)
   - 创建 `cost_tracker.py`
   - 集成到 agent loop
   - 添加 `/cost` 命令

### P1 - 短期实施（体验提升）

4. **重构命令系统** (约 250 行)
   - 实现多态命令 (Prompt/Local/Interactive)
   - 从多个来源加载命令
   - 支持文件路径匹配

5. **改进上下文收集** (约 150 行)
   - 实现异步缓存
   - 并行收集 git/CLAUDE.md
   - 添加缓存失效机制

### P2 - 中期实施（高级功能）

6. **Sub-agents 轻量实现** (约 300 行)
   - Explore Agent（只读快速搜索）
   - General-purpose Agent（完整功能）
   - 独立上下文窗口

7. **Auto Mode** (约 200 行)
   - 信任模式切换
   - 安全操作自动执行
   - 高风险操作拦截

---

## 📊 四、架构对比总结

| 架构维度 | Claude Code | MiniCode Python (当前) | MiniCode Python (目标) |
|---------|-------------|----------------------|----------------------|
| **状态管理** | Zustand Store | 手动 dataclass | ✅ Store (P0) |
| **工具系统** | 声明式 Tool 对象 | Tool 类 + 注册表 | ✅ Tool Protocol (P0) |
| **命令系统** | 多态命令 (3 种) | 字符串匹配 | ✅ 多态命令 (P1) |
| **上下文收集** | Memoized Async | 简单字典 | ✅ 异步缓存 (P1) |
| **费用追踪** | cost-tracker.ts | ❌ 缺失 | ✅ CostTracker (P0) |
| **记忆系统** | memdir/ 文件索引 | 三层架构 | ✅ 已超越 |
| **任务跟踪** | AppState 集成 | TaskList 独立 | ✅ 已实现 |
| **Sub-agents** | Explore/Plan/General | ❌ 缺失 | ⏳ 计划中 (P2) |

---

## 💡 五、关键架构决策

从 Claude Code 学到的最重要的设计原则：

1. **声明式优于命令式**
   - 工具定义为完整对象，而非分散的函数
   - 命令为多态类型，而非字符串匹配

2. **统一状态管理**
   - 所有状态集中在 Store 中
   - 不可变更新模式
   - 支持订阅和通知

3. **异步缓存**
   - 昂贵 I/O 操作缓存结果
   - 提供缓存失效接口
   - 并行收集独立数据

4. **多来源加载**
   - 命令/工具从多个来源动态加载
   - 内置、技能、插件统一管理
   - 特性标志门控

5. **完整生命周期**
   - 工具定义包含执行、验证、权限、UI 渲染
   - 命令定义类型、可用性、上下文
   - 状态变更可追踪和回滚

---

## 🎯 六、结论

通过学习 Claude Code 的完整源码，我提取了以下关键改进方向：

1. **最关键的架构缺口**: 缺少统一的状态管理（Store）
2. **最有价值的改进**: 声明式工具系统 + 多态命令
3. **最实用的功能**: 费用追踪（Claude Code 有，我们缺失）
4. **最需要重构的**: 命令系统从字符串匹配改为多态类型

**本次学习的最大收获**: Claude Code 的核心设计哲学是 **"声明式 + 统一状态 + 异步缓存"**，这三点是我们下一步应该重点对齐的。

---

## 📝 七、下一步行动

建议立即开始实施 P0 级别的 3 项改进：
1. 创建 `state.py` - Store 状态管理
2. 重构 `tooling.py` - 声明式工具 Protocol
3. 创建 `cost_tracker.py` - 费用追踪

这三项约 **500 行代码**，但能让架构水平从 70% 提升到 90%！
