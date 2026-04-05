from __future__ import annotations

import subprocess
import sys
import re
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# Docker Helpers
# ---------------------------------------------------------------------------

def _run_docker_command(args: list[str], timeout: int = 30) -> tuple[bool, str, str]:
    """Run a docker command and return result."""
    cmd = ["docker"] + args
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        success = result.returncode == 0
        return success, result.stdout.strip(), result.stderr.strip()
    
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout} seconds"
    except FileNotFoundError:
        return False, "", "Docker is not installed or not in PATH"
    except Exception as e:
        return False, "", str(e)


def _run_compose_command(args: list[str], timeout: int = 30, project_dir: str = ".") -> tuple[bool, str, str]:
    """Run a docker compose command."""
    cmd = ["docker", "compose"] + args
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_dir,
        )
        
        success = result.returncode == 0
        return success, result.stdout.strip(), result.stderr.strip()
    
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout} seconds"
    except FileNotFoundError:
        return False, "", "Docker Compose is not available"
    except Exception as e:
        return False, "", str(e)


def _format_container_list(containers: list[dict[str, Any]]) -> str:
    """Format container list for display."""
    if not containers:
        return "No containers found."
    
    lines = ["🐳 Docker Containers", "=" * 60, ""]
    
    # Calculate column widths
    id_width = max(12, max((len(c.get("id", "")[:12]) for c in containers), default=12))
    name_width = max(20, max((len(c.get("name", "")) for c in containers), default=20))
    status_width = max(20, max((len(c.get("status", "")) for c in containers), default=20))
    ports_width = max(15, max((len(c.get("ports", "")) for c in containers), default=15))
    
    # Header
    header = f"{'ID':<{id_width}} {'NAME':<{name_width}} {'STATUS':<{status_width}} {'PORTS':<{ports_width}} IMAGE"
    lines.append(header)
    lines.append("-" * len(header))
    
    # Rows
    for c in containers:
        container_id = c.get("id", "")[:12]
        name = c.get("name", "")
        status = c.get("status", "")
        ports = c.get("ports", "")
        image = c.get("image", "")
        
        line = f"{container_id:<{id_width}} {name:<{name_width}} {status:<{status_width}} {ports:<{ports_width}} {image}"
        lines.append(line)
    
    lines.append("")
    lines.append(f"Total: {len(containers)} container(s)")
    
    return "\n".join(lines)


def _parse_container_ps(output: str) -> list[dict[str, Any]]:
    """Parse docker ps output into structured data."""
    containers = []
    
    lines = output.strip().split('\n')
    if len(lines) < 2:
        return containers
    
    # Skip header line
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 7:
            containers.append({
                "id": parts[0],
                "image": parts[1],
                "command": ' '.join(parts[2:4]).strip('"'),
                "created": parts[4],
                "status": ' '.join(parts[5:7]),
                "name": parts[-1] if len(parts) > 7 else "",
                "ports": "",
            })
    
    return containers


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    action = input_data.get("action")
    if action not in ("ps", "logs", "exec", "compose_ps", "compose_logs", "compose_up", "compose_down", "info"):
        raise ValueError(f"action must be one of: ps, logs, exec, compose_ps, compose_logs, compose_up, compose_down, info")
    
    container = input_data.get("container")
    command = input_data.get("command")
    service = input_data.get("service")
    tail = int(input_data.get("tail", 100))
    timeout = int(input_data.get("timeout", 30))
    project_dir = input_data.get("project_dir", ".")
    follow = input_data.get("follow", False)
    
    if action in ("logs", "exec") and not container:
        raise ValueError(f"'container' is required when action is '{action}'")
    
    if action == "exec" and not command:
        raise ValueError("'command' is required when action is 'exec'")
    
    if action in ("compose_ps", "compose_logs", "compose_up", "compose_down") and not service:
        raise ValueError(f"'service' is required when action is '{action}'")
    
    if tail < 10 or tail > 1000:
        raise ValueError("tail must be between 10 and 1000")
    
    if timeout < 10 or timeout > 300:
        raise ValueError("timeout must be between 10 and 300 seconds")
    
    return {
        "action": action,
        "container": container,
        "command": command,
        "service": service,
        "tail": tail,
        "timeout": timeout,
        "project_dir": project_dir,
        "follow": follow,
    }


