"""Task tool — spawn a sub-agent to handle complex multi-step tasks.

Inspired by Claude Code's Task tool which launches an independent agent loop
with its own context window, isolated from the main conversation.

The sub-agent runs a full agent loop (model + tools) with:
- Its own system prompt tailored to the task type
- A filtered tool set based on the agent type
- A turn limit to prevent runaway execution
- Result summarized back into the parent context
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from minicode.agent_loop import run_agent_turn
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# Agent type definitions
# ---------------------------------------------------------------------------

AGENT_TYPES = {
    "explore": {
        "name": "Explore",
        "description": "Fast, read-only agent for codebase exploration and search",
        "system_prompt": (
            "You are an exploration agent. Your job is to quickly search and "
            "understand codebases. You should be fast and focused on finding "
            "relevant files and understanding structure. "
            "You can only use read-only tools. "
            "When done, provide a concise summary of your findings."
        ),
        "allowed_tools": {"read_file", "list_files", "grep_files", "file_tree", "find_symbols", "find_references", "get_ast_info"},
        "max_turns": 5,
    },
    "plan": {
        "name": "Plan",
        "description": "Thorough agent for gathering context and understanding code",
        "system_prompt": (
            "You are a planning agent. Your job is to thoroughly understand "
            "the codebase and task before acting. Read multiple files, trace "
            "code paths, and build a complete mental model. "
            "You can only use read-only tools. "
            "When done, provide a detailed analysis with actionable recommendations."
        ),
        "allowed_tools": {"read_file", "list_files", "grep_files", "file_tree", "find_symbols", "find_references", "get_ast_info", "code_review"},
        "max_turns": 8,
    },
    "general": {
        "name": "General",
        "description": "Full-featured agent for complex multi-step tasks",
        "system_prompt": (
            "You are a general-purpose coding agent. You can read, write, "
            "and modify code. Follow best practices and explain your changes. "
            "Break complex tasks into smaller steps. "
            "When done, provide a summary of what you did and any important findings."
        ),
        "allowed_tools": None,  # None = all tools allowed
        "max_turns": 15,
    },
}


def _validate(input_data: dict) -> dict:
    description = input_data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description is required")
    
    agent_type = input_data.get("agent_type", "general")
    if agent_type not in AGENT_TYPES:
        valid = ", ".join(AGENT_TYPES.keys())
        raise ValueError(f"agent_type must be one of: {valid}. Got: {agent_type}")
    
    return {
        "description": description.strip(),
        "agent_type": agent_type,
        "prompt": input_data.get("prompt", description.strip()),
    }


def _run(input_data: dict, context) -> ToolResult:
    """Execute a sub-agent task.
    
    This creates an isolated agent loop with:
    - Its own message history (system + task prompt)
    - Filtered tools based on agent type
    - A turn limit
    - Result summarized for the parent context
    """
    from minicode.model_registry import create_model_adapter
    from minicode.context_manager import ContextManager
    from minicode.permissions import PermissionManager
    from minicode.tools import create_default_tool_registry
    
    agent_type = input_data["agent_type"]
    agent_def = AGENT_TYPES[agent_type]
    task_prompt = input_data["prompt"]
    
    # Try to get the model from context or fall back to creating one
    # The context object carries runtime info needed for the model adapter
    runtime = None
    model = None
    
    # Attempt to extract runtime from the ToolContext
    if hasattr(context, '_runtime') and context._runtime:
        runtime = context._runtime
    
    if not runtime:
        # Try loading from config
        try:
            from minicode.config import load_runtime_config
            runtime = load_runtime_config(context.cwd)
        except Exception:
            pass
    
    if not runtime:
        return ToolResult(
            ok=False,
            output="Cannot run sub-agent: no model configuration available. Set ANTHROPIC_API_KEY and ANTHROPIC_MODEL."
        )
    
    # Create a filtered tool registry for this agent type
    full_tools = create_default_tool_registry(context.cwd, runtime=runtime)
    allowed = agent_def["allowed_tools"]
    
    if allowed is not None:
        filtered_tools = [t for t in full_tools.list() if t.name in allowed]
        from minicode.tooling import ToolRegistry
        tools = ToolRegistry(filtered_tools)
    else:
        tools = full_tools
    
    # Create model adapter
    model = create_model_adapter(
        model=runtime.get("model", ""),
        tools=tools,
        runtime=runtime,
    )
    
    # Create isolated permissions (no prompts — auto-deny writes for read-only agents)
    if agent_def["allowed_tools"] is not None:
        # Read-only agent: create permission manager that denies writes
        sub_permissions = PermissionManager(context.cwd, prompt=None)
    else:
        # General agent: inherit parent's permission prompt handler
        sub_permissions = PermissionManager(context.cwd, prompt=getattr(context.permissions, 'prompt', None))
    
    # Build isolated message list
    sub_messages = [
        {
            "role": "system",
            "content": agent_def["system_prompt"]
            + f"\n\nCurrent cwd: {context.cwd}"
            + "\n\nIMPORTANT: When you have completed your task, end with <final> and provide your findings."
            + " Do not ask the user questions — work autonomously with the tools available."
            + " Be concise and focused."
        },
        {
            "role": "user",
            "content": task_prompt,
        },
    ]
    
    # Run the sub-agent loop
    start_time = time.time()
    max_turns = agent_def["max_turns"]
    
    try:
        result_messages = run_agent_turn(
            model=model,
            tools=tools,
            messages=sub_messages,
            cwd=context.cwd,
            permissions=sub_permissions,
            max_steps=max_turns,
        )
    except Exception as e:
        return ToolResult(
            ok=False,
            output=f"Sub-agent ({agent_def['name']}) failed: {type(e).__name__}: {e}"
        )
    
    elapsed = time.time() - start_time
    
    # Extract the final assistant message as the result
    final_message = None
    for msg in reversed(result_messages):
        if msg.get("role") == "assistant" and msg.get("content", "").strip():
            final_message = msg["content"]
            break
    
    if not final_message:
        final_message = "(sub-agent completed without a final message)"
    
    # Build summary
    tool_calls_count = sum(1 for m in result_messages if m.get("role") == "assistant_tool_call")
    user_messages_count = sum(1 for m in result_messages if m.get("role") == "user")
    
    header = (
        f"[Sub-agent {agent_def['name']} completed]\n"
        f"  Type: {agent_type}\n"
        f"  Turns: {user_messages_count} (tool calls: {tool_calls_count})\n"
        f"  Duration: {elapsed:.1f}s\n"
        f"  Max turns: {max_turns}\n"
    )
    
    # Truncate very long results
    result_text = final_message
    MAX_RESULT_LEN = 8000
    if len(result_text) > MAX_RESULT_LEN:
        result_text = result_text[:MAX_RESULT_LEN] + f"\n\n... (truncated, {len(final_message)} chars total)"
    
    return ToolResult(ok=True, output=header + "\n" + result_text)


task_tool = ToolDefinition(
    name="task",
    description=(
        "Launch a sub-agent to handle a complex task autonomously. "
        "The sub-agent runs in its own isolated context with a turn limit. "
        "Use 'explore' for fast read-only codebase exploration, "
        "'plan' for thorough analysis, or 'general' for full-featured multi-step work. "
        "The sub-agent's final result is returned to you."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short 3-5 word description of the task",
            },
            "prompt": {
                "type": "string",
                "description": "Full task description for the sub-agent. If not provided, uses 'description'.",
            },
            "agent_type": {
                "type": "string",
                "enum": ["explore", "plan", "general"],
                "description": "Type of sub-agent: 'explore' (fast, read-only), 'plan' (thorough, read-only), 'general' (full tools, default)",
            },
        },
        "required": ["description"],
    },
    validator=_validate,
    run=_run,
)
