from __future__ import annotations

import subprocess
import sys
import re
import os
from pathlib import Path
from typing import Any
from minicode.tooling import ToolDefinition, ToolResult


# ---------------------------------------------------------------------------
# Test Discovery
# ---------------------------------------------------------------------------

def _discover_test_files(path: Path, pattern: str = "test_*.py") -> list[Path]:
    """Discover test files matching pattern."""
    test_files = []
    
    if path.is_file():
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            test_files.append(path)
    elif path.is_dir():
        for root, dirs, files in os.walk(path):
            # Skip common non-test dirs
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "venv", "env", ".tox", "node_modules")]
            
            for f in files:
                if f.startswith("test_") and f.endswith(".py"):
                    test_files.append(Path(root) / f)
    
    return sorted(test_files)


# ---------------------------------------------------------------------------
# Test Output Parsers
# ---------------------------------------------------------------------------

def _parse_pytest_output(output: str) -> dict[str, Any]:
    """Parse pytest output into structured format."""
    results = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "warnings": 0,
        "tests": [],
        "failures": [],
        "coverage": None,
    }
    
    # Parse summary line
    summary_match = re.search(r'(\d+) passed', output)
    if summary_match:
        results["passed"] = int(summary_match.group(1))
    
    failed_match = re.search(r'(\d+) failed', output)
    if failed_match:
        results["failed"] = int(failed_match.group(1))
    
    error_match = re.search(r'(\d+) error', output)
    if error_match:
        results["errors"] = int(error_match.group(1))
    
    skipped_match = re.search(r'(\d+) skipped', output)
    if skipped_match:
        results["skipped"] = int(skipped_match.group(1))
    
    warning_match = re.search(r'(\d+) warning', output)
    if warning_match:
        results["warnings"] = int(warning_match.group(1))
    
    # Parse individual test results
    test_pattern = re.compile(r'(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(.+?)(?:::(\w+))?', re.MULTILINE)
    for match in test_pattern.finditer(output):
        status = match.group(1)
        file_path = match.group(2)
        test_name = match.group(3)
        
        results["tests"].append({
            "file": file_path.strip(),
            "name": test_name or "unknown",
            "status": status.lower(),
        })
    
    # Parse failure details
    failure_pattern = re.compile(r'FAILURES\s*\n(.*?)(?=\n={50,}|\Z)', re.DOTALL)
    failure_match = failure_pattern.search(output)
    if failure_match:
        results["failure_details"] = failure_match.group(1)[:2000]
    
    # Parse coverage if present
    coverage_pattern = re.compile(r'TOTAL\s+\d+\s+\d+\s+(\d+)%')
    coverage_match = coverage_pattern.search(output)
    if coverage_match:
        results["coverage"] = int(coverage_match.group(1))
    
    return results


def _parse_unittest_output(output: str) -> dict[str, Any]:
    """Parse unittest output into structured format."""
    results = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "tests": [],
        "failures": [],
    }
    
    # Parse summary
    summary_match = re.search(r'Ran (\d+) test', output)
    if summary_match:
        total = int(summary_match.group(1))
        if "OK" in output:
            results["passed"] = total
        else:
            failed_match = re.search(r'failures=(\d+)', output)
            error_match = re.search(r'errors=(\d+)', output)
            
            results["failed"] = int(failed_match.group(1)) if failed_match else 0
            results["errors"] = int(error_match.group(1)) if error_match else 0
            results["passed"] = total - results["failed"] - results["errors"]
    
    return results


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------

def _validate(input_data: dict) -> dict:
    path = input_data.get("path", ".")
    framework = input_data.get("framework", "auto")
    if framework not in ("auto", "pytest", "unittest"):
        raise ValueError("framework must be one of: auto, pytest, unittest")
    
    verbose = input_data.get("verbose", False)
    if not isinstance(verbose, bool):
        raise ValueError("verbose must be a boolean")
    
    coverage = input_data.get("coverage", False)
    if not isinstance(coverage, bool):
        raise ValueError("coverage must be a boolean")
    
    pattern = input_data.get("pattern")
    timeout = int(input_data.get("timeout", 60))
    if timeout < 10 or timeout > 300:
        raise ValueError("timeout must be between 10 and 300 seconds")
    
    return {
        "path": path,
        "framework": framework,
        "verbose": verbose,
        "coverage": coverage,
        "pattern": pattern,
        "timeout": timeout,
    }


