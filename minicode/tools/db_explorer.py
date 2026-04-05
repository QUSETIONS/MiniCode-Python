from __future__ import annotations

import sqlite3
import re
from pathlib import Path
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# Database Explorer Helpers
# ---------------------------------------------------------------------------

def _parse_connection_string(conn_string: str) -> dict[str, Any]:
    """Parse database connection string."""
    # Support SQLite: sqlite:///path/to/db.db
    sqlite_match = re.match(r'sqlite:///(.+)', conn_string)
    if sqlite_match:
        return {
            "type": "sqlite",
            "path": sqlite_match.group(1),
        }
    
    # Support SQLite relative path: sqlite://db.db
    sqlite_relative = re.match(r'sqlite://(.+)', conn_string)
    if sqlite_relative:
        return {
            "type": "sqlite",
            "path": sqlite_relative.group(1),
            "relative": True,
        }
    
    return {"type": "unknown", "error": f"Unsupported connection string: {conn_string}"}


def _connect_to_db(conn_string: str, cwd: str) -> Any:
    """Connect to database based on connection string."""
    parsed = _parse_connection_string(conn_string)
    
    if parsed["type"] == "sqlite":
        db_path = Path(parsed["path"])
        if parsed.get("relative"):
            db_path = Path(cwd) / parsed["path"]
        
        if not db_path.exists():
            return None, f"Database file not found: {db_path}"
        
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn, None
        except Exception as e:
            return None, f"Connection failed: {e}"
    
    return None, f"Unsupported database type: {parsed['type']}"


def _get_table_list(conn: Any) -> list[str]:
    """Get list of all tables in database."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall()]


def _get_table_schema(conn: Any, table_name: str) -> list[dict[str, Any]]:
    """Get schema information for a table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    
    columns = []
    for row in cursor.fetchall():
        columns.append({
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5]),
        })
    
    return columns


def _get_table_row_count(conn: Any, table_name: str) -> int:
    """Get row count for a table."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    return cursor.fetchone()[0]


def _get_table_indexes(conn: Any, table_name: str) -> list[dict[str, Any]]:
    """Get indexes for a table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA index_list({table_name})")
    
    indexes = []
    for row in cursor.fetchall():
        indexes.append({
            "seq": row[0],
            "name": row[1],
            "unique": bool(row[2]),
        })
    
    return indexes


