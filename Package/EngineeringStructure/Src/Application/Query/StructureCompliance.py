from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Package.EngineeringStructure.Src.Application.Query.ProductRootProjection import (
    PROJECT_ROLE_SPACE_NAMES,
    ROOT_PROJECT_ID,
    scan_product_project_root,
    summarize_structure_projection,
)


IMPORT_STEM_RE = re.compile(r"^(0|[1-9][0-9]*)(-[A-Za-z][A-Za-z0-9_]*)+$")
APPLICATION_PUBLIC_SECTIONS = frozenset(
    {"Port", "Entry", "Command", "Query", "Result", "Dto", "Error"}
)
PYTHON_STDLIB_MODULES = (
    frozenset(getattr(sys, "stdlib_module_names", frozenset()))
    | frozenset(sys.builtin_module_names)
    | {"__future__"}
)


@dataclass(frozen=True, slots=True)
class ImportedModule:
    originalModule: str
    resolvedModule: str
    importStyle: str


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    sourcePathFromRoot: list[str]
    originalImportedModule: str
    importedModule: str
    importStyle: str
    targetModuleRoot: list[str] | None
    targetAreaPath: str | None
    targetPathFromRoot: list[str] | None
    allowed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourcePathFromRoot": self.sourcePathFromRoot,
            "originalImportedModule": self.originalImportedModule,
            "importedModule": self.importedModule,
            "importStyle": self.importStyle,
            "targetModuleRoot": self.targetModuleRoot,
            "targetAreaPath": self.targetAreaPath,
            "targetPathFromRoot": self.targetPathFromRoot,
            "allowed": self.allowed,
        }


@dataclass(frozen=True, slots=True)
class ImportDependencyEdge:
    sourcePathFromRoot: list[str]
    sourceModuleRoot: list[str]
    targetModuleRoot: list[str]
    sourceRole: str
    targetRole: str
    importStem: str
    sameProjectScope: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "sourcePathFromRoot": self.sourcePathFromRoot,
            "sourceModuleRoot": self.sourceModuleRoot,
            "targetModuleRoot": self.targetModuleRoot,
            "sourceRole": self.sourceRole,
            "targetRole": self.targetRole,
            "importStem": self.importStem,
            "sameProjectScope": self.sameProjectScope,
        }


@dataclass(frozen=True, slots=True)
class DependencyFinding:
    pathFromRoot: list[str]
    ruleId: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "recordKind": "Finding",
            "findingKind": "DependencyBoundaryError",
            "severity": self.severity,
            "ruleId": self.ruleId,
            "message": self.message,
            "pathFromRoot": self.pathFromRoot,
            "rootProjectId": ROOT_PROJECT_ID,
        }


