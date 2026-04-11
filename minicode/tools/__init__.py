from dataclasses import asdict

from minicode.mcp import create_mcp_backed_tools
from minicode.skills import discover_skills
from minicode.tooling import ToolRegistry
from minicode.tools.ask_user import ask_user_tool
from minicode.tools.archive_utils import (
    gzip_compress_tool, gzip_decompress_tool, tar_create_tool, tar_extract_tool,
    zip_create_tool, zip_extract_tool,
)
from minicode.tools.batch_ops import batch_copy_tool, batch_move_tool, batch_delete_tool
from minicode.tools.code_nav import find_symbols_tool, find_references_tool, get_ast_info_tool
from minicode.tools.code_review import code_review_tool
from minicode.tools.crypto_utils import current_time_tool, timestamp_tool, hash_tool, hmac_tool
from minicode.tools.csv_utils import csv_parse_tool, csv_create_tool
from minicode.tools.diff_viewer import diff_viewer_tool
from minicode.tools.edit_file import edit_file_tool
from minicode.tools.encoding_utils import base64_encode_tool, base64_decode_tool, url_encode_tool, url_decode_tool
from minicode.tools.file_tree import file_tree_tool
from minicode.tools.git import git_tool
from minicode.tools.grep_files import grep_files_tool
from minicode.tools.http_utils import http_request_tool
from minicode.tools.json_utils import json_format_tool, json_parse_tool
from minicode.tools.list_files import list_files_tool
from minicode.tools.load_skill import create_load_skill_tool
from minicode.tools.modify_file import modify_file_tool
from minicode.tools.patch_file import patch_file_tool
from minicode.tools.read_file import read_file_tool
from minicode.tools.regex_utils import regex_test_tool, regex_replace_tool
from minicode.tools.run_command import run_command_tool
from minicode.tools.test_runner import test_runner_tool
from minicode.tools.text_utils import (
    uuid_generate_tool, text_sort_tool, text_dedupe_tool, text_join_tool,
    line_count_tool, random_string_tool,
)
from minicode.tools.todo_write import todo_write_tool
from minicode.tools.web_fetch import web_fetch_tool
from minicode.tools.web_search import web_search_tool
from minicode.tools.write_file import write_file_tool
from minicode.tools.task import task_tool


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
            # Batch operations
            batch_copy_tool,
            batch_move_tool,
            batch_delete_tool,
            # Command execution
            run_command_tool,
            # Web tools
            web_fetch_tool,
            web_search_tool,
            http_request_tool,
            # Data processing
            json_format_tool,
            json_parse_tool,
            regex_test_tool,
            regex_replace_tool,
            # Encoding
            base64_encode_tool,
            base64_decode_tool,
            url_encode_tool,
            url_decode_tool,
            # Crypto & Time
            current_time_tool,
            timestamp_tool,
            hash_tool,
            hmac_tool,
            # Archive
            gzip_compress_tool,
            gzip_decompress_tool,
            tar_create_tool,
            tar_extract_tool,
            zip_create_tool,
            zip_extract_tool,
            # CSV
            csv_parse_tool,
            csv_create_tool,
            # Text utilities
            uuid_generate_tool,
            text_sort_tool,
            text_dedupe_tool,
            text_join_tool,
            line_count_tool,
            random_string_tool,
            # Task management
            todo_write_tool,
            # Sub-agent
            task_tool,
            # Git workflow
            git_tool,
            # Code intelligence
            find_symbols_tool,
            find_references_tool,
            get_ast_info_tool,
            code_review_tool,
            # Visualization
            file_tree_tool,
            diff_viewer_tool,
            # Testing
            test_runner_tool,
            # Skills
            create_load_skill_tool(cwd),
            # MCP tools
            *mcp["tools"],
        ],
        skills=skills,
        mcp_servers=mcp["servers"],
        disposer=mcp["dispose"],
    )
