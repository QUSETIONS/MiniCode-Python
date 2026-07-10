from __future__ import annotations

import json
from pathlib import Path

import pytest

from minicode.engineering_structure import (
    ROOT_PROJECT_ID,
    check_product_project_compliance,
    scan_product_project_root,
    summarize_structure_projection,
)
from minicode.structure_check import check_material_inventory
from minicode.structure_check import main as structure_check_main
from Package.EngineeringStructure.Src.Application.Query.ProductRootProjection import (
    scan_product_project_root as scan_product_project_root_from_package,
)


REQUIRED_RECORD_FIELDS = {
    "recordId",
    "recordKind",
    "methodVersion",
    "stateVersion",
    "rootProfile",
    "rootProjectId",
    "excludedRootEntries",
    "operationKind",
    "entityId",
    "entityKind",
    "projectId",
    "moduleId",
    "moduleRole",
    "vendorGoverned",
    "sameProjectScope",
    "pathFromRoot",
    "canonicalPathSegments",
    "importStem",
    "findingId",
    "findingKind",
    "severity",
    "ruleId",
    "message",
    "sourceRecordIds",
}


def test_product_root_projection_emits_required_payload_fields(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "minicode").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)

    assert records
    assert all(set(record) == REQUIRED_RECORD_FIELDS for record in records)
    assert {record["rootProjectId"] for record in records} == {ROOT_PROJECT_ID}
    assert {record["rootProfile"] for record in records} == {"ProductProjectRoot"}
    assert all(record["excludedRootEntries"] == [".git"] for record in records)


def test_minicode_projection_api_is_package_compatibility_surface() -> None:
    assert scan_product_project_root is scan_product_project_root_from_package


def test_current_repository_compliance_check_passes() -> None:
    result = check_product_project_compliance(Path(__file__).resolve().parent.parent)

    assert result["passed"] is True
    assert result["summary"]["total_finding_count"] == 0
    assert result["summary"]["dependency_edge_count"] > 0
    assert all(edge["allowed"] for edge in result["dependencyEdges"])


def test_structure_check_cli_reports_success(capsys: pytest.CaptureFixture[str]) -> None:
    code = structure_check_main(["--root", str(Path(__file__).resolve().parent.parent)])
    captured = capsys.readouterr()

    assert code == 0
    assert "AGENTS structure compliance: passed" in captured.out
    assert "dependency edges:" in captured.out
    assert "dependency impact nodes:" in captured.out
    assert "dependency impact hotspots:" in captured.out
    assert "max dependency direct upstream:" in captured.out
    assert "same-project import dependency edges:" in captured.out
    assert "vendor import dependency edges:" in captured.out
    assert "cross-project import dependency edges:" in captured.out
    assert "import impact nodes:" in captured.out
    assert "import impact hotspots:" in captured.out
    assert "max import transitive upstream:" in captured.out
    assert "import findings:" in captured.out
    assert "total findings: 0" in captured.out