def _run(input_data: dict, context) -> ToolResult:
    """Manage Docker containers and compose services."""
    action = input_data["action"]
    container = input_data.get("container")
    command = input_data.get("command")
    service = input_data.get("service")
    tail = input_data["tail"]
    timeout = input_data["timeout"]
    project_dir = input_data.get("project_dir", ".")
    
    lines = ["🐳 Docker Helper", "=" * 60, ""]
    
    try:
        if action == "ps":
            # List containers
            success, stdout, stderr = _run_docker_command(
                ["ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Command}}\t{{.CreatedAt}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}"],
                timeout,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker ps failed: {stderr}")
            
            containers = _parse_container_ps(stdout)
            if containers:
                lines.append(_format_container_list(containers))
            else:
                lines.append("No containers running.")
        
        elif action == "logs":
            # View container logs
            success, stdout, stderr = _run_docker_command(
                ["logs", "--tail", str(tail), container],
                timeout,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker logs failed: {stderr}")
            
            lines.append(f"📝 Logs for container: {container}")
            lines.append(f"Last {tail} lines:")
            lines.append("")
            lines.append("-" * 60)
            lines.append(stdout)
        
        elif action == "exec":
            # Execute command in container
            cmd_parts = command.split()
            success, stdout, stderr = _run_docker_command(
                ["exec", container] + cmd_parts,
                timeout,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker exec failed: {stderr}")
            
            lines.append(f"✅ Command executed in container: {container}")
            lines.append(f"Command: {command}")
            lines.append("")
            if stdout:
                lines.append("Output:")
                lines.append(stdout[:3000])
        
        elif action == "compose_ps":
            # List compose services
            success, stdout, stderr = _run_compose_command(
                ["ps", "--format", "json"],
                timeout,
                project_dir,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker compose ps failed: {stderr}")
            
            lines.append(f"📦 Compose Services in {project_dir}")
            lines.append("")
            lines.append(stdout[:3000])
        
        elif action == "compose_logs":
            # View compose service logs
            success, stdout, stderr = _run_compose_command(
                ["logs", "--tail", str(tail), service],
                timeout,
                project_dir,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker compose logs failed: {stderr}")
            
            lines.append(f"📝 Logs for service: {service}")
            lines.append(f"Last {tail} lines:")
            lines.append("")
            lines.append("-" * 60)
            lines.append(stdout)
        
        elif action == "compose_up":
            # Start compose services
            success, stdout, stderr = _run_compose_command(
                ["up", "-d", service],
                timeout,
                project_dir,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker compose up failed: {stderr}")
            
            lines.append(f"✅ Service started: {service}")
            lines.append("")
            if stdout:
                lines.append(stdout)
        
        elif action == "compose_down":
            # Stop compose services
            success, stdout, stderr = _run_compose_command(
                ["down", service],
                timeout,
                project_dir,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker compose down failed: {stderr}")
            
            lines.append(f"✅ Service stopped: {service}")
            lines.append("")
            if stdout:
                lines.append(stdout)
        
        elif action == "info":
            # Show Docker system info
            success, stdout, stderr = _run_docker_command(
                ["info", "--format", "{{.ServerVersion}}\t{{.OperatingSystem}}\t{{.NCPU}} CPUs\t{{.MemTotal}}"],
                timeout,
            )
            
            if not success:
                return ToolResult(ok=False, output=f"❌ Docker info failed: {stderr}")
            
            lines.append("🐳 Docker System Info")
            lines.append("")
            lines.append(stdout)
    
    except Exception as e:
        return ToolResult(ok=False, output=f"❌ Error: {e}")
    
    return ToolResult(ok=True, output="\n".join(lines))


docker_helper_tool = ToolDefinition(
    name="docker_helper",
    description="Manage Docker containers and Compose services. View container logs, execute commands, start/stop services, and inspect Docker system info.",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ps", "logs", "exec", "compose_ps", "compose_logs", "compose_up", "compose_down", "info"],
                "description": "Action to perform",
            },
            "container": {"type": "string", "description": "Container name or ID (required for ps/logs/exec)"},
            "command": {"type": "string", "description": "Command to execute in container (required for exec)"},
            "service": {"type": "string", "description": "Service name (required for compose actions)"},
            "tail": {"type": "number", "description": "Number of log lines to show (default: 100)"},
            "timeout": {"type": "number", "description": "Timeout in seconds (default: 30)"},
            "project_dir": {"type": "string", "description": "Docker Compose project directory (default: current directory)"},
        },
        "required": ["action"],
    },
    validator=_validate,
    run=_run,
)
