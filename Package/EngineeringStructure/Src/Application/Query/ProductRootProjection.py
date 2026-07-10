from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


METHOD_VERSION = "AgentsStructureProjectionV1"
ROOT_PROFILE = "ProductProjectRoot"
ROOT_PROJECT_ID = "@rootProject"
PROJECT_RESERVED_NAMES = frozenset(
    {"Main", "Package", "Tool", "Script", "Docs", "Vendor", "Workspace"}
)
PROJECT_ROLE_SPACE_NAMES = frozenset({"Main", "Package"})
PROJECT_EMBEDDED_WORKSPACE_NAMES = frozenset({"Tool", "Script", "Docs"})
MODULE_RESERVED_ITEM_NAMES = frozenset({"Src", "Test", "Config", "Data", "Bin"})
MODULE_EMBEDDED_WORKSPACE_NAMES = frozenset({"Tool", "Script", "Docs", "Vendor"})
MODULE_RESERVED_NAMES = (
    MODULE_RESERVED_ITEM_NAMES | MODULE_EMBEDDED_WORKSPACE_NAMES | {"Workspace"}
)
SRC_AREA_NAMES = frozenset({"Boot", "Import", "Domain", "Application", "Adapter"})
MODEL_RESERVED_NAMES = (
    PROJECT_RESERVED_NAMES | MODULE_RESERVED_ITEM_NAMES | SRC_AREA_NAMES
)
ROOT_EXCLUSIONS = (".git", ".temp", "CLAUDE.md")
PROCESS_CARRIER_EXCLUSIONS = frozenset({"__pycache__"})
STRUCTURE_SEGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class StructureRecord:
    recordId: str
    recordKind: str
    methodVersion: str
    stateVersion: str
    rootProfile: str
    rootProjectId: str
    excludedRootEntries: list[str]
    operationKind: str
    entityId: str | None
    entityKind: str | None
    projectId: str | None
    moduleId: str | None
    moduleRole: str | None
    vendorGoverned: bool | None
    sameProjectScope: bool | None
    pathFromRoot: list[str]
    canonicalPathSegments: list[str]
    importStem: str | None
    findingId: str | None
    findingKind: str | None
    severity: str | None
    ruleId: str | None
    message: str | None
    sourceRecordIds: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


def _stable_id(prefix: str, parts: list[str] | tuple[str, ...]) -> str:
    joined = "/".join(parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}{digest}"


def _state_version(root: Path, excluded: list[str]) -> str:
    entries = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.name in excluded:
            continue
        try:
            stat = child.lstat()
        except OSError:
            entries.append(f"{child.name}:unreadable")
            continue
        kind = "dir" if child.is_dir() else "file" if child.is_file() else "other"
        entries.append(f"{child.name}:{kind}:{stat.st_mtime_ns}:{stat.st_size}")
    digest = hashlib.sha1("\n".join(entries).encode("utf-8")).hexdigest()[:12]
    return f"state{digest}"


def _base_record(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    record_id: str,
    record_kind: str,
    operation_kind: str,
    entity_id: str | None,
    entity_kind: str | None,
    path_from_root: list[str],
    canonical_path_segments: list[str] | None = None,
    project_id: str | None = None,
    module_id: str | None = None,
    module_role: str | None = None,
    vendor_governed: bool | None = None,
    finding_id: str | None = None,
    finding_kind: str | None = None,
    severity: str | None = None,
    rule_id: str | None = None,
    message: str | None = None,
    source_record_ids: list[str] | None = None,
) -> StructureRecord:
    del root
    return StructureRecord(
        recordId=record_id,
        recordKind=record_kind,
        methodVersion=METHOD_VERSION,
        stateVersion=state_version,
        rootProfile=ROOT_PROFILE,
        rootProjectId=ROOT_PROJECT_ID,
        excludedRootEntries=excluded,
        operationKind=operation_kind,
        entityId=entity_id,
        entityKind=entity_kind,
        projectId=project_id
        if project_id is not None
        else ROOT_PROJECT_ID
        if entity_kind is not None
        else None,
        moduleId=module_id,
        moduleRole=module_role,
        vendorGoverned=vendor_governed
        if vendor_governed is not None
        else False
        if entity_kind
        in {
            "Project",
            "ModuleRoleSpace",
            "Module",
            "ModuleReservedItem",
            "EmbeddedWorkspace",
            "SourceDirectory",
            "SourceFile",
            "TestDirectory",
            "TestFile",
            "FreeRemainder",
        }
        else None,
        sameProjectScope=None,
        pathFromRoot=path_from_root,
        canonicalPathSegments=canonical_path_segments or [],
        importStem=None,
        findingId=finding_id,
        findingKind=finding_kind,
        severity=severity,
        ruleId=rule_id,
        message=message,
        sourceRecordIds=sorted(source_record_ids or []),
    )


def _is_reserved_case_variant(name: str) -> bool:
    return _is_case_variant(name, PROJECT_RESERVED_NAMES)


def _is_case_variant(name: str, reserved_names: frozenset[str]) -> bool:
    folded = name.lower()
    return any(
        reserved.lower() == folded and reserved != name
        for reserved in reserved_names
    )


def _is_structure_segment(name: str) -> bool:
    return bool(STRUCTURE_SEGMENT_RE.fullmatch(name))


def _is_process_carrier(path: Path) -> bool:
    return path.name in PROCESS_CARRIER_EXCLUSIONS


def _finding_record(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    path_from_root: list[str],
    rule_id: str,
    message: str,
    source_record_ids: list[str],
    finding_kind: str = "StructureClosureError",
    module_id: str | None = None,
    module_role: str | None = None,
) -> StructureRecord:
    return _base_record(
        root=root,
        state_version=state_version,
        excluded=excluded,
        record_id=_stable_id("record", ("finding", rule_id, *path_from_root)),
        record_kind="Finding",
        operation_kind="StructureCandidateProjection",
        entity_id=None,
        entity_kind=None,
        project_id=ROOT_PROJECT_ID if module_id is not None else None,
        module_id=module_id,
        module_role=module_role,
        vendor_governed=False if module_id is not None else None,
        path_from_root=path_from_root,
        finding_id=_stable_id("finding", (rule_id, *path_from_root)),
        finding_kind=finding_kind,
        severity="error",
        rule_id=rule_id,
        message=message,
        source_record_ids=source_record_ids,
    )