def _run(input_data: dict, context) -> ToolResult:
    """Run tests with smart discovery and parsing."""
    target = Path(context.cwd) / input_data["path"]
    framework = input_data["framework"]
    verbose = input_data["verbose"]
    coverage = input_data["coverage"]
    pattern = input_data.get("pattern")
    timeout = input_data["timeout"]
    
    if not target.exists():
        return ToolResult(ok=False, output=f"Path not found: {target}")
    
    # Discover test files
    test_files = _discover_test_files(target)
    
    if not test_files:
        return ToolResult(
            ok=False,
            output=f"No test files found in {input_data['path']}\n\n"
                   f"Expected files matching: test_*.py or *_test.py",
        )
    
    # Apply pattern filter if provided
    if pattern:
        test_files = [f for f in test_files if pattern in f.name]
        if not test_files:
            return ToolResult(
                ok=False,
                output=f"No test files match pattern: {pattern}",
            )
    
    # Determine framework
    if framework == "auto":
        # Check if pytest is available
        try:
            subprocess.run(
                [sys.executable, "-m", "pytest", "--version"],
                capture_output=True,
                timeout=5,
            )
            framework = "pytest"
        except Exception:
            framework = "unittest"
    
    # Build command
    if framework == "pytest":
        cmd = [sys.executable, "-m", "pytest"]
        
        # Add test files
        cmd.extend([str(f) for f in test_files[:10]])  # Limit to 10 files
        
        if verbose:
            cmd.append("-v")
        
        if coverage:
            cmd.extend(["--cov", str(target)])
        
        # Add pattern
        if pattern:
            cmd.extend(["-k", pattern])
        
    else:  # unittest
        cmd = [sys.executable, "-m", "unittest", "discover"]
        cmd.extend(["-s", str(target)])
        
        if pattern:
            cmd.extend(["-p", f"*{pattern}*"])
        else:
            cmd.extend(["-p", "test_*.py"])
        
        if verbose:
            cmd.append("-v")
    
    # Run tests
    lines = [
        "🧪 Test Runner",
        "=" * 60,
        "",
        f"Framework: {framework}",
        f"Test files: {len(test_files)}",
        f"Pattern: {pattern or 'all'}",
        f"Coverage: {'enabled' if coverage else 'disabled'}",
        "",
        "-" * 60,
        "",
    ]
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(context.cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        output = result.stdout + "\n" + result.stderr
        success = result.returncode == 0
        
        # Parse results
        if framework == "pytest":
            parsed = _parse_pytest_output(output)
        else:
            parsed = _parse_unittest_output(output)
        
        # Format results
        lines.append("📊 Results:")
        lines.append(f"  ✓ Passed:  {parsed.get('passed', 0)}")
        lines.append(f"  ✗ Failed:  {parsed.get('failed', 0)}")
        lines.append(f"  ⚠ Errors:  {parsed.get('errors', 0)}")
        lines.append(f"  ⊘ Skipped: {parsed.get('skipped', 0)}")
        
        if parsed.get("coverage"):
            lines.append(f"  📈 Coverage: {parsed['coverage']}%")
        
        lines.append("")
        
        # Show failures
        if parsed.get("failed", 0) > 0 or parsed.get("errors", 0) > 0:
            lines.append("❌ Failures:")
            
            if parsed.get("failure_details"):
                lines.append(parsed["failure_details"][:2000])
            else:
                # Extract from output
                failure_pattern = re.compile(r'FAILURES\s*\n(.*?)(?=\n={50,}|\Z)', re.DOTALL)
                failure_match = failure_pattern.search(output)
                if failure_match:
                    lines.append(failure_match.group(1)[:2000])
            
            lines.append("")
        
        # Show warnings
        if parsed.get("warnings", 0) > 0:
            lines.append(f"⚠️  {parsed['warnings']} warning(s)")
            lines.append("")
        
        # Show test list if verbose
        if verbose and parsed.get("tests"):
            lines.append("📝 All Tests:")
            for test in parsed["tests"][:50]:  # Limit to 50
                icon = {"passed": "✓", "failed": "✗", "error": "⚠", "skipped": "⊘"}.get(test["status"], "?")
                lines.append(f"  {icon} {test['file']}::{test['name']}")
            if len(parsed["tests"]) > 50:
                lines.append(f"  ... and {len(parsed['tests']) - 50} more")
            lines.append("")
        
        # Full output if requested
        if verbose:
            lines.append("-" * 60)
            lines.append("")
            lines.append("Full Output:")
            lines.append(output[:5000])
            if len(output) > 5000:
                lines.append(f"\n... (output truncated)")
        
    except subprocess.TimeoutExpired:
        lines.append(f"❌ Tests timed out after {timeout} seconds")
        success = False
    except Exception as e:
        lines.append(f"❌ Test execution error: {e}")
        success = False
    
    return ToolResult(
        ok=success,
        output="\n".join(lines),
    )


test_runner_tool = ToolDefinition(
    name="test_runner",
    description="Discover and run Python tests automatically. Supports pytest and unittest frameworks. Provides structured results with pass/fail counts, failure details, and optional coverage reporting.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory or file path to test (default: current directory)"},
            "framework": {"type": "string", "enum": ["auto", "pytest", "unittest"], "description": "Test framework to use (default: auto)"},
            "verbose": {"type": "boolean", "description": "Show detailed output (default: false)"},
            "coverage": {"type": "boolean", "description": "Enable coverage reporting (default: false, requires pytest-cov)"},
            "pattern": {"type": "string", "description": "Filter tests by name pattern"},
            "timeout": {"type": "number", "description": "Timeout in seconds (default: 60, max: 300)"},
        },
    },
    validator=_validate,
    run=_run,
)