def test_structure_check_cli_can_gate_material_inventory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "structure-report.json"

    code = structure_check_main(
        [
            "--root",
            str(Path(__file__).resolve().parent.parent),
            "--check-material-inventory",
            "--report",
            str(report_path),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == 0
    assert "material inventory findings: 0" in captured.out
    assert payload["materialInventory"]["passed"] is True
    assert payload["materialInventory"]["summary"]["focused_gate_count"] >= 15
    assert payload["qualityGateFindings"] == []


def test_material_inventory_gate_reports_missing_required_gate(tmp_path: Path) -> None:
    (tmp_path / "Docs" / "Documentation" / "engineering").mkdir(parents=True)
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / "README.zh-CN.md").write_text("", encoding="utf-8")
    inventory_path = tmp_path / "Docs" / "Documentation" / "engineering" / "material-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "currentProductApp": {
                    "logicalBoundary": "product/app/minicode_frontline",
                    "currentSourceRoot": "minicode",
                    "entrySurfaces": [],
                    "coverageEvidence": [],
                },
                "materials": [],
                "focusedGates": [
                    {
                        "name": "compileall",
                        "command": "python -m compileall -q minicode",
                        "portableFallback": "python3 -m compileall -q minicode",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    check = check_material_inventory(tmp_path)
    messages = "\n".join(finding["message"] for finding in check["findings"])

    assert check["passed"] is False
    assert "focusedGates missing release-markdown-report-gate" in messages
    assert "currentProductApp.entrySurfaces" in messages


def test_material_inventory_allows_declared_optional_workspace_material_to_be_absent(
    tmp_path: Path,
) -> None:
    inventory_dir = tmp_path / "Docs" / "Documentation" / "engineering"
    inventory_dir.mkdir(parents=True)
    (tmp_path / "README.md").write_text("evidence", encoding="utf-8")
    (tmp_path / "README.zh-CN.md").write_text("evidence", encoding="utf-8")
    (inventory_dir / "material-inventory.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "currentProductApp": {
                    "logicalBoundary": "product/app/minicode_frontline",
                    "currentSourceRoot": "minicode",
                    "entrySurfaces": [{"path": "README.md"}],
                    "coverageEvidence": [{"path": "README.md"}],
                },
                "materials": [
                    {
                        "path": "workspace-reference",
                        "identity": "local reference checkout",
                        "status": "archive-approved-reference-only",
                        "presencePolicy": "optional-workspace-material",
                        "callerSummary": "No current callers.",
                        "replacementTarget": "README.md",
                        "retirementCondition": "Retained outside clean checkout.",
                        "observedEntries": [
                            {"name": "reference", "path": "workspace-reference/README.md", "result": "observed locally"}
                        ],
                        "coverageEvidence": [{"path": "README.md", "reason": "tracked evidence"}],
                        "currentCallers": [],
                        "historicalReferences": [],
                    }
                ],
                "focusedGates": [],
            }
        ),
        encoding="utf-8",
    )

    check = check_material_inventory(tmp_path)
    messages = "\n".join(finding["message"] for finding in check["findings"])

    assert "missing repo path: workspace-reference" not in messages
    assert "workspace-reference/README.md" not in messages