def _format_schema_output(tables: list[str], schemas: dict, row_counts: dict, indexes: dict) -> str:
    """Format database schema as readable output."""
    lines = ["📊 Database Schema", "=" * 60, ""]
    lines.append(f"Tables: {len(tables)}")
    lines.append("")
    
    for table_name in tables:
        lines.append(f"📁 {table_name}")
        lines.append(f"  Rows: {row_counts.get(table_name, 'N/A')}")
        lines.append("")
        
        # Columns
        columns = schemas.get(table_name, [])
        if columns:
            lines.append(f"  Columns:")
            for col in columns:
                pk_marker = " 🔑" if col["pk"] else ""
                nullable = "" if col["notnull"] else " (nullable)"
                default = f" = {col['default']}" if col["default"] is not None else ""
                lines.append(f"    {col['name']}: {col['type']}{pk_marker}{nullable}{default}")
        
        # Indexes
        table_indexes = indexes.get(table_name, [])
        if table_indexes:
            lines.append(f"")
            lines.append(f"  Indexes:")
            for idx in table_indexes:
                unique = "UNIQUE " if idx["unique"] else ""
                lines.append(f"    {unique}{idx['name']}")
        
        lines.append("")
        lines.append("-" * 60)
        lines.append("")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    connection = input_data.get("connection")
    if not isinstance(connection, str) or not connection:
        raise ValueError("connection is required")
    
    action = input_data.get("action", "explore")
    if action not in ("explore", "query", "schema"):
        raise ValueError("action must be one of: explore, query, schema")
    
    query = input_data.get("query")
    if action == "query" and (not isinstance(query, str) or not query.strip()):
        raise ValueError("query is required when action is 'query'")
    
    table = input_data.get("table")
    limit = int(input_data.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    
    return {
        "connection": connection,
        "action": action,
        "query": query,
        "table": table,
        "limit": limit,
    }


def _run(input_data: dict, context) -> ToolResult:
    """Explore database structure or run queries."""
    connection = input_data["connection"]
    action = input_data["action"]
    query = input_data.get("query")
    table = input_data.get("table")
    limit = input_data["limit"]
    cwd = context.cwd
    
    # Connect to database
    conn, error = _connect_to_db(connection, cwd)
    if error:
        return ToolResult(ok=False, output=f"❌ {error}")
    
    try:
        if action == "explore":
            # Get all tables with schema
            tables = _get_table_list(conn)
            
            if not tables:
                return ToolResult(
                    ok=True,
                    output="📭 Database exists but contains no tables.",
                )
            
            # Get schema for all tables
            schemas = {}
            row_counts = {}
            indexes = {}
            
            for table_name in tables:
                schemas[table_name] = _get_table_schema(conn, table_name)
                row_counts[table_name] = _get_table_row_count(conn, table_name)
                indexes[table_name] = _get_table_indexes(conn, table_name)
            
            output = _format_schema_output(tables, schemas, row_counts, indexes)
            return ToolResult(ok=True, output=output)
        
        elif action == "schema":
            # Get schema for specific table
            if not table:
                return ToolResult(
                    ok=False,
                    output="❌ 'table' parameter is required when action is 'schema'",
                )
            
            tables = _get_table_list(conn)
            if table not in tables:
                return ToolResult(
                    ok=False,
                    output=f"❌ Table '{table}' not found. Available tables: {', '.join(tables)}",
                )
            
            columns = _get_table_schema(conn, table)
            row_count = _get_table_row_count(conn, table)
            table_indexes = _get_table_indexes(conn, table)
            
            lines = [f"📁 Table Schema: {table}", "=" * 60, ""]
            lines.append(f"Rows: {row_count}")
            lines.append("")
            lines.append("Columns:")
            
            for col in columns:
                pk_marker = " 🔑" if col["pk"] else ""
                nullable = "" if col["notnull"] else " (nullable)"
                default = f" = {col['default']}" if col["default"] is not None else ""
                lines.append(f"  {col['name']}: {col['type']}{pk_marker}{nullable}{default}")
            
            if table_indexes:
                lines.append("")
                lines.append("Indexes:")
                for idx in table_indexes:
                    unique = "UNIQUE " if idx["unique"] else ""
                    lines.append(f"  {unique}{idx['name']}")
            
            return ToolResult(ok=True, output="\n".join(lines))
        
        elif action == "query":
            # Execute custom query
            if not query:
                return ToolResult(
                    ok=False,
                    output="❌ 'query' parameter is required when action is 'query'",
                )
            
            # Security: only allow SELECT statements
            if not query.strip().upper().startswith("SELECT"):
                return ToolResult(
                    ok=False,
                    output="❌ Only SELECT queries are allowed for safety.",
                )
            
            # Add LIMIT if not present
            if "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {limit}"
            
            try:
                cursor = conn.cursor()
                cursor.execute(query)
                rows = cursor.fetchall()
                columns = [description[0] for description in cursor.description]
                
            except Exception as e:
                return ToolResult(
                    ok=False,
                    output=f"❌ Query failed: {e}\n\nQuery: {query}",
                )
            
            # Format results
            lines = [f"📊 Query Results", "=" * 60, ""]
            lines.append(f"Rows returned: {len(rows)}")
            lines.append(f"Columns: {', '.join(columns)}")
            lines.append("")
            
            if rows:
                # Calculate column widths
                col_widths = {col: len(col) for col in columns}
                row_strs = []
                
                for row in rows[:50]:  # Limit display to 50 rows
                    row_dict = dict(row)
                    row_str = {col: str(row_dict.get(col, ""))[:50] for col in columns}
                    row_strs.append(row_dict)
                    
                    for col in columns:
                        col_widths[col] = max(col_widths[col], len(str(row_dict.get(col, ""))[:50]))
                
                # Print header
                header = " | ".join(col.ljust(min(col_widths[col], 20)) for col in columns)
                lines.append(header)
                lines.append("-" * len(header))
                
                # Print rows
                for row_dict in row_strs:
                    row_str = " | ".join(
                        str(row_dict.get(col, ""))[:50].ljust(min(col_widths[col], 20))
                        for col in columns
                    )
                    lines.append(row_str)
                
                if len(rows) > 50:
                    lines.append(f"\n... ({len(rows) - 50} more rows)")
            else:
                lines.append("(No rows returned)")
            
            return ToolResult(ok=True, output="\n".join(lines))
    
    finally:
        conn.close()


db_explorer_tool = ToolDefinition(
    name="db_explorer",
    description="Explore SQLite database structure and run read-only queries. Supports exploring all tables, viewing schemas, and executing SELECT queries with result formatting.",
    input_schema={
        "type": "object",
        "properties": {
            "connection": {"type": "string", "description": "Database connection string (e.g., 'sqlite:///app.db' or 'sqlite://app.db')"},
            "action": {"type": "string", "enum": ["explore", "schema", "query"], "description": "Action to perform (default: explore)"},
            "query": {"type": "string", "description": "SQL SELECT query (required when action is 'query')"},
            "table": {"type": "string", "description": "Table name (required when action is 'schema')"},
            "limit": {"type": "number", "description": "Maximum rows to return (default: 100, max: 1000)"},
        },
        "required": ["connection"],
    },
    validator=_validate,
    run=_run,
)