def _module_id(role_name: str, module_name: str) -> str:
    return _stable_id("module", (role_name, module_name))


def _scan_role_space(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    role_space: Path,
    role_name: str,
    role_record_id: str,
    role_path: list[str] | None = None,
) -> None:
    role_path = role_path or [role_name]
    if not role_space.is_dir() or role_space.is_symlink():
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=role_path,
                rule_id="RoleSpaceCarrierInvalid",
                message=f"Project role space '{role_name}' must be a real directory.",
                source_record_ids=[role_record_id],
            )
        )
        return

    for child in sorted(role_space.iterdir(), key=lambda path: path.name):
        name = child.name
        path_segments = [*role_path, name]
        if (
            not child.is_dir()
            or child.is_symlink()
            or name.startswith(".")
            or not _is_structure_segment(name)
            or name in MODEL_RESERVED_NAMES
            or _is_case_variant(name, MODEL_RESERVED_NAMES)
        ):
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="RoleSpaceModuleNameInvalid",
                    message=(
                        f"Role space child '{name}' cannot become a legal "
                        f"{role_name} module."
                    ),
                    source_record_ids=[role_record_id],
                )
            )
            continue

        module_id = (
            _module_id(role_name, name)
            if role_path == [role_name]
            else _stable_id("module", tuple(path_segments))
        )
        module_record_id = _stable_id("record", ("module", *path_segments))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=module_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=module_id,
                entity_kind="Module",
                module_id=module_id,
                module_role=role_name,
                vendor_governed=False,
                path_from_root=path_segments,
                canonical_path_segments=path_segments,
            )
        )
        _scan_module(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            module_root=child,
            module_path=path_segments,
            module_id=module_id,
            module_role=role_name,
            module_record_id=module_record_id,
        )


def _scan_module(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    module_root: Path,
    module_path: list[str],
    module_id: str,
    module_role: str,
    module_record_id: str,
) -> None:
    source_files: list[tuple[list[str], str, str]] = []
    source_record_ids: dict[tuple[str, ...], str] = {}
    test_files: list[list[str]] = []
    test_directories: list[list[str]] = []
    has_src = False
    has_test = False

    for child in sorted(module_root.iterdir(), key=lambda path: path.name):
        name = child.name
        path_segments = [*module_path, name]

        if name in MODULE_RESERVED_ITEM_NAMES:
            record_id = _stable_id("record", ("moduleReserved", *path_segments))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("reserved", tuple(path_segments)),
                    entity_kind="ModuleReservedItem",
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            if not child.is_dir() or child.is_symlink():
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=path_segments,
                        rule_id="ModuleReservedItemCarrierInvalid",
                        message=f"Module reserved item '{name}' must be a real directory.",
                        source_record_ids=[record_id, module_record_id],
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
                continue
            if name == "Src":
                has_src = True
                source_files = _scan_src(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    src_root=child,
                    module_path=module_path,
                    module_id=module_id,
                    module_role=module_role,
                    src_record_id=record_id,
                    source_record_ids=source_record_ids,
                )
            elif name == "Test":
                has_test = True
                test_files, test_directories = _scan_test(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    test_root=child,
                    module_path=module_path,
                    module_id=module_id,
                    module_role=module_role,
                    test_record_id=record_id,
                )
            elif name == "Config":
                _validate_config_or_data_carrier(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    carrier_root=child,
                    module_path=module_path,
                    reserved_name=name,
                    module_id=module_id,
                    module_role=module_role,
                    reserved_record_id=record_id,
                    allow_data_test=False,
                )
            elif name == "Data":
                _validate_config_or_data_carrier(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    carrier_root=child,
                    module_path=module_path,
                    reserved_name=name,
                    module_id=module_id,
                    module_role=module_role,
                    reserved_record_id=record_id,
                    allow_data_test=True,
                )
            elif name == "Bin":
                _validate_bin_carrier(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    bin_root=child,
                    module_path=module_path,
                    module_id=module_id,
                    module_role=module_role,
                    bin_record_id=record_id,
                )
            continue

        if name in MODULE_EMBEDDED_WORKSPACE_NAMES:
            workspace_record_id = _stable_id("record", ("moduleWorkspace", *path_segments))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=workspace_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("workspace", tuple(path_segments)),
                    entity_kind="EmbeddedWorkspace",
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            if name == "Vendor":
                _scan_module_vendor_workspace(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    vendor_root=child,
                    vendor_path=path_segments,
                    vendor_record_id=workspace_record_id,
                )
            else:
                _validate_embedded_workspace_carrier(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    records=records,
                    workspace_root=child,
                    workspace_path=path_segments,
                    workspace_record_id=workspace_record_id,
                    module_id=module_id,
                    module_role=module_role,
                )
            continue

        if name == "Workspace" or _is_case_variant(name, MODULE_RESERVED_NAMES):
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="ModuleDirectReservedName",
                    message=(
                        f"Module direct child '{name}' is reserved here and "
                        "cannot be a free remainder."
                    ),
                    source_record_ids=[module_record_id],
                    module_id=module_id,
                    module_role=module_role,
                )
            )
            continue

        free_record_id = _stable_id("record", ("moduleFree", *path_segments))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=free_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=_stable_id("free", tuple(path_segments)),
                entity_kind="FreeRemainder",
                module_id=module_id,
                module_role=module_role,
                vendor_governed=False,
                path_from_root=path_segments,
                canonical_path_segments=[],
            )
        )
        _validate_free_remainder_carrier(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            carrier=child,
            path_from_root=path_segments,
            source_record_id=free_record_id,
            module_id=module_id,
            module_role=module_role,
        )

    if has_src:
        _check_source_extension_and_stem_uniqueness(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            module_path=module_path,
            module_id=module_id,
            module_role=module_role,
            source_files=source_files,
            source_record_ids=source_record_ids,
            module_record_id=module_record_id,
        )
        _check_source_position_implications(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            module_path=module_path,
            module_id=module_id,
            module_role=module_role,
            source_files=source_files,
            source_record_ids=source_record_ids,
            module_record_id=module_record_id,
        )
    if source_files and not has_test:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Test"],
                rule_id="TestReservedItemMissing",
                message="Module with source files must include a Test mirror.",
                source_record_ids=[module_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )
    if has_test:
        _check_test_mirrors(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            module_root=module_root,
            module_path=module_path,
            module_id=module_id,
            module_role=module_role,
            source_files=source_files,
            source_record_ids=source_record_ids,
            test_files=test_files,
            test_directories=test_directories,
        )