def check_product_project_compliance(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    structure_records = scan_product_project_root(root_path)
    import_findings, import_edges = _check_import_file_boundaries(structure_records)
    dependency_findings, dependency_edges = _check_python_dependency_boundaries(
        root_path,
        structure_records,
    )
    dependency_impact = _dependency_impact_records(dependency_edges)
    structure_findings = [
        record for record in structure_records if record.get("recordKind") == "Finding"
    ]
    findings = [
        *structure_findings,
        *[finding.as_dict() for finding in import_findings],
        *[finding.as_dict() for finding in dependency_findings],
    ]
    import_impact = _import_impact_records(import_edges)

    return {
        "passed": len(findings) == 0,
        "summary": {
            **summarize_structure_projection(structure_records),
            "dependency_edge_count": len(dependency_edges),
            "dependency_impact_node_count": len(dependency_impact),
            "max_dependency_direct_upstream_count": max(
                (
                    len(record["directUpstreamSourcePaths"])
                    for record in dependency_impact
                ),
                default=0,
            ),
            "import_dependency_edge_count": len(import_edges),
            "same_project_import_dependency_edge_count": _same_project_import_edge_count(
                import_edges
            ),
            "vendor_import_dependency_edge_count": _vendor_import_edge_count(
                import_edges
            ),
            "cross_project_import_dependency_edge_count": _cross_project_import_edge_count(
                import_edges
            ),
            "import_impact_node_count": len(import_impact),
            "max_import_transitive_upstream_count": max(
                (
                    len(record["transitiveUpstreamModuleRoots"])
                    for record in import_impact
                ),
                default=0,
            ),
            "import_finding_count": len(import_findings),
            "dependency_finding_count": len(dependency_findings),
            "total_finding_count": len(findings),
            "finding_kind_counts": _count_by_key(findings, "findingKind"),
            "rule_id_counts": _count_by_key(findings, "ruleId"),
        },
        "findings": findings,
        "importDependencyEdges": [edge.as_dict() for edge in import_edges],
        "importImpact": import_impact,
        "importImpactHotspots": _import_impact_hotspots(import_impact),
        "dependencyEdges": [edge.as_dict() for edge in dependency_edges],
        "dependencyImpact": dependency_impact,
        "dependencyImpactHotspots": _dependency_impact_hotspots(dependency_impact),
        "records": structure_records,
    }


def _count_by_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(key)
        if value is None:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _same_project_import_edge_count(edges: list[ImportDependencyEdge]) -> int:
    return sum(1 for edge in edges if edge.sameProjectScope)


def _vendor_import_edge_count(edges: list[ImportDependencyEdge]) -> int:
    return sum(
        1
        for edge in edges
        if not edge.sameProjectScope
        and _is_own_vendor_target(edge.sourceModuleRoot, edge.targetModuleRoot)
    )


def _cross_project_import_edge_count(edges: list[ImportDependencyEdge]) -> int:
    return sum(
        1
        for edge in edges
        if not edge.sameProjectScope
        and not _is_own_vendor_target(edge.sourceModuleRoot, edge.targetModuleRoot)
    )


def _dependency_impact_records(edges: list[DependencyEdge]) -> list[dict[str, Any]]:
    direct_upstream: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    nodes: set[tuple[str, ...]] = set()
    for edge in edges:
        source = tuple(edge.sourcePathFromRoot)
        nodes.add(source)
        if edge.targetPathFromRoot is None:
            continue
        target = tuple(edge.targetPathFromRoot)
        nodes.add(target)
        direct_upstream.setdefault(target, set()).add(source)
        direct_upstream.setdefault(source, set())

    records: list[dict[str, Any]] = []
    for node in sorted(nodes):
        direct = sorted(direct_upstream.get(node, set()))
        records.append(
            {
                "sourcePathFromRoot": list(node),
                "directUpstreamSourcePaths": [
                    list(upstream) for upstream in direct
                ],
                "directUpstreamCount": len(direct),
            }
        )
    return records


def _dependency_impact_hotspots(
    records: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    hotspots = [
        record for record in records if int(record.get("directUpstreamCount") or 0) > 0
    ]
    return sorted(
        hotspots,
        key=lambda record: (
            -int(record.get("directUpstreamCount") or 0),
            record.get("sourcePathFromRoot") or [],
        ),
    )[:limit]


def _import_impact_records(edges: list[ImportDependencyEdge]) -> list[dict[str, Any]]:
    direct_upstream: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    nodes: set[tuple[str, ...]] = set()
    for edge in edges:
        source = tuple(edge.sourceModuleRoot)
        target = tuple(edge.targetModuleRoot)
        nodes.add(source)
        nodes.add(target)
        direct_upstream.setdefault(target, set()).add(source)
        direct_upstream.setdefault(source, set())

    records: list[dict[str, Any]] = []
    for node in sorted(nodes):
        direct = sorted(direct_upstream.get(node, set()))
        transitive = _transitive_upstream_modules(node, direct_upstream)
        records.append(
            {
                "moduleRoot": list(node),
                "directUpstreamModuleRoots": [list(upstream) for upstream in direct],
                "transitiveUpstreamModuleRoots": [
                    list(upstream) for upstream in transitive
                ],
                "directUpstreamCount": len(direct),
                "transitiveUpstreamCount": len(transitive),
            }
        )
    return records


def _import_impact_hotspots(
    records: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    hotspots = [
        record
        for record in records
        if int(record.get("transitiveUpstreamCount") or 0) > 0
    ]
    return sorted(
        hotspots,
        key=lambda record: (
            -int(record.get("transitiveUpstreamCount") or 0),
            -int(record.get("directUpstreamCount") or 0),
            record.get("moduleRoot") or [],
        ),
    )[:limit]


def _transitive_upstream_modules(
    module: tuple[str, ...],
    direct_upstream: dict[tuple[str, ...], set[tuple[str, ...]]],
) -> list[tuple[str, ...]]:
    visited: set[tuple[str, ...]] = set()
    stack = list(direct_upstream.get(module, set()))
    while stack:
        upstream = stack.pop()
        if upstream == module or upstream in visited:
            continue
        visited.add(upstream)
        stack.extend(direct_upstream.get(upstream, set()))
    return sorted(visited)


def _check_import_file_boundaries(
    records: list[dict[str, Any]],
) -> tuple[list[DependencyFinding], list[ImportDependencyEdge]]:
    import_records = [
        record for record in records if record.get("entityKind") == "ImportFile"
    ]
    module_paths = {
        tuple(record["pathFromRoot"])
        for record in records
        if record.get("entityKind") == "Module"
    }
    module_roles = {
        tuple(record["pathFromRoot"]): str(record.get("moduleRole") or "")
        for record in records
        if record.get("entityKind") == "Module"
    }
    public_surface_modules = _public_surface_modules(records)
    findings: list[DependencyFinding] = []
    import_edges: list[ImportDependencyEdge] = []
    seen_by_module: dict[tuple[str, str], list[list[str]]] = {}
    for record in import_records:
        path_from_root = list(record["pathFromRoot"])
        stem = Path(path_from_root[-1]).stem
        module_id = str(record.get("moduleId") or "")
        if not _is_valid_import_stem(stem):
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportStemInvalid",
                    message=(
                        "Import file stem must be encoded as "
                        "<up-count>-<target-segment>... ."
                    ),
                )
            )
            continue
        source_module = _module_root_from_import_path(path_from_root)
        target_module = _decode_import_target(source_module, stem)
        if target_module is None:
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportTargetPathInvalid",
                    message=f"Import stem '{stem}' does not decode to a module path.",
                )
            )
            continue
        if target_module == source_module:
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportSelfDependency",
                    message="Import file cannot target its own module.",
                )
            )
            continue
        if _is_ancestor_module(target_module, source_module):
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportAncestorDependency",
                    message="Import file cannot target an ancestor module.",
                )
            )
            continue
        if tuple(target_module) not in module_paths:
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportTargetMissing",
                    message=(
                        "Import file target module does not exist: "
                        f"{'/'.join(target_module)}."
                    ),
                )
            )
            continue
        expected_stem = _encode_import_stem(source_module, target_module)
        if stem != expected_stem:
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportStemNotCanonical",
                    message=(
                        f"Import stem '{stem}' is not canonical; expected "
                        f"'{expected_stem}'."
                    ),
                )
            )
            continue
        if tuple(target_module) not in public_surface_modules:
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportTargetNotDependable",
                    message=(
                        "Import target module has no public surface: "
                        f"{'/'.join(target_module)}."
                    ),
                )
            )
            continue
        source_role = module_roles.get(tuple(source_module), "")
        target_role = module_roles.get(tuple(target_module), "")
        if not _is_allowed_module_import_by_role(source_module, source_role, target_module, target_role):
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="ImportRoleDependencyInvalid",
                    message=(
                        f"{source_role} module cannot structurally depend on "
                        f"{target_role} module through Src/Import."
                    ),
                )
            )
            continue
        import_edges.append(
            ImportDependencyEdge(
                sourcePathFromRoot=path_from_root,
                sourceModuleRoot=source_module,
                targetModuleRoot=target_module,
                sourceRole=source_role,
                targetRole=target_role,
                importStem=stem,
                sameProjectScope=_is_same_project_module(
                    source_module,
                    target_module,
                ),
            )
        )
        seen_by_module.setdefault((module_id, stem), []).append(path_from_root)

    for (_module_id, stem), paths in seen_by_module.items():
        if len(paths) <= 1:
            continue
        for path_from_root in paths:
            findings.append(
                DependencyFinding(
                    pathFromRoot=path_from_root,
                    ruleId="DuplicateImportStem",
                    message=f"Import stem '{stem}' appears more than once in one module.",
                )
            )
    findings.extend(_package_import_cycle_findings(import_edges))
    return findings, import_edges