def test_structure_check_cli_can_print_impact_hotspots(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = structure_check_main(
        [
            "--root",
            str(Path(__file__).resolve().parent.parent),
            "--hotspots",
            "1",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert "dependency impact hotspots:" in captured.out
    assert "direct upstream:" in captured.out
    assert "Src/" in captured.out


def test_structure_check_cli_can_fail_dependency_hotspot_threshold(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dto_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Dto"
    query_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Query"
    test_dto_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Dto"
    test_query_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Query"
    dto_dir.mkdir(parents=True)
    query_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "FirstQuery.py").write_text(
        "from ..Dto.Payload import VALUE\n",
        encoding="utf-8",
    )
    (query_dir / "SecondQuery.py").write_text(
        "from ..Dto.Payload import VALUE\n",
        encoding="utf-8",
    )
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "FirstQuery.Test.py").write_text(
        "def test_first_query():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "SecondQuery.Test.py").write_text(
        "def test_second_query():\n    assert True\n",
        encoding="utf-8",
    )

    code = structure_check_main(
        [
            "--root",
            str(tmp_path),
            "--max-dependency-upstream",
            "1",
            "--hotspots",
            "1",
        ]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert "AGENTS structure compliance: failed" in captured.out
    assert "DependencyImpactThreshold" in captured.out
    assert "Payload.py" in captured.out
    assert "quality gate findings: 1" in captured.out


def test_structure_check_cli_writes_json_report(tmp_path: Path) -> None:
    report_path = tmp_path / "structure-report.json"

    code = structure_check_main(
        [
            "--root",
            str(Path(__file__).resolve().parent.parent),
            "--report",
            str(report_path),
        ]
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["passed"] is True
    assert payload["cliPassed"] is True
    assert payload["qualityGatePassed"] is True
    assert payload["qualityGateFindings"] == []
    assert payload["summary"]["total_finding_count"] == 0
    assert payload["summary"]["finding_kind_counts"] == {}
    assert payload["summary"]["rule_id_counts"] == {}
    assert payload["summary"]["dependency_edge_count"] == len(payload["dependencyEdges"])
    assert payload["summary"]["dependency_impact_node_count"] == len(
        payload["dependencyImpact"]
    )
    assert payload["summary"]["max_dependency_direct_upstream_count"] == max(
        (
            len(record["directUpstreamSourcePaths"])
            for record in payload["dependencyImpact"]
        ),
        default=0,
    )
    assert payload["dependencyImpactHotspots"] == sorted(
        [
            record
            for record in payload["dependencyImpact"]
            if record["directUpstreamCount"] > 0
        ],
        key=lambda record: (
            -record["directUpstreamCount"],
            record["sourcePathFromRoot"],
        ),
    )[:5]
    assert payload["summary"]["import_dependency_edge_count"] == len(
        payload["importDependencyEdges"]
    )
    assert payload["summary"]["same_project_import_dependency_edge_count"] == sum(
        1 for edge in payload["importDependencyEdges"] if edge["sameProjectScope"]
    )
    assert payload["summary"]["vendor_import_dependency_edge_count"] == sum(
        1
        for edge in payload["importDependencyEdges"]
        if not edge["sameProjectScope"]
        and len(edge["targetModuleRoot"]) > len(edge["sourceModuleRoot"])
        and edge["targetModuleRoot"][: len(edge["sourceModuleRoot"])]
        == edge["sourceModuleRoot"]
        and edge["targetModuleRoot"][len(edge["sourceModuleRoot"])] == "Vendor"
    )
    assert payload["summary"]["cross_project_import_dependency_edge_count"] == sum(
        1
        for edge in payload["importDependencyEdges"]
        if not edge["sameProjectScope"]
        and not (
            len(edge["targetModuleRoot"]) > len(edge["sourceModuleRoot"])
            and edge["targetModuleRoot"][: len(edge["sourceModuleRoot"])]
            == edge["sourceModuleRoot"]
            and edge["targetModuleRoot"][len(edge["sourceModuleRoot"])] == "Vendor"
        )
    )
    assert payload["summary"]["import_impact_node_count"] == len(
        payload["importImpact"]
    )
    assert payload["summary"]["max_import_transitive_upstream_count"] == max(
        (
            len(record["transitiveUpstreamModuleRoots"])
            for record in payload["importImpact"]
        ),
        default=0,
    )
    assert payload["importImpactHotspots"] == sorted(
        [
            record
            for record in payload["importImpact"]
            if record["transitiveUpstreamCount"] > 0
        ],
        key=lambda record: (
            -record["transitiveUpstreamCount"],
            -record["directUpstreamCount"],
            record["moduleRoot"],
        ),
    )[:5]


def test_projection_recognizes_package_module_source_and_test_mirror(
    tmp_path: Path,
) -> None:
    source_dir = (
        tmp_path
        / "Package"
        / "EngineeringStructure"
        / "Src"
        / "Application"
        / "Query"
    )
    test_dir = (
        tmp_path
        / "Package"
        / "EngineeringStructure"
        / "Test"
        / "Application"
        / "Query"
    )
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "ProductRootProjection.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "ProductRootProjection.Test.py").write_text(
        "def test_value():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)
    by_kind = {
        tuple(record["pathFromRoot"]): record
        for record in records
        if record["recordKind"] == "StructureEntity"
    }

    module_record = by_kind[("Package", "EngineeringStructure")]
    source_record = by_kind[
        (
            "Package",
            "EngineeringStructure",
            "Src",
            "Application",
            "Query",
            "ProductRootProjection.py",
        )
    ]
    test_record = by_kind[
        (
            "Package",
            "EngineeringStructure",
            "Test",
            "Application",
            "Query",
            "ProductRootProjection.Test.py",
        )
    ]

    assert module_record["entityKind"] == "Module"
    assert module_record["moduleRole"] == "Package"
    assert source_record["entityKind"] == "SourceFile"
    assert source_record["moduleId"] == module_record["moduleId"]
    assert test_record["entityKind"] == "TestFile"
    assert not [record for record in records if record["recordKind"] == "Finding"]


def test_projection_reports_missing_test_mirror_for_source_file(tmp_path: Path) -> None:
    source_dir = (
        tmp_path
        / "Package"
        / "EngineeringStructure"
        / "Src"
        / "Application"
        / "Query"
    )
    (tmp_path / "Package" / "EngineeringStructure" / "Test").mkdir(parents=True)
    source_dir.mkdir(parents=True)
    (source_dir / "ProductRootProjection.py").write_text("VALUE = 1\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)
    findings = [record for record in records if record["recordKind"] == "Finding"]

    assert any(finding["ruleId"] == "TestMirrorMissing" for finding in findings)


def test_projection_recognizes_import_file_and_test_mirror(tmp_path: Path) -> None:
    boot_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Boot"
    usecase_dir = (
        tmp_path
        / "Package"
        / "SourceModule"
        / "Src"
        / "Application"
        / "Usecase"
    )
    adapter_dir = (
        tmp_path
        / "Package"
        / "SourceModule"
        / "Src"
        / "Adapter"
        / "Out"
        / "Module"
    )
    import_dir = (
        tmp_path
        / "Package"
        / "SourceModule"
        / "Src"
        / "Import"
    )
    test_boot_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Boot"
    test_usecase_dir = (
        tmp_path
        / "Package"
        / "SourceModule"
        / "Test"
        / "Application"
        / "Usecase"
    )
    test_adapter_dir = (
        tmp_path
        / "Package"
        / "SourceModule"
        / "Test"
        / "Adapter"
        / "Out"
        / "Module"
    )
    test_import_dir = (
        tmp_path
        / "Package"
        / "SourceModule"
        / "Test"
        / "Import"
    )
    boot_dir.mkdir(parents=True)
    usecase_dir.mkdir(parents=True)
    adapter_dir.mkdir(parents=True)
    import_dir.mkdir(parents=True)
    test_boot_dir.mkdir(parents=True)
    test_usecase_dir.mkdir(parents=True)
    test_adapter_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (usecase_dir / "RunSource.py").write_text("VALUE = 1\n", encoding="utf-8")
    (adapter_dir / "TargetBinding.py").write_text("VALUE = 1\n", encoding="utf-8")
    (import_dir / "1-Package-TargetModule.py").write_text("", encoding="utf-8")
    (test_boot_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )
    (test_usecase_dir / "RunSource.Test.py").write_text(
        "def test_run_source():\n    assert True\n",
        encoding="utf-8",
    )
    (test_adapter_dir / "TargetBinding.Test.py").write_text(
        "def test_target_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (test_import_dir / "1-Package-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)
    import_record = next(
        record
        for record in records
        if record["pathFromRoot"]
        == ["Package", "SourceModule", "Src", "Import", "1-Package-TargetModule.py"]
    )

    assert import_record["entityKind"] == "ImportFile"
    assert not [record for record in records if record["recordKind"] == "Finding"]


def test_product_root_projection_keeps_root_basename_out_of_canonical_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "Main").mkdir()
    (tmp_path / "free-dir").mkdir()

    records = scan_product_project_root(tmp_path)
    root_record = next(record for record in records if record["entityKind"] == "Project")
    role_record = next(record for record in records if record["entityKind"] == "ModuleRoleSpace")
    free_record = next(record for record in records if record["entityKind"] == "FreeRemainder")

    assert root_record["canonicalPathSegments"] == []
    assert role_record["canonicalPathSegments"] == ["Main"]
    assert free_record["canonicalPathSegments"] == []
    assert tmp_path.name not in role_record["canonicalPathSegments"]


@pytest.mark.parametrize("reserved_name", ["Vendor", "Workspace", "vendor"])
def test_project_direct_vendor_and_workspace_are_findings(
    tmp_path: Path,
    reserved_name: str,
) -> None:
    (tmp_path / reserved_name).mkdir()

    records = scan_product_project_root(tmp_path)
    findings = [record for record in records if record["recordKind"] == "Finding"]

    assert {finding["pathFromRoot"][0] for finding in findings} == {reserved_name}
    assert {finding["findingKind"] for finding in findings} == {"StructureClosureError"}
    assert {finding["ruleId"] for finding in findings} == {"ProjectDirectReservedName"}
    assert all(finding["severity"] == "error" for finding in findings)
    assert all(finding["sourceRecordIds"] == ["recordRootProject"] for finding in findings)


def test_projection_summary_counts_findings_and_entities(tmp_path: Path) -> None:
    (tmp_path / "Main").mkdir()
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Vendor").mkdir()
    (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")

    summary = summarize_structure_projection(scan_product_project_root(tmp_path))

    assert summary["finding_count"] == 2
    assert summary["entity_kind_counts"]["Project"] == 1
    assert summary["entity_kind_counts"]["ModuleRoleSpace"] == 1
    assert summary["entity_kind_counts"]["EmbeddedWorkspace"] == 1
    assert summary["entity_kind_counts"]["FreeRemainder"] == 1


def test_projection_rejects_non_directory_root(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="scan root must be a real directory"):
        scan_product_project_root(target)


def test_current_repository_projection_accepts_canonical_docs_workspace() -> None:
    records = scan_product_project_root(Path(__file__).resolve().parent.parent)
    findings = [record for record in records if record["recordKind"] == "Finding"]
    docs_record = next(
        record for record in records if record["pathFromRoot"] == ["Docs"]
    )

    assert docs_record["entityKind"] == "EmbeddedWorkspace"
    assert not any(
        finding["ruleId"] == "ProjectDirectReservedName"
        for finding in findings
    )