def _scan_module_vendor_workspace(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    vendor_root: Path,
    vendor_path: list[str],
    vendor_record_id: str,
) -> None:
    if not vendor_root.is_dir() or vendor_root.is_symlink():
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=vendor_path,
                rule_id="VendorWorkspaceCarrierInvalid",
                message="Module Vendor workspace must be a real directory.",
                source_record_ids=[vendor_record_id],
            )
        )
        return

    for project in sorted(vendor_root.iterdir(), key=lambda path: path.name):
        if _is_process_carrier(project):
            continue
        project_path = [*vendor_path, project.name]
        if not project.is_dir() or project.is_symlink():
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=project_path,
                    rule_id="VendorProjectCarrierInvalid",
                    message="Vendor direct child must be a real supply project directory.",
                    source_record_ids=[vendor_record_id],
                )
            )
            continue
        project_record_id = _stable_id("record", ("vendorProject", *project_path))
        project_id = _stable_id("vendorProject", tuple(project_path))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=project_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=project_id,
                entity_kind="Project",
                project_id=project_id,
                vendor_governed=True,
                path_from_root=project_path,
                canonical_path_segments=project_path,
            )
        )
        for role_space_name in sorted(PROJECT_ROLE_SPACE_NAMES):
            role_space = project / role_space_name
            if not role_space.exists():
                continue
            role_path = [*project_path, role_space_name]
            role_record_id = _stable_id("record", ("vendorRole", *role_path))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=role_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("roleSpace", tuple(role_path)),
                    entity_kind="ModuleRoleSpace",
                    project_id=project_id,
                    vendor_governed=True,
                    path_from_root=role_path,
                    canonical_path_segments=role_path,
                )
            )
            _scan_vendor_role_space(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                role_space=role_space,
                role_path=role_path,
                role_name=role_space_name,
                role_record_id=role_record_id,
            )
        _scan_vendor_project_remainder(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            project_root=project,
            project_path=project_path,
            project_id=project_id,
            project_record_id=project_record_id,
        )


def _scan_vendor_role_space(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    role_space: Path,
    role_path: list[str],
    role_name: str,
    role_record_id: str,
) -> None:
    if not role_space.is_dir() or role_space.is_symlink():
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=role_path,
                rule_id="VendorRoleSpaceCarrierInvalid",
                message="Vendor role space must be a real directory.",
                source_record_ids=[role_record_id],
            )
        )
        return
    for module_root in sorted(role_space.iterdir(), key=lambda path: path.name):
        module_path = [*role_path, module_root.name]
        if not module_root.is_dir() or module_root.is_symlink():
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=module_path,
                    rule_id="VendorModuleCarrierInvalid",
                    message="Vendor module must be a real directory.",
                    source_record_ids=[role_record_id],
                )
            )
            continue
        module_id = _stable_id("module", tuple(module_path))
        module_record_id = _stable_id("record", ("vendorModule", *module_path))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=module_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=module_id,
                entity_kind="Module",
                module_id=module_id,
                module_role=role_name,
                vendor_governed=True,
                path_from_root=module_path,
                canonical_path_segments=module_path,
            )
        )
        _scan_module(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            module_root=module_root,
            module_path=module_path,
            module_id=module_id,
            module_role=role_name,
            module_record_id=module_record_id,
        )


def _scan_vendor_project_remainder(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    project_root: Path,
    project_path: list[str],
    project_id: str,
    project_record_id: str,
) -> None:
    children = [
        child
        for child in sorted(project_root.iterdir(), key=lambda path: path.name)
        if not _is_process_carrier(child)
    ]
    if not children:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=project_path,
                rule_id="ProjectDirectoryEmpty",
                message="Project directory must contain at least one direct child.",
                source_record_ids=[project_record_id],
            )
        )
        return

    for child in children:
        name = child.name
        path_segments = [*project_path, name]
        if name in PROJECT_ROLE_SPACE_NAMES:
            continue
        if name in PROJECT_EMBEDDED_WORKSPACE_NAMES:
            workspace_record_id = _stable_id("record", ("workspace", *path_segments))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=workspace_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("workspace", tuple(path_segments)),
                    entity_kind="EmbeddedWorkspace",
                    project_id=project_id,
                    vendor_governed=True,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            _validate_embedded_workspace_carrier(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                workspace_root=child,
                workspace_path=path_segments,
                workspace_record_id=workspace_record_id,
            )
            continue
        if name in {"Vendor", "Workspace"} or _is_case_variant(name, PROJECT_RESERVED_NAMES):
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="ProjectDirectReservedName",
                    message=(
                        f"Project direct child '{name}' is reserved here and "
                        "cannot be a free remainder."
                    ),
                    source_record_ids=[project_record_id],
                )
            )
            continue
        free_record_id = _stable_id("record", ("projectFree", *path_segments))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=free_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=_stable_id("free", tuple(path_segments)),
                entity_kind="FreeRemainder",
                project_id=project_id,
                vendor_governed=True,
                path_from_root=path_segments,
                canonical_path_segments=[],
            )
        )
        _validate_free_remainder_carrier(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            carrier=child,
            path_from_root=path_segments,
            source_record_id=free_record_id,
        )