def _is_valid_import_stem(stem: str) -> bool:
    return bool(IMPORT_STEM_RE.fullmatch(stem))


def _public_surface_modules(records: list[dict[str, Any]]) -> set[tuple[str, ...]]:
    modules: set[tuple[str, ...]] = set()
    for record in records:
        if record.get("entityKind") != "SourceFile":
            continue
        path_from_root = list(record["pathFromRoot"])
        if len(path_from_root) < 5:
            continue
        try:
            src_index = path_from_root.index("Src")
        except ValueError:
            continue
        module = tuple(path_from_root[:src_index])
        source_path = path_from_root[src_index:]
        if _is_boot_public_surface(source_path) or _is_application_public_surface(
            source_path
        ):
            modules.add(module)
    return modules


def _is_boot_public_surface(source_path: list[str]) -> bool:
    return len(source_path) >= 3 and source_path[0] == "Src" and source_path[1] == "Boot"


def _is_application_public_surface(source_path: list[str]) -> bool:
    if len(source_path) < 4:
        return False
    if source_path[0:2] != ["Src", "Application"]:
        return False
    if source_path[2] == "Port":
        return len(source_path) >= 5 and source_path[3] == "In"
    return source_path[2] in APPLICATION_PUBLIC_SECTIONS


def _is_allowed_module_import_by_role(
    source_module: list[str],
    source_role: str,
    target_module: list[str],
    target_role: str,
) -> bool:
    if source_role == "Main":
        return target_role == "Package" and _is_same_project_module(
            source_module,
            target_module,
        )
    if source_role == "Package":
        if _is_own_vendor_target(source_module, target_module):
            return target_role in {"Main", "Package"}
        return target_role == "Package" and _is_same_project_module(
            source_module,
            target_module,
        )
    return False


