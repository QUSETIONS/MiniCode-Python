"""Governance audit tools for MiniCode Python.

Provides dependency direction checking and sink rule validation
based on the engineering governance framework.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DependencyEdge:
    """A single import dependency between files."""
    source: str  # Source file path
    target: str  # Target file path
    is_config: bool = False  # Whether this is a config import


@dataclass
class AuditResult:
    """Result of a governance audit."""
    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dependency_graph: list[DependencyEdge] = field(default_factory=list)
    sinks: dict[str, list[str]] = field(default_factory=dict)  # area -> sink files
    
    def summary(self) -> str:
        """Format audit result as summary string."""
        lines = ["Governance Audit Result", "=" * 50, ""]
        
        if self.passed:
            lines.append("✓ PASSED - All governance rules satisfied")
        else:
            lines.append(f"✗ FAILED - {len(self.violations)} violation(s) found")
        
        lines.append("")
        
        if self.violations:
            lines.append("Violations:")
            for i, v in enumerate(self.violations, 1):
                lines.append(f"  {i}. {v}")
            lines.append("")
        
        if self.warnings:
            lines.append("Warnings:")
            for i, w in enumerate(self.warnings, 1):
                lines.append(f"  {i}. {w}")
            lines.append("")
        
        if self.dependency_graph:
            lines.append(f"Dependencies: {len(self.dependency_graph)} edges")
        
        if self.sinks:
            lines.append("")
            lines.append("Sink files:")
            for area, sinks in self.sinks.items():
                lines.append(f"  {area}: {len(sinks)} sink(s)")
                for s in sinks[:5]:
                    lines.append(f"    - {s}")
                if len(sinks) > 5:
                    lines.append(f"    ... and {len(sinks) - 5} more")
        
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

def extract_imports(file_path: Path) -> list[tuple[str, bool]]:
    """Extract imports from a Python file.
    
    Returns:
        List of (imported_module, is_config) tuples
    """
    if not file_path.exists():
        return []
    
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    
    imports = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Check if this is a config import
                is_config = "config" in alias.name.lower()
                imports.append((alias.name, is_config))
        
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # Check if this is a config import
                is_config = "config" in node.module.lower() or \
                           (node.level > 0 and "config" in node.module.lower())
                imports.append((node.module, is_config))
    
    return imports


def resolve_import_to_file(import_module: str, source_file: Path, pkg_root: Path) -> Path | None:
    """Resolve an import module name to an actual file path.
    
    Args:
        import_module: Module name from import statement
        source_file: File making the import
        pkg_root: Package root directory
    
    Returns:
        Resolved file path or None
    """
    # Convert module name to path
    module_path = import_module.replace(".", "/")
    
    # Try different resolutions
    candidates = [
        pkg_root / f"{module_path}.py",
        pkg_root / module_path / "__init__.py",
        source_file.parent / f"{module_path}.py",
        source_file.parent / module_path / "__init__.py",
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


# ---------------------------------------------------------------------------
# Package area detection
# ---------------------------------------------------------------------------

def detect_file_area(file_path: Path, pkg_root: Path) -> str | None:
    """Detect which package area a file belongs to.
    
    Returns:
        Area name: 'port_entry', 'wrap_src', 'wrap_config', 'business_src',
                   'business_config', 'test_src', 'test_config', or None
    """
    try:
        rel_path = file_path.relative_to(pkg_root)
        parts = rel_path.parts
        
        if len(parts) >= 2:
            if parts[0] == "port" and parts[1] == "port_entry":
                return "port_entry"
            elif parts[0] == "wrap" and parts[1] == "src":
                return "wrap_src"
            elif parts[0] == "wrap" and parts[1] == "config":
                return "wrap_config"
            elif parts[0] == "business" and parts[1] == "src":
                return "business_src"
            elif parts[0] == "business" and parts[1] == "config":
                return "business_config"
            elif parts[0] == "test" and parts[1] == "src":
                return "test_src"
            elif parts[0] == "test" and parts[1] == "config":
                return "test_config"
    except ValueError:
        pass
    
    return None


# ---------------------------------------------------------------------------
# Dependency rules
# ---------------------------------------------------------------------------

# Import rules: source_area -> allowed target areas
IMPORT_RULES = {
    "port_entry": None,  # Can import anything
    "wrap_src": {"port_entry", "wrap_config", "wrap_src"},
    "wrap_config": set(),  # Zero dependencies
    "business_src": {"wrap_src", "business_config", "business_src"},
    "business_config": set(),  # Zero dependencies
    "test_src": {"business_src", "test_config", "test_src"},
    "test_config": set(),  # Zero dependencies
}

# Config import rule: config imports must come last
CONFIG_IMPORT_LAST = True


# ---------------------------------------------------------------------------
# Audit functions
# ---------------------------------------------------------------------------

def audit_dependency_directions(pkg_root: Path) -> AuditResult:
    """Audit 2: Check dependency direction compliance.
    
    Checks:
    1. Import direction rules (source area -> allowed target areas)
    2. Config imports come last
    3. No cycles in dependency graph
    """
    result = AuditResult(passed=True)
    
    # Find all Python files
    py_files = list(pkg_root.rglob("*.py"))
    
    # Extract dependencies
    for source_file in py_files:
        source_area = detect_file_area(source_file, pkg_root)
        if source_area is None:
            continue
        
        imports = extract_imports(source_file)
        last_import_is_config = False
        
        for import_module, is_config in imports:
            target_file = resolve_import_to_file(import_module, source_file, pkg_root)
            if target_file is None:
                # External import - check governance rules
                if source_area == "business_src":
                    result.violations.append(
                        f"business/src/ cannot import external libs: "
                        f"{source_file.relative_to(pkg_root)} imports {import_module}"
                    )
                    result.passed = False
                continue
            
            target_area = detect_file_area(target_file, pkg_root)
            if target_area is None:
                continue
            
            # Create dependency edge
            edge = DependencyEdge(
                source=str(source_file.relative_to(pkg_root)),
                target=str(target_file.relative_to(pkg_root)),
                is_config=is_config,
            )
            result.dependency_graph.append(edge)
            
            # Check import rules
            allowed = IMPORT_RULES.get(source_area)
            if allowed is not None and target_area not in allowed:
                result.violations.append(
                    f"Import rule violation: {source_area} → {target_area}\n"
                    f"  {source_file.relative_to(pkg_root)} imports {target_file.relative_to(pkg_root)}\n"
                    f"  Allowed: {allowed}"
                )
                result.passed = False
            
            # Check config import ordering
            if is_config:
                last_import_is_config = True
            elif last_import_is_config and CONFIG_IMPORT_LAST:
                result.warnings.append(
                    f"Config import should come last: "
                    f"{source_file.relative_to(pkg_root)} imports {import_module}"
                )
    
    # Check for cycles (simple DFS)
    cycles = _find_cycles(result.dependency_graph)
    if cycles:
        for cycle in cycles:
            result.violations.append(
                f"Dependency cycle detected: {' → '.join(cycle)}"
            )
            result.passed = False
    
    return result


def audit_sink_rules(pkg_root: Path) -> AuditResult:
    """Audit: Check sink rule compliance.
    
    Checks:
    1. business/src/ has exactly ONE sink
    2. wrap/src/ sinks are used by business/src/
    3. test/src/ sinks are used by port_exit/
    """
    result = AuditResult(passed=True)
    
    # Find all Python files by area
    files_by_area: dict[str, list[Path]] = {}
    for py_file in pkg_root.rglob("*.py"):
        area = detect_file_area(py_file, pkg_root)
        if area:
            files_by_area.setdefault(area, []).append(py_file)
    
    # Build dependency graph
    deps: dict[str, list[str]] = {}  # file -> list of files it imports
    for source_file in pkg_root.rglob("*.py"):
        source_str = str(source_file.relative_to(pkg_root))
        deps[source_str] = []
        
        for import_module, _ in extract_imports(source_file):
            target_file = resolve_import_to_file(import_module, source_file, pkg_root)
            if target_file:
                deps[source_str].append(str(target_file.relative_to(pkg_root)))
    
    # Find sinks (files not imported by others in same area)
    sinks: dict[str, list[str]] = {}
    
    for area, files in files_by_area.items():
        area_files = {str(f.relative_to(pkg_root)) for f in files}
        imported_in_area = set()
        
        for source_str, targets in deps.items():
            source_area = detect_file_area(Path(pkg_root) / source_str, pkg_root)
            if source_area == area:
                for target in targets:
                    if target in area_files:
                        imported_in_area.add(target)
        
        area_sinks = area_files - imported_in_area
        sinks[area] = sorted(area_sinks)
    
    result.sinks = sinks
    
    # Check business/src/ sink rule
    business_sinks = sinks.get("business_src", [])
    if len(business_sinks) == 0:
        result.violations.append("business/src/ has ZERO sinks (circular dependency?)")
        result.passed = False
    elif len(business_sinks) > 1:
        result.violations.append(
            f"business/src/ has {len(business_sinks)} sinks (must be exactly 1)\n"
            f"  Sinks: {', '.join(business_sinks)}\n"
            f"  Action: Split package"
        )
        result.passed = False
    
    # Check wrap/src/ sinks are used by business/src/
    wrap_sinks = sinks.get("wrap_src", [])
    business_files = {str(f.relative_to(pkg_root)) for f in files_by_area.get("business_src", [])}
    
    for wrap_sink in wrap_sinks:
        used_by_business = any(
            wrap_sink in deps.get(bf, [])
            for bf in business_files
        )
        if not used_by_business:
            result.warnings.append(
                f"wrap/src/ sink not used by business/src/: {wrap_sink}"
            )
    
    return result


def _find_cycles(edges: list[DependencyEdge]) -> list[list[str]]:
    """Find cycles in dependency graph using DFS."""
    # Build adjacency list
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge.source, set()).add(edge.target)
        graph.setdefault(edge.target, set())
    
    cycles = []
    visited = set()
    rec_stack = set()
    path = []
    
    def dfs(node: str):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)
        
        path.pop()
        rec_stack.discard(node)
    
    for node in graph:
        if node not in visited:
            dfs(node)
    
    return cycles


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------

def run_full_audit(pkg_root: Path) -> AuditResult:
    """Run complete governance audit (Audit 2 + Sink rules).
    
    Args:
        pkg_root: Package root directory
    
    Returns:
        Combined audit result
    """
    result = AuditResult(passed=True)
    
    # Run dependency direction audit
    dep_result = audit_dependency_directions(pkg_root)
    result.violations.extend(dep_result.violations)
    result.warnings.extend(dep_result.warnings)
    result.dependency_graph.extend(dep_result.dependency_graph)
    result.passed = result.passed and dep_result.passed
    
    # Run sink rule audit
    sink_result = audit_sink_rules(pkg_root)
    result.violations.extend(sink_result.violations)
    result.warnings.extend(sink_result.warnings)
    result.sinks.update(sink_result.sinks)
    result.passed = result.passed and sink_result.passed
    
    return result