def _scan_embedded_project(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    project_root: Path,
    project_path: list[str],
    project_id: str,
    project_record_id: str,
) -> None:
    children = [
        child
        for child in sorted(project_root.iterdir(), key=lambda path: path.name)
        if not _is_process_carrier(child)
    ]
    if not children:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=project_path,
                rule_id="ProjectDirectoryEmpty",
                message="Project directory must contain at least one direct child.",
                source_record_ids=[project_record_id],
            )
        )
        return

    for child in children:
        name = child.name
        path_segments = [*project_path, name]
        if name in PROJECT_ROLE_SPACE_NAMES:
            role_record_id = _stable_id("record", ("role", *path_segments))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=role_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("roleSpace", tuple(path_segments)),
                    entity_kind="ModuleRoleSpace",
                    project_id=project_id,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            _scan_role_space(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                role_space=child,
                role_name=name,
                role_record_id=role_record_id,
                role_path=path_segments,
            )
            continue

        if name in PROJECT_EMBEDDED_WORKSPACE_NAMES:
            workspace_record_id = _stable_id("record", ("workspace", *path_segments))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=workspace_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("workspace", tuple(path_segments)),
                    entity_kind="EmbeddedWorkspace",
                    project_id=project_id,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            _validate_embedded_workspace_carrier(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                workspace_root=child,
                workspace_path=path_segments,
                workspace_record_id=workspace_record_id,
            )
            continue

        if name in {"Vendor", "Workspace"} or _is_case_variant(name, PROJECT_RESERVED_NAMES):
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="ProjectDirectReservedName",
                    message=(
                        f"Project direct child '{name}' is reserved here and "
                        "cannot be a free remainder."
                    ),
                    source_record_ids=[project_record_id],
                )
            )
            continue

        free_record_id = _stable_id("record", ("projectFree", *path_segments))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=free_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=_stable_id("free", tuple(path_segments)),
                entity_kind="FreeRemainder",
                project_id=project_id,
                path_from_root=path_segments,
                canonical_path_segments=[],
            )
        )
        _validate_free_remainder_carrier(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            carrier=child,
            path_from_root=path_segments,
            source_record_id=free_record_id,
        )


def _validate_embedded_workspace_carrier(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    workspace_root: Path,
    workspace_path: list[str],
    workspace_record_id: str,
    module_id: str | None = None,
    module_role: str | None = None,
) -> None:
    if not workspace_root.is_dir() or workspace_root.is_symlink():
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=workspace_path,
                rule_id="EmbeddedWorkspaceCarrierInvalid",
                message="Embedded workspace must be a real directory.",
                source_record_ids=[workspace_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )
        return

    children = [
        child
        for child in sorted(workspace_root.iterdir(), key=lambda path: path.name)
        if not _is_process_carrier(child)
    ]
    if not children:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=workspace_path,
                rule_id="EmbeddedWorkspaceEmpty",
                message="Embedded workspace must contain at least one project directory.",
                source_record_ids=[workspace_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )
        return

    for child in children:
        child_path = [*workspace_path, child.name]
        if (
            child.is_dir()
            and not child.is_symlink()
            and not child.name.startswith(".")
            and _is_structure_segment(child.name)
            and child.name not in MODEL_RESERVED_NAMES
            and not _is_case_variant(child.name, MODEL_RESERVED_NAMES)
        ):
            project_id = _stable_id("project", tuple(child_path))
            project_record_id = _stable_id("record", ("project", *child_path))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=project_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=project_id,
                    entity_kind="Project",
                    project_id=project_id,
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=child_path,
                    canonical_path_segments=child_path,
                )
            )
            _scan_embedded_project(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                project_root=child,
                project_path=child_path,
                project_id=project_id,
                project_record_id=project_record_id,
            )
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=child_path,
                rule_id="EmbeddedWorkspaceProjectInvalid",
                message=(
                    "Embedded workspace direct child must be a real project "
                    "directory with a legal structure segment name."
                ),
                source_record_ids=[workspace_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )


def _check_source_extension_and_stem_uniqueness(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    module_path: list[str],
    module_id: str,
    module_role: str,
    source_files: list[tuple[list[str], str, str]],
    source_record_ids: dict[tuple[str, ...], str],
    module_record_id: str,
) -> None:
    suffixes = sorted({suffix for _relative_path, _stem, suffix in source_files})
    if len(suffixes) > 1:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Src"],
                rule_id="ModuleExtensionConflict",
                message=(
                    "Module source carriers must use one extension; found "
                    + ", ".join(suffixes)
                    + "."
                ),
                source_record_ids=[module_record_id],
                finding_kind="ModuleExtensionConflict",
                module_id=module_id,
                module_role=module_role,
            )
        )

    paths_by_stem: dict[str, list[list[str]]] = {}
    for relative_path, stem, _suffix in source_files:
        if relative_path[:1] == ["Import"]:
            continue
        paths_by_stem.setdefault(stem, []).append(relative_path)

    for stem, relative_paths in sorted(paths_by_stem.items()):
        if len(relative_paths) <= 1:
            continue
        for relative_path in relative_paths:
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=[*module_path, "Src", *relative_path],
                    rule_id="SourceStemDuplicate",
                    message=f"Source stem '{stem}' appears more than once in one module.",
                    source_record_ids=[
                        source_record_ids.get(tuple(relative_path), module_record_id)
                    ],
                    finding_kind="UniquenessConflict",
                    module_id=module_id,
                    module_role=module_role,
                )
        )


def _validate_config_or_data_carrier(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    carrier_root: Path,
    module_path: list[str],
    reserved_name: str,
    module_id: str,
    module_role: str,
    reserved_record_id: str,
    allow_data_test: bool,
) -> None:
    file_count = _validate_recursive_data_carrier(
        root=root,
        state_version=state_version,
        excluded=excluded,
        records=records,
        carrier_root=carrier_root,
        module_path=module_path,
        relative_prefix=[reserved_name],
        module_id=module_id,
        module_role=module_role,
        parent_record_id=reserved_record_id,
        allow_data_test=allow_data_test,
        inside_data_root=True,
    )
    if file_count == 0:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, reserved_name],
                rule_id=f"{reserved_name}ContainsNoFile",
                message=f"{reserved_name}/ must recursively contain at least one regular file.",
                source_record_ids=[reserved_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )


def _validate_free_remainder_carrier(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    carrier: Path,
    path_from_root: list[str],
    source_record_id: str,
    module_id: str | None = None,
    module_role: str | None = None,
) -> None:
    if carrier.is_file() and not carrier.is_symlink():
        return
    if carrier.is_dir() and not carrier.is_symlink():
        _validate_free_remainder_directory(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            directory=carrier,
            path_from_root=path_from_root,
            source_record_id=source_record_id,
            module_id=module_id,
            module_role=module_role,
        )
        return
    records.append(
        _finding_record(
            root=root,
            state_version=state_version,
            excluded=excluded,
            path_from_root=path_from_root,
            rule_id="FreeRemainderCarrierInvalid",
            message="Free remainder must be a regular file or real directory.",
            source_record_ids=[source_record_id],
            finding_kind="CarrierValidationFailure",
            module_id=module_id,
            module_role=module_role,
        )
    )