def _package_import_cycle_findings(
    import_edges: list[ImportDependencyEdge],
) -> list[DependencyFinding]:
    package_edges = [
        edge
        for edge in import_edges
        if edge.sourceRole == "Package" and edge.targetRole == "Package"
        and edge.sameProjectScope
    ]
    adjacency: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    edge_paths: dict[tuple[tuple[str, ...], tuple[str, ...]], list[str]] = {}
    for edge in package_edges:
        source = tuple(edge.sourceModuleRoot)
        target = tuple(edge.targetModuleRoot)
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set())
        edge_paths[(source, target)] = edge.sourcePathFromRoot

    findings: list[DependencyFinding] = []
    for component in _strongly_connected_components(adjacency):
        if len(component) <= 1:
            continue
        component_nodes = sorted(component)
        internal_edges = sorted(
            (source, target)
            for source in component
            for target in adjacency.get(source, set())
            if target in component
        )
        path_from_root = edge_paths[internal_edges[0]]
        findings.append(
            DependencyFinding(
                pathFromRoot=path_from_root,
                ruleId="PackageImportCycle",
                message=(
                    "Package import dependency cycle detected among modules: "
                    + ", ".join("/".join(node) for node in component_nodes)
                    + "."
                ),
            )
        )
    return findings


def _strongly_connected_components(
    adjacency: dict[tuple[str, ...], set[tuple[str, ...]]],
) -> list[set[tuple[str, ...]]]:
    index = 0
    stack: list[tuple[str, ...]] = []
    indices: dict[tuple[str, ...], int] = {}
    lowlinks: dict[tuple[str, ...], int] = {}
    on_stack: set[tuple[str, ...]] = set()
    components: list[set[tuple[str, ...]]] = []

    def visit(node: tuple[str, ...]) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for next_node in sorted(adjacency.get(node, set())):
            if next_node not in indices:
                visit(next_node)
                lowlinks[node] = min(lowlinks[node], lowlinks[next_node])
            elif next_node in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[next_node])

        if lowlinks[node] != indices[node]:
            return
        component: set[tuple[str, ...]] = set()
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.add(member)
            if member == node:
                break
        components.append(component)

    for node in sorted(adjacency):
        if node not in indices:
            visit(node)
    return components


