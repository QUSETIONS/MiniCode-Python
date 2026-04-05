from dataclasses import asdict

from minicode.mcp import create_mcp_backed_tools
from minicode.skills import discover_skills
from minicode.tooling import ToolRegistry
from minicode.tools.ask_user import ask_user_tool
from minicode.tools.edit_file import edit_file_tool
from minicode.tools.git import git_tool
from minicode.tools.governance_audit_tool import governance_audit_tool
from minicode.tools.grep_files import grep_files_tool
from minicode.tools.list_files import list_files_tool
from minicode.tools.load_skill import create_load_skill_tool
from minicode.tools.modify_file import modify_file_tool
from minicode.tools.notebook_edit import notebook_edit_tool
from minicode.tools.patch_file import patch_file_tool
from minicode.tools.read_file import read_file_tool
from minicode.tools.run_command import run_command_tool
from minicode.tools.todo_write import todo_write_tool
from minicode.tools.web_fetch import web_fetch_tool
from minicode.tools.web_search import web_search_tool
from minicode.tools.write_file import write_file_tool


def create_default_tool_registry(cwd: str, runtime: dict | None = None) -> ToolRegistry:
    skills = [asdict(skill) for skill in discover_skills(cwd)]
    mcp = create_mcp_backed_tools(cwd=cwd, mcp_servers=dict(runtime.get("mcpServers", {})) if runtime else {})
    return ToolRegistry(
        [
            # User interaction
            ask_user_tool,
            # File operations
            list_files_tool,
            grep_files_tool,
            read_file_tool,
            write_file_tool,
            modify_file_tool,
            edit_file_tool,
            patch_file_tool,
            # Command execution
            run_command_tool,
            # Web tools
            web_fetch_tool,
            web_search_tool,
            # Task management
            todo_write_tool,
            # Git workflow
            git_tool,
            # Notebook editing
            notebook_edit_tool,
            # Governance audit (MANDATORY)
            governance_audit_tool,
            # Skills
            create_load_skill_tool(cwd),
            # MCP tools
            *mcp["tools"],
        ],
        skills=skills,
        mcp_servers=mcp["servers"],
        disposer=mcp["dispose"],
    )