def _validate_free_remainder_directory(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    directory: Path,
    path_from_root: list[str],
    source_record_id: str,
    module_id: str | None,
    module_role: str | None,
) -> None:
    if _is_vcs_snapshot_root(directory):
        return
    children = sorted(directory.iterdir(), key=lambda path: path.name)
    if not children:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=path_from_root,
                rule_id="FreeRemainderDirectoryEmpty",
                message="Free remainder directories must not be empty.",
                source_record_ids=[source_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )
        return
    for child in children:
        child_path = [*path_from_root, child.name]
        if child.is_file() and not child.is_symlink():
            continue
        if child.is_dir() and not child.is_symlink():
            _validate_free_remainder_directory(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                directory=child,
                path_from_root=child_path,
                source_record_id=source_record_id,
                module_id=module_id,
                module_role=module_role,
            )
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=child_path,
                rule_id="FreeRemainderCarrierInvalid",
                message="Free remainder contents must be regular files or real directories.",
                source_record_ids=[source_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )


def _is_vcs_snapshot_root(directory: Path) -> bool:
    return (directory / ".git").exists() or (directory / ".gitmodules").exists()


def _validate_recursive_data_carrier(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    carrier_root: Path,
    module_path: list[str],
    relative_prefix: list[str],
    module_id: str,
    module_role: str,
    parent_record_id: str,
    allow_data_test: bool,
    inside_data_root: bool,
) -> int:
    children = sorted(carrier_root.iterdir(), key=lambda path: path.name)
    if not children:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, *relative_prefix],
                rule_id="DataCarrierDirectoryEmpty",
                message="Config/Data carrier directories must not be empty.",
                source_record_ids=[parent_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )
        return 0

    file_count = 0
    for child in children:
        child_relative = [*relative_prefix, child.name]
        child_path = [*module_path, *child_relative]
        if allow_data_test and inside_data_root and child.name.lower() == "test":
            if child.name != "Test" or not child.is_dir() or child.is_symlink():
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=child_path,
                        rule_id="DataTestCarrierInvalid",
                        message="Data/Test must use canonical name and be a real directory.",
                        source_record_ids=[parent_record_id],
                        finding_kind="CarrierValidationFailure",
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
                continue
        if child.is_file() and not child.is_symlink():
            file_count += 1
            continue
        if child.is_dir() and not child.is_symlink():
            file_count += _validate_recursive_data_carrier(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                carrier_root=child,
                module_path=module_path,
                relative_prefix=child_relative,
                module_id=module_id,
                module_role=module_role,
                parent_record_id=parent_record_id,
                allow_data_test=allow_data_test,
                inside_data_root=False,
            )
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=child_path,
                rule_id="DataCarrierInvalid",
                message="Config/Data carriers must be regular files or real directories.",
                source_record_ids=[parent_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )
    return file_count


def _validate_bin_carrier(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    bin_root: Path,
    module_path: list[str],
    module_id: str,
    module_role: str,
    bin_record_id: str,
) -> None:
    children = sorted(bin_root.iterdir(), key=lambda path: path.name)
    if not children:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Bin"],
                rule_id="BinContainsNoFile",
                message="Bin/ must contain at least one regular file.",
                source_record_ids=[bin_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )
        return
    for child in children:
        if child.is_file() and not child.is_symlink():
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Bin", child.name],
                rule_id="BinCarrierInvalid",
                message="Bin/ may contain only direct regular files.",
                source_record_ids=[bin_record_id],
                finding_kind="CarrierValidationFailure",
                module_id=module_id,
                module_role=module_role,
            )
        )


def _check_source_position_implications(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    module_path: list[str],
    module_id: str,
    module_role: str,
    source_files: list[tuple[list[str], str, str]],
    source_record_ids: dict[tuple[str, ...], str],
    module_record_id: str,
) -> None:
    relative_paths = [relative_path for relative_path, _stem, _suffix in source_files]
    has_boot = _has_source_prefix(relative_paths, ["Boot"])
    has_usecase = _has_source_prefix(relative_paths, ["Application", "Usecase"])
    has_adapter = _has_source_prefix(relative_paths, ["Adapter"])
    has_port_in = _has_source_prefix(relative_paths, ["Application", "Port", "In"])
    has_port_out = _has_source_prefix(relative_paths, ["Application", "Port", "Out"])
    has_adapter_out = _has_source_prefix(relative_paths, ["Adapter", "Out"])
    has_adapter_out_module = _has_source_prefix(
        relative_paths,
        ["Adapter", "Out", "Module"],
    )
    has_import = _has_source_prefix(relative_paths, ["Import"])

    implication_rules = [
        (
            has_usecase and not has_boot,
            ["Application", "Usecase"],
            "UsecaseRequiresBoot",
            "Src/Application/Usecase requires Src/Boot.",
        ),
        (
            has_adapter and not has_boot,
            ["Adapter"],
            "AdapterRequiresBoot",
            "Src/Adapter requires Src/Boot.",
        ),
        (
            has_adapter and not has_usecase,
            ["Adapter"],
            "AdapterRequiresUsecase",
            "Src/Adapter requires Src/Application/Usecase.",
        ),
        (
            has_port_in and not has_usecase,
            ["Application", "Port", "In"],
            "PortInRequiresUsecase",
            "Src/Application/Port/In requires Src/Application/Usecase.",
        ),
        (
            has_port_out and not has_adapter_out,
            ["Application", "Port", "Out"],
            "PortOutRequiresAdapterOut",
            "Src/Application/Port/Out requires Src/Adapter/Out.",
        ),
        (
            has_import and not has_adapter_out_module,
            ["Import"],
            "ImportRequiresAdapterOutModule",
            "Src/Import requires Src/Adapter/Out/Module.",
        ),
        (
            has_boot and not has_usecase,
            ["Boot"],
            "BootRequiresUsecase",
            "Src/Boot requires Src/Application/Usecase.",
        ),
    ]
    for violated, relative_prefix, rule_id, message in implication_rules:
        if not violated:
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Src", *relative_prefix],
                rule_id=rule_id,
                message=message,
                source_record_ids=[
                    _first_source_record_id_for_prefix(
                        source_record_ids,
                        relative_prefix,
                        module_record_id,
                    )
                ],
                module_id=module_id,
                module_role=module_role,
            )
        )