def _module_root_from_import_path(path_from_root: list[str]) -> list[str]:
    try:
        src_index = path_from_root.index("Src")
    except ValueError:
        return path_from_root[:2]
    return path_from_root[:src_index]


def _decode_import_target(source_module: list[str], stem: str) -> list[str] | None:
    parts = stem.split("-")
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    up_count = int(parts[0])
    if up_count > len(source_module):
        return None
    target = [*source_module[: len(source_module) - up_count], *parts[1:]]
    if not _is_module_path(target):
        return None
    return target


def _is_module_path(module: list[str]) -> bool:
    return len(module) >= 2 and module[-2] in PROJECT_ROLE_SPACE_NAMES


def _is_same_project_module(source: list[str], target: list[str]) -> bool:
    if not _is_module_path(source) or not _is_module_path(target):
        return False
    return source[:-2] == target[:-2]


def _is_own_vendor_target(source: list[str], target: list[str]) -> bool:
    if not _is_module_path(source) or not _is_module_path(target):
        return False
    return (
        len(target) == len(source) + 4
        and target[: len(source)] == source
        and target[len(source)] == "Vendor"
    )


def _encode_import_stem(source_module: list[str], target_module: list[str]) -> str:
    common_length = 0
    for source_part, target_part in zip(source_module, target_module):
        if source_part != target_part:
            break
        common_length += 1
    up_count = len(source_module) - common_length
    down_segments = target_module[common_length:]
    return "-".join([str(up_count), *down_segments])


def _is_ancestor_module(candidate: list[str], source: list[str]) -> bool:
    return len(candidate) < len(source) and source[: len(candidate)] == candidate


def _check_python_dependency_boundaries(
    root: Path,
    records: list[dict[str, Any]],
) -> tuple[list[DependencyFinding], list[DependencyEdge]]:
    source_records = [
        record
        for record in records
        if record.get("entityKind") in {"SourceFile", "ImportFile"}
        and record.get("pathFromRoot", [])[-1].endswith(".py")
    ]
    findings: list[DependencyFinding] = []
    edges: list[DependencyEdge] = []
    for record in source_records:
        path_from_root = list(record["pathFromRoot"])
        source_path = root.joinpath(*path_from_root)
        findings.extend(_check_python_source_semantics(source_path, path_from_root))
        for imported in _read_imported_modules(source_path, path_from_root):
            target = _resolve_internal_source_import(imported.resolvedModule)
            if target is None:
                if _is_external_python_import(imported):
                    findings.append(
                        DependencyFinding(
                            pathFromRoot=path_from_root,
                            ruleId="ExternalImportWithoutSupplyBoundary",
                            message=(
                                "External Python imports must be represented through "
                                "a vendor supply boundary before module source uses "
                                f"'{imported.resolvedModule}'."
                            ),
                        )
                    )
                continue
            edge, finding = _dependency_edge_and_finding_for_import(
                path_from_root,
                imported,
                target,
            )
            edges.append(edge)
            if finding is not None:
                findings.append(finding)
    return findings, edges


