# MiniCode Python 功能完整性测试设计

## 概述

创建自动化集成测试套件，验证 MiniCode Python 经过七轮优化后的所有核心功能是否正常工作。

## 架构

测试脚本按顺序执行 7 个测试模块，模拟真实使用流程，生成详细的测试报告。

## 技术栈

- Python 3.11+
- pytest 框架
- tempfile（临时测试目录）
- pathlib（路径操作）

## 测试模块

### 模块 1：启动与配置验证

**测试内容**:
- 配置诊断命令 (`--validate-config`)
- 日志系统初始化 (`~/.mini-code/minicode.log`)
- 核心模块导入（main, logging_config, context_manager, memory）

**成功标准**:
- 所有模块导入无错误
- 日志文件创建成功
- 配置诊断输出包含 "Configuration Diagnostics"

### 模块 2：工具执行测试

**测试工具**:
- `list_files_tool` - 文件列表
- `read_file_tool` - 文件读取（含缓存）
- `grep_files_tool` - 文本搜索（含目录跳过）
- `run_command_tool` - 命令执行（含超时）

**成功标准**:
- 所有工具返回 `result.ok == True`
- 文件缓存正常工作（重复读取更快）
- grep 跳过 .git/node_modules 目录

### 模块 3：权限系统测试

**测试内容**:
- 路径访问控制（cwd 内允许，cwd 外拒绝）
- 命令审批（安全命令自动通过，危险命令需审批）
- 编辑审批（文件修改审批流程）

**成功标准**:
- cwd 内路径访问通过
- cwd 外路径访问拒绝（抛出 RuntimeError）
- 危险命令触发审批流程

### 模块 4：上下文管理测试

**测试内容**:
- Token 估算（中英文混合）
- 上下文统计（total_tokens, usage_percentage）
- 自动压缩触发（should_compact）
- 压缩执行（compact_messages）

**成功标准**:
- Token 估算准确（ASCII ~4 字符/token, CJK ~1.5 字符/token）
- 使用率计算正确
- 压缩后消息数减少

### 模块 5：记忆系统测试

**测试内容**:
- 记忆添加（User/Project/Local 三级）
- 记忆搜索（按关键词）
- 记忆注入（get_relevant_context）
- 记忆持久化（MEMORY.md 文件）

**成功标准**:
- 添加成功并返回 entry.id
- 搜索返回相关结果
- 上下文注入格式正确
- 文件持久化到磁盘

### 模块 6：帮助系统测试

**测试命令**:
- `/config` - 配置诊断
- `/context` - 上下文使用率
- `/memory` - 记忆系统状态
- `/help` - 帮助信息

**成功标准**:
- 每个命令返回预期输出
- 无异常抛出
- 输出格式可读

### 模块 7：错误恢复测试

**测试场景**:
- 配置错误（模型名缺失）→ 显示修复建议
- 工具失败（命令不存在）→ 显示错误引导
- 权限拒绝 → 显示审批提示

**成功标准**:
- 错误消息包含修复建议
- 无静默失败
- 日志记录错误详情

## 测试执行

```bash
# 运行所有测试
python tests/test_functional_completeness.py -v

# 运行特定模块
python tests/test_functional_completeness.py::test_startup_and_config -v
```

## 报告格式

```
================================================================================
MiniCode Python Functional Completeness Test Report
================================================================================

Test Summary
------------
Total Tests:     25
Passed:          25
Failed:          0
Skipped:         0
Pass Rate:       100%

Module Results
--------------
1. Startup & Config      ✅ 3/3 passed
2. Tool Execution        ✅ 4/4 passed
3. Permission System     ✅ 3/3 passed
4. Context Management    ✅ 4/4 passed
5. Memory System         ✅ 4/4 passed
6. Help System           ✅ 4/4 passed
7. Error Recovery        ✅ 3/3 passed

Performance Metrics
-------------------
Startup Time:        0.8s  (target: <2s)  ✅
Tool Response:       45ms  (target: <100ms) ✅
Memory Usage:        120MB (target: <200MB) ✅
Token Estimation:    479K ops/sec ✅
File Read (cached):  107ms/1000 ✅

Issues Found
------------
None ✅

================================================================================
Overall Status: ✅ ALL TESTS PASSED
================================================================================
```

## 文件结构

- 创建：`tests/test_functional_completeness.py` - 主测试文件
- 创建：`tests/fixtures/` - 测试固件（测试文件、配置）
- 修改：无（纯新增）