def _has_source_prefix(
    relative_paths: list[list[str]],
    prefix: list[str],
) -> bool:
    return any(path[: len(prefix)] == prefix for path in relative_paths)


def _first_source_record_id_for_prefix(
    source_record_ids: dict[tuple[str, ...], str],
    prefix: list[str],
    fallback_record_id: str,
) -> str:
    for relative_path, record_id in sorted(source_record_ids.items()):
        if list(relative_path[: len(prefix)]) == prefix:
            return record_id
    return fallback_record_id


def _scan_src(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    src_root: Path,
    module_path: list[str],
    module_id: str,
    module_role: str,
    src_record_id: str,
    source_record_ids: dict[tuple[str, ...], str],
) -> list[tuple[list[str], str, str]]:
    source_files: list[tuple[list[str], str, str]] = []
    for child in sorted(src_root.iterdir(), key=lambda path: path.name):
        if _is_process_carrier(child):
            continue
        name = child.name
        path_segments = [*module_path, "Src", name]
        if name not in SRC_AREA_NAMES or not child.is_dir() or child.is_symlink():
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="SrcDirectChildInvalid",
                    message=(
                        f"Src direct child '{name}' must be one of "
                        "Boot, Import, Domain, Application, or Adapter directories."
                    ),
                    source_record_ids=[src_record_id],
                    module_id=module_id,
                    module_role=module_role,
                )
            )
            continue

        area_record_id = _stable_id("record", ("sourceDirectory", *path_segments))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=area_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=_stable_id("sourceDirectory", tuple(path_segments)),
                entity_kind="SourceDirectory",
                module_id=module_id,
                module_role=module_role,
                vendor_governed=False,
                path_from_root=path_segments,
                canonical_path_segments=path_segments,
            )
        )
        if name != "Import":
            area_files = _scan_source_tree(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                tree_root=child,
                module_path=module_path,
                relative_prefix=[name],
                module_id=module_id,
                module_role=module_role,
                parent_record_id=area_record_id,
                source_record_ids=source_record_ids,
            )
            if not area_files:
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=path_segments,
                        rule_id="SourceAreaEmpty",
                        message=(
                            f"Src/{name} must recursively contain at least one "
                            "legal source file once present."
                        ),
                        source_record_ids=[area_record_id],
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
            source_files.extend(area_files)
        else:
            import_files = _scan_import_files(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                import_root=child,
                module_path=module_path,
                module_id=module_id,
                module_role=module_role,
                import_record_id=area_record_id,
                source_record_ids=source_record_ids,
            )
            if not import_files:
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=path_segments,
                        rule_id="ImportAreaEmpty",
                        message=(
                            "Src/Import must contain at least one legal Import "
                            "file once present."
                        ),
                        source_record_ids=[area_record_id],
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
            source_files.extend(import_files)
    if not source_files:
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Src"],
                rule_id="SrcContainsNoSource",
                message=(
                    "Src must contain at least one legal source file under "
                    "Boot, Domain, Application, or Adapter, or one legal Import file."
                ),
                source_record_ids=[src_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )
    return source_files


def _scan_import_files(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    import_root: Path,
    module_path: list[str],
    module_id: str,
    module_role: str,
    import_record_id: str,
    source_record_ids: dict[tuple[str, ...], str],
) -> list[tuple[list[str], str, str]]:
    import_files: list[tuple[list[str], str, str]] = []
    for child in sorted(import_root.iterdir(), key=lambda path: path.name):
        if _is_process_carrier(child):
            continue
        path_segments = [*module_path, "Src", "Import", child.name]
        if child.is_dir() or child.is_symlink() or not child.is_file():
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="ImportCarrierInvalid",
                    message="Src/Import may contain only regular Import files.",
                    source_record_ids=[import_record_id],
                    module_id=module_id,
                    module_role=module_role,
                )
            )
            continue
        if child.suffix == "":
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="ImportFileNameInvalid",
                    message=f"Import file '{child.name}' must include a module extension.",
                    source_record_ids=[import_record_id],
                    module_id=module_id,
                    module_role=module_role,
                )
            )
            continue
        source_record_id = _stable_id("record", ("importFile", *path_segments))
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=source_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=_stable_id("importFile", tuple(path_segments)),
                entity_kind="ImportFile",
                module_id=module_id,
                module_role=module_role,
                vendor_governed=False,
                path_from_root=path_segments,
                canonical_path_segments=path_segments,
            )
        )
        relative_path = ["Import", child.name]
        source_record_ids[tuple(relative_path)] = source_record_id
        import_files.append((relative_path, child.stem, child.suffix))
    return import_files


def _scan_source_tree(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    tree_root: Path,
    module_path: list[str],
    relative_prefix: list[str],
    module_id: str,
    module_role: str,
    parent_record_id: str,
    source_record_ids: dict[tuple[str, ...], str],
) -> list[tuple[list[str], str, str]]:
    source_files: list[tuple[list[str], str, str]] = []
    for child in sorted(tree_root.iterdir(), key=lambda path: path.name):
        if _is_process_carrier(child):
            continue
        relative_path = [*relative_prefix, child.name]
        path_segments = [*module_path, "Src", *relative_path]
        if child.is_dir() and not child.is_symlink():
            if not _is_structure_segment(child.name):
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=path_segments,
                        rule_id="SourceDirectoryNameInvalid",
                        message=f"Source directory '{child.name}' is not a structure segment.",
                        source_record_ids=[parent_record_id],
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
                continue
            directory_record_id = _stable_id(
                "record", ("sourceDirectory", *path_segments)
            )
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=directory_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("sourceDirectory", tuple(path_segments)),
                    entity_kind="SourceDirectory",
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            directory_files = _scan_source_tree(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                tree_root=child,
                module_path=module_path,
                relative_prefix=relative_path,
                module_id=module_id,
                module_role=module_role,
                parent_record_id=directory_record_id,
                source_record_ids=source_record_ids,
            )
            if not directory_files:
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=path_segments,
                        rule_id="SourceDirectoryEmpty",
                        message=(
                            f"Source directory '{child.name}' must recursively "
                            "contain at least one legal source file."
                        ),
                        source_record_ids=[directory_record_id],
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
            source_files.extend(directory_files)
            continue

        if child.is_file() and not child.is_symlink():
            if child.suffix == "" or not _is_structure_segment(child.stem):
                records.append(
                    _finding_record(
                        root=root,
                        state_version=state_version,
                        excluded=excluded,
                        path_from_root=path_segments,
                        rule_id="SourceFileNameInvalid",
                        message=f"Source file '{child.name}' is not a legal source carrier.",
                        source_record_ids=[parent_record_id],
                        module_id=module_id,
                        module_role=module_role,
                    )
                )
                continue
            source_record_id = _stable_id("record", ("sourceFile", *path_segments))
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=source_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("sourceFile", tuple(path_segments)),
                    entity_kind="SourceFile",
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            source_record_ids[tuple(relative_path)] = source_record_id
            source_files.append((relative_path, child.stem, child.suffix))
            continue

        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=path_segments,
                rule_id="SourceCarrierInvalid",
                message=f"Source carrier '{child.name}' must be a regular file or directory.",
                source_record_ids=[parent_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )
    return source_files