def _is_external_python_import(imported: ImportedModule) -> bool:
    if imported.importStyle != "absolute":
        return False
    root_name = imported.resolvedModule.split(".", 1)[0]
    if root_name in {"Main", "Package"}:
        return False
    return root_name not in PYTHON_STDLIB_MODULES


def _check_python_source_semantics(
    source_path: Path,
    path_from_root: list[str],
) -> list[DependencyFinding]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []

    findings: list[DependencyFinding] = []
    position = _source_position(path_from_root)
    if position is None:
        return findings

    if position["area"] == "Import" and not _is_pure_import_binding_tree(tree):
        findings.append(
            DependencyFinding(
                pathFromRoot=path_from_root,
                ruleId="ImportFileNotPureBinding",
                message="Src/Import Python files may only contain import bindings.",
            )
        )

    if position["area"] == "Boot" and _boot_tree_reads_platform_state(tree):
        findings.append(
            DependencyFinding(
                pathFromRoot=path_from_root,
                ruleId="BootPlatformRead",
                message=(
                    "Src/Boot must not directly read platform state such as "
                    "environment variables, files, or sockets."
                ),
            )
        )
    return findings


def _is_pure_import_binding_tree(tree: ast.AST) -> bool:
    for statement in getattr(tree, "body", []):
        if isinstance(statement, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        return False
    return True


def _boot_tree_reads_platform_state(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                if node.attr in {"environ", "getenv"}:
                    return True
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name) and function.id == "open":
                return True
            if isinstance(function, ast.Attribute):
                if isinstance(function.value, ast.Name):
                    owner = function.value.id
                    if owner == "os" and function.attr == "getenv":
                        return True
                    if owner == "socket" and function.attr == "socket":
                        return True
    return False


def _dependency_edge_and_finding_for_import(
    source_path_from_root: list[str],
    imported: ImportedModule,
    imported_parts: list[str],
) -> tuple[DependencyEdge, DependencyFinding | None]:
    target_position = _import_position(imported_parts)
    finding = _dependency_finding_for_import(source_path_from_root, imported_parts)
    return (
        DependencyEdge(
            sourcePathFromRoot=source_path_from_root,
            originalImportedModule=imported.originalModule,
            importedModule=imported.resolvedModule,
            importStyle=imported.importStyle,
            targetModuleRoot=target_position["moduleRoot"] if target_position else None,
            targetAreaPath=target_position["areaPath"] if target_position else None,
            targetPathFromRoot=_python_module_parts_to_path(imported_parts),
            allowed=finding is None,
        ),
        finding,
    )


def _python_module_parts_to_path(imported_parts: list[str]) -> list[str]:
    return [*imported_parts[:-1], f"{imported_parts[-1]}.py"]


def _read_imported_modules(
    source_path: Path,
    source_path_from_root: list[str],
) -> list[ImportedModule]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []

    imports: list[ImportedModule] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                ImportedModule(
                    originalModule=alias.name,
                    resolvedModule=alias.name,
                    importStyle="absolute",
                )
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import_from_module(node, source_path_from_root)
            if resolved:
                imports.append(resolved)
    return imports


def _resolve_import_from_module(
    node: ast.ImportFrom,
    source_path_from_root: list[str],
) -> ImportedModule | None:
    module = node.module or ""
    if node.level <= 0:
        if not module:
            return None
        return ImportedModule(
            originalModule=module,
            resolvedModule=module,
            importStyle="absolute",
        )

    source_module_parts = _source_module_parts(source_path_from_root)
    if source_module_parts is None:
        return None
    package_parts = source_module_parts[:-1]
    base_count = len(package_parts) - (node.level - 1)
    if base_count < 0:
        return None
    resolved_parts = package_parts[:base_count]
    if module:
        resolved_parts.extend(module.split("."))
    if not resolved_parts:
        return None
    return ImportedModule(
        originalModule="." * node.level + module,
        resolvedModule=".".join(resolved_parts),
        importStyle="relative",
    )


def _source_module_parts(path_from_root: list[str]) -> list[str] | None:
    if not path_from_root or "." not in path_from_root[-1]:
        return None
    return [*path_from_root[:-1], Path(path_from_root[-1]).stem]


def _resolve_internal_source_import(imported: str) -> list[str] | None:
    parts = imported.split(".")
    if len(parts) < 4:
        return None
    try:
        src_index = parts.index("Src")
    except ValueError:
        return None
    if src_index < 2:
        return None
    if not _is_module_path(parts[:src_index]):
        return None
    return parts


def _dependency_finding_for_import(
    source_path_from_root: list[str],
    imported_parts: list[str],
) -> DependencyFinding | None:
    source = _source_position(source_path_from_root)
    target = _import_position(imported_parts)
    if source is None or target is None:
        return None

    if source["moduleRoot"] != target["moduleRoot"]:
        return DependencyFinding(
            pathFromRoot=source_path_from_root,
            ruleId="DirectCrossModuleSourceImport",
            message=(
                "Cross-module source imports must be expressed through "
                "Src/Import and Adapter/Out/Module, not by direct Python import "
                f"to {'.'.join(imported_parts)}."
            ),
        )

    if not _is_allowed_same_module_dependency(source, target):
        return DependencyFinding(
            pathFromRoot=source_path_from_root,
            ruleId="ModuleInternalDependencyBoundary",
            message=(
                f"{source['areaPath']} cannot depend on {target['areaPath']} "
                "under AGENTS module dependency rules."
            ),
        )
    return None


def _source_position(path_from_root: list[str]) -> dict[str, Any] | None:
    try:
        src_index = path_from_root.index("Src")
    except ValueError:
        return None
    if src_index < 2 or len(path_from_root) <= src_index + 1:
        return None
    area_path = path_from_root[src_index + 1 : -1]
    if not area_path:
        return None
    return {
        "moduleRoot": path_from_root[:src_index],
        "area": area_path[0],
        "section": area_path[1] if len(area_path) > 1 else "",
        "segments": area_path,
        "areaPath": "/".join(["Src", *area_path]),
    }


def _import_position(imported_parts: list[str]) -> dict[str, Any] | None:
    try:
        src_index = imported_parts.index("Src")
    except ValueError:
        return None
    if src_index < 2:
        return None
    area_path = imported_parts[src_index + 1 :]
    if not area_path:
        return None
    return {
        "moduleRoot": imported_parts[:src_index],
        "area": area_path[0],
        "section": area_path[1] if len(area_path) > 1 else "",
        "segments": area_path,
        "areaPath": "/".join(["Src", *area_path]),
    }


def _is_allowed_same_module_dependency(
    source: dict[str, Any],
    target: dict[str, Any],
) -> bool:
    source_area = source["area"]
    target_area = target["area"]

    if source_area == "Domain":
        return target_area == "Domain"
    if source_area == "Boot":
        if target_area == "Boot":
            return True
        if target_area == "Application":
            return True
        if target_area == "Adapter":
            return True
        return False
    if source_area == "Adapter":
        return _is_allowed_adapter_dependency(source["segments"], target)
    if source_area == "Application":
        return _is_allowed_application_dependency(source["segments"], target)
    return target_area == source_area


def _is_allowed_application_dependency(
    source_segments: list[str],
    target: dict[str, Any],
) -> bool:
    if target["area"] == "Boot" or target["area"] in {"Adapter", "Import"}:
        return False
    if target["area"] == "Domain":
        return _matches_prefix(source_segments, ["Application", "Usecase"])
    if target["area"] != "Application":
        return False

    target_segments = target["segments"]
    if _matches_prefix(source_segments, ["Application", "Port", "In"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Command"],
                ["Application", "Query"],
                ["Application", "Result"],
                ["Application", "Dto"],
                ["Application", "Error"],
            ],
        )
    if _matches_prefix(source_segments, ["Application", "Port", "Out"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Dto"],
                ["Application", "Result"],
                ["Application", "Error"],
            ],
        )
    if _matches_prefix(source_segments, ["Application", "Entry"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Port", "In"],
                ["Application", "Command"],
                ["Application", "Query"],
                ["Application", "Result"],
                ["Application", "Dto"],
                ["Application", "Error"],
            ],
        )
    if _matches_prefix(source_segments, ["Application", "Command"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Command"],
                ["Application", "Dto"],
                ["Application", "Error"],
            ],
        )
    if _matches_prefix(source_segments, ["Application", "Query"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Query"],
                ["Application", "Dto"],
                ["Application", "Error"],
            ],
        )
    if _matches_prefix(source_segments, ["Application", "Result"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Result"],
                ["Application", "Dto"],
                ["Application", "Error"],
            ],
        )
    if _matches_prefix(source_segments, ["Application", "Dto"]):
        return _matches_prefix(target_segments, ["Application", "Dto"])
    if _matches_prefix(source_segments, ["Application", "Error"]):
        return _matches_prefix(target_segments, ["Application", "Error"])
    if _matches_prefix(source_segments, ["Application", "Usecase"]):
        return _matches_any_application_prefix(
            target_segments,
            [
                ["Application", "Port", "In"],
                ["Application", "Port", "Out"],
                ["Application", "Command"],
                ["Application", "Query"],
                ["Application", "Result"],
                ["Application", "Dto"],
                ["Application", "Error"],
                ["Application", "Usecase"],
            ],
        )
    return target["area"] == "Application"


def _is_allowed_adapter_dependency(
    source_segments: list[str],
    target: dict[str, Any],
) -> bool:
    if target["area"] in {"Domain", "Boot"}:
        return False
    if target["area"] == "Import":
        return _matches_prefix(source_segments, ["Adapter", "Out", "Module"])
    if target["area"] == "Application":
        if _matches_prefix(target["segments"], ["Application", "Usecase"]):
            return False
        if _matches_prefix(source_segments, ["Adapter", "In"]):
            return _matches_any_application_prefix(
                target["segments"],
                [
                    ["Application", "Port", "In"],
                    ["Application", "Command"],
                    ["Application", "Query"],
                    ["Application", "Result"],
                    ["Application", "Dto"],
                    ["Application", "Error"],
                ],
            )
        if _matches_prefix(source_segments, ["Adapter", "Out"]):
            return _matches_any_application_prefix(
                target["segments"],
                [
                    ["Application", "Port", "Out"],
                    ["Application", "Dto"],
                    ["Application", "Result"],
                    ["Application", "Error"],
                ],
            )
        if _matches_prefix(source_segments, ["Adapter", "Mapper"]):
            return _matches_any_application_prefix(
                target["segments"],
                [
                    ["Application", "Command"],
                    ["Application", "Query"],
                    ["Application", "Result"],
                    ["Application", "Dto"],
                    ["Application", "Error"],
                ],
            )
        return True
    if target["area"] != "Adapter":
        return False
    if _matches_prefix(source_segments, ["Adapter", "In"]):
        return _matches_prefix(target["segments"], ["Adapter", "Mapper"])
    if _matches_prefix(source_segments, ["Adapter", "Out"]):
        if _matches_prefix(target["segments"], ["Adapter", "Mapper"]):
            return True
        return _matches_prefix(target["segments"], source_segments[:3])
    if _matches_prefix(source_segments, ["Adapter", "Mapper"]):
        return _matches_prefix(target["segments"], ["Adapter", "Mapper"])
    return True


def _matches_any_application_prefix(
    segments: list[str],
    prefixes: list[list[str]],
) -> bool:
    return any(_matches_prefix(segments, prefix) for prefix in prefixes)


def _matches_prefix(segments: list[str], prefix: list[str]) -> bool:
    return segments[: len(prefix)] == prefix