def _scan_test(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    test_root: Path,
    module_path: list[str],
    module_id: str,
    module_role: str,
    test_record_id: str,
) -> tuple[list[list[str]], list[list[str]]]:
    test_files: list[list[str]] = []
    test_directories: list[list[str]] = []
    for child in sorted(test_root.iterdir(), key=lambda path: path.name):
        if _is_process_carrier(child):
            continue
        name = child.name
        path_segments = [*module_path, "Test", name]
        if name not in SRC_AREA_NAMES or not child.is_dir() or child.is_symlink():
            records.append(
                _finding_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    path_from_root=path_segments,
                    rule_id="TestDirectChildInvalid",
                    message=(
                        f"Test direct child '{name}' must be one of "
                        "Boot, Import, Domain, Application, or Adapter directories."
                    ),
                    source_record_ids=[test_record_id],
                    module_id=module_id,
                    module_role=module_role,
                )
            )
            continue
        directory_record_id = _stable_id("record", ("testDirectory", *path_segments))
        test_directories.append([name])
        records.append(
            _base_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                record_id=directory_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=_stable_id("testDirectory", tuple(path_segments)),
                entity_kind="TestDirectory",
                module_id=module_id,
                module_role=module_role,
                vendor_governed=False,
                path_from_root=path_segments,
                canonical_path_segments=path_segments,
            )
        )
        _scan_test_tree(
            root=root,
            state_version=state_version,
            excluded=excluded,
            records=records,
            tree_root=child,
            module_path=module_path,
            relative_prefix=[name],
            module_id=module_id,
            module_role=module_role,
            parent_record_id=directory_record_id,
            test_files=test_files,
            test_directories=test_directories,
        )
    return test_files, test_directories


def _scan_test_tree(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    tree_root: Path,
    module_path: list[str],
    relative_prefix: list[str],
    module_id: str,
    module_role: str,
    parent_record_id: str,
    test_files: list[list[str]],
    test_directories: list[list[str]],
) -> None:
    for child in sorted(tree_root.iterdir(), key=lambda path: path.name):
        if _is_process_carrier(child):
            continue
        relative_path = [*relative_prefix, child.name]
        path_segments = [*module_path, "Test", *relative_path]
        if child.is_dir() and not child.is_symlink():
            directory_record_id = _stable_id("record", ("testDirectory", *path_segments))
            test_directories.append(relative_path)
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=directory_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("testDirectory", tuple(path_segments)),
                    entity_kind="TestDirectory",
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            _scan_test_tree(
                root=root,
                state_version=state_version,
                excluded=excluded,
                records=records,
                tree_root=child,
                module_path=module_path,
                relative_prefix=relative_path,
                module_id=module_id,
                module_role=module_role,
                parent_record_id=directory_record_id,
                test_files=test_files,
                test_directories=test_directories,
            )
            continue
        if child.is_file() and not child.is_symlink():
            test_files.append(relative_path)
            records.append(
                _base_record(
                    root=root,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=_stable_id("record", ("testFile", *path_segments)),
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=_stable_id("testFile", tuple(path_segments)),
                    entity_kind="TestFile",
                    module_id=module_id,
                    module_role=module_role,
                    vendor_governed=False,
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=path_segments,
                rule_id="TestCarrierInvalid",
                message=f"Test carrier '{child.name}' must be a regular file or directory.",
                source_record_ids=[parent_record_id],
                module_id=module_id,
                module_role=module_role,
            )
        )


def _check_test_mirrors(
    *,
    root: Path,
    state_version: str,
    excluded: list[str],
    records: list[StructureRecord],
    module_root: Path,
    module_path: list[str],
    module_id: str,
    module_role: str,
    source_files: list[tuple[list[str], str, str]],
    source_record_ids: dict[tuple[str, ...], str],
    test_files: list[list[str]],
    test_directories: list[list[str]],
) -> None:
    expected_files: set[tuple[str, ...]] = set()
    expected_directories: set[tuple[str, ...]] = set()
    invalid_test_files: set[tuple[str, ...]] = set()
    source_suffixes = {suffix for _relative_path, _source_stem, suffix in source_files}
    module_suffix = next(iter(source_suffixes)) if len(source_suffixes) == 1 else None
    for relative_path, source_stem, suffix in source_files:
        expected_relative = [*relative_path[:-1], f"{source_stem}.Test{suffix}"]
        expected_files.add(tuple(expected_relative))
        for index in range(1, len(expected_relative)):
            expected_directories.add(tuple(expected_relative[:index]))
        expected_path = module_root / "Test" / Path(*expected_relative)
        if expected_path.is_file() and not expected_path.is_symlink():
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Test", *expected_relative],
                rule_id="TestMirrorMissing",
                message=(
                    "Source file requires an exact mirrored test file at "
                    f"Test/{'/'.join(expected_relative)}."
                ),
                source_record_ids=[
                    source_record_ids.get(tuple(relative_path), "")
                ],
                module_id=module_id,
                module_role=module_role,
            )
        )

    for test_file in sorted(test_files):
        if _is_valid_test_file_name(test_file[-1], module_suffix):
            continue
        invalid_test_files.add(tuple(test_file))
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Test", *test_file],
                rule_id="TestFileNameInvalid",
                message=(
                    "Test file must be named <mirrored_source_stem>.Test.<ext> "
                    "and use the module source extension."
                ),
                source_record_ids=[],
                finding_kind="TestMirrorExtra",
                module_id=module_id,
                module_role=module_role,
            )
        )

    for test_directory in sorted(test_directories):
        if tuple(test_directory) in expected_directories:
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Test", *test_directory],
                rule_id="TestMirrorExtra",
                message=(
                    "Test directory has no corresponding source mirror path: "
                    f"Test/{'/'.join(test_directory)}."
                ),
                source_record_ids=[],
                finding_kind="TestMirrorExtra",
                module_id=module_id,
                module_role=module_role,
            )
        )

    for test_file in sorted(test_files):
        if tuple(test_file) in invalid_test_files:
            continue
        if tuple(test_file) in expected_files:
            continue
        records.append(
            _finding_record(
                root=root,
                state_version=state_version,
                excluded=excluded,
                path_from_root=[*module_path, "Test", *test_file],
                rule_id="TestMirrorExtra",
                message=(
                    "Test file has no corresponding source file: "
                    f"Test/{'/'.join(test_file)}."
                ),
                source_record_ids=[],
                finding_kind="TestMirrorExtra",
                module_id=module_id,
                module_role=module_role,
            )
        )


def _is_valid_test_file_name(file_name: str, module_suffix: str | None) -> bool:
    path = Path(file_name)
    if path.suffix == "":
        return False
    if module_suffix is not None and path.suffix != module_suffix:
        return False
    stem = path.stem
    if not stem.endswith(".Test"):
        return False
    mirrored_stem = stem[: -len(".Test")]
    return bool(mirrored_stem)


def scan_product_project_root(root: str | Path) -> list[dict[str, Any]]:
    """Project a repository root using the AGENTS product-root profile."""
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir() or root_path.is_symlink():
        raise ValueError(f"scan root must be a real directory: {root}")

    excluded = sorted(name for name in ROOT_EXCLUSIONS if (root_path / name).exists())
    state_version = _state_version(root_path, excluded)
    records: list[StructureRecord] = []

    root_entity_id = "projectRootProject"
    records.append(
        _base_record(
            root=root_path,
            state_version=state_version,
            excluded=excluded,
            record_id="recordRootProject",
            record_kind="StructureEntity",
            operation_kind="StructureCandidateProjection",
            entity_id=root_entity_id,
            entity_kind="Project",
            path_from_root=[],
            canonical_path_segments=[],
        )
    )

    for child in sorted(root_path.iterdir(), key=lambda path: path.name):
        name = child.name
        if name in excluded:
            continue

        path_segments = [name]
        if name in PROJECT_ROLE_SPACE_NAMES:
            entity_id = _stable_id("roleSpace", tuple(path_segments))
            record_id = _stable_id("record", ("role", name))
            records.append(
                _base_record(
                    root=root_path,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=entity_id,
                    entity_kind="ModuleRoleSpace",
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            _scan_role_space(
                root=root_path,
                state_version=state_version,
                excluded=excluded,
                records=records,
                role_space=child,
                role_name=name,
                role_record_id=record_id,
            )
            continue

        if name in PROJECT_EMBEDDED_WORKSPACE_NAMES:
            entity_id = _stable_id("workspace", tuple(path_segments))
            workspace_record_id = _stable_id("record", ("workspace", name))
            records.append(
                _base_record(
                    root=root_path,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=workspace_record_id,
                    record_kind="StructureEntity",
                    operation_kind="StructureCandidateProjection",
                    entity_id=entity_id,
                    entity_kind="EmbeddedWorkspace",
                    path_from_root=path_segments,
                    canonical_path_segments=path_segments,
                )
            )
            _validate_embedded_workspace_carrier(
                root=root_path,
                state_version=state_version,
                excluded=excluded,
                records=records,
                workspace_root=child,
                workspace_path=path_segments,
                workspace_record_id=workspace_record_id,
            )
            continue

        if name in {"Vendor", "Workspace"} or _is_reserved_case_variant(name):
            finding_id = _stable_id("finding", ("projectReserved", name))
            records.append(
                _base_record(
                    root=root_path,
                    state_version=state_version,
                    excluded=excluded,
                    record_id=_stable_id("record", ("finding", name)),
                    record_kind="Finding",
                    operation_kind="StructureCandidateProjection",
                    entity_id=None,
                    entity_kind=None,
                    path_from_root=path_segments,
                    finding_id=finding_id,
                    finding_kind="StructureClosureError",
                    severity="error",
                    rule_id="ProjectDirectReservedName",
                    message=(
                        f"Project direct child '{name}' is reserved here and "
                        "cannot be a free remainder."
                    ),
                    source_record_ids=["recordRootProject"],
                )
            )
            continue

        entity_id = _stable_id("free", tuple(path_segments))
        free_record_id = _stable_id("record", ("free", name))
        records.append(
            _base_record(
                root=root_path,
                state_version=state_version,
                excluded=excluded,
                record_id=free_record_id,
                record_kind="StructureEntity",
                operation_kind="StructureCandidateProjection",
                entity_id=entity_id,
                entity_kind="FreeRemainder",
                path_from_root=path_segments,
                canonical_path_segments=[],
            )
        )
        _validate_free_remainder_carrier(
            root=root_path,
            state_version=state_version,
            excluded=excluded,
            records=records,
            carrier=child,
            path_from_root=path_segments,
            source_record_id=free_record_id,
        )

    sorted_records = sorted(
        records,
        key=lambda record: (
            record.recordKind,
            record.canonicalPathSegments,
            record.entityId or "",
            record.findingKind or "",
            record.recordId,
        ),
    )
    return [record.as_dict() for record in sorted_records]


def summarize_structure_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    findings = 0
    for record in records:
        entity_kind = record.get("entityKind") or record.get("recordKind")
        by_kind[str(entity_kind)] = by_kind.get(str(entity_kind), 0) + 1
        if record.get("recordKind") == "Finding":
            findings += 1
    return {
        "record_count": len(records),
        "finding_count": findings,
        "entity_kind_counts": dict(sorted(by_kind.items())),
    }
