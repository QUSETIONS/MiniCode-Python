from __future__ import annotations

from pathlib import Path

from Package.EngineeringStructure.Src.Application.Query.ProductRootProjection import (
    ROOT_PROJECT_ID,
    scan_product_project_root,
)


def test_product_root_projection_reports_project_identity(tmp_path: Path) -> None:
    (tmp_path / "Main").mkdir()

    records = scan_product_project_root(tmp_path)
    project_record = next(record for record in records if record["entityKind"] == "Project")

    assert project_record["rootProjectId"] == ROOT_PROJECT_ID
    assert project_record["canonicalPathSegments"] == []


def test_product_root_projection_reports_empty_src(tmp_path: Path) -> None:
    (tmp_path / "Package" / "Demo" / "Src").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding" and record["ruleId"] == "SrcContainsNoSource"
        for record in records
    )


def test_product_root_projection_reports_empty_source_area(tmp_path: Path) -> None:
    (tmp_path / "Package" / "Demo" / "Src" / "Application").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding" and record["ruleId"] == "SourceAreaEmpty"
        for record in records
    )


def test_product_root_projection_reports_empty_source_directory(tmp_path: Path) -> None:
    (tmp_path / "Package" / "Demo" / "Src" / "Application" / "Query").mkdir(
        parents=True
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "SourceDirectoryEmpty"
        for record in records
    )


def test_product_root_projection_reports_empty_import_area(tmp_path: Path) -> None:
    (tmp_path / "Package" / "Demo" / "Src" / "Import").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding" and record["ruleId"] == "ImportAreaEmpty"
        for record in records
    )


def test_product_root_projection_reports_test_direct_file(tmp_path: Path) -> None:
    test_root = tmp_path / "Package" / "Demo" / "Test"
    test_root.mkdir(parents=True)
    (test_root / "Loose.Test.py").write_text("def test_loose(): pass\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "TestDirectChildInvalid"
        for record in records
    )


def test_product_root_projection_reports_unknown_test_direct_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Demo" / "Test" / "Loose").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "TestDirectChildInvalid"
        for record in records
    )


def test_product_root_projection_reports_usecase_without_boot(tmp_path: Path) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Usecase"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Usecase"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "RunDemo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "RunDemo.Test.py").write_text(
        "def test_run_demo():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding" and record["ruleId"] == "UsecaseRequiresBoot"
        for record in records
    )


def test_product_root_projection_reports_boot_without_usecase(tmp_path: Path) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Boot"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Boot"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding" and record["ruleId"] == "BootRequiresUsecase"
        for record in records
    )


def test_product_root_projection_reports_adapter_without_runtime_closure(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Adapter" / "In"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Adapter" / "In"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "CliAdapter.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "CliAdapter.Test.py").write_text(
        "def test_cli_adapter():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)
    rule_ids = {record["ruleId"] for record in records if record["recordKind"] == "Finding"}

    assert "AdapterRequiresBoot" in rule_ids
    assert "AdapterRequiresUsecase" in rule_ids


def test_product_root_projection_reports_port_in_without_usecase(tmp_path: Path) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Port" / "In"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Port" / "In"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "RunDemo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "RunDemo.Test.py").write_text(
        "def test_run_demo():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding" and record["ruleId"] == "PortInRequiresUsecase"
        for record in records
    )


def test_product_root_projection_reports_port_out_without_adapter_out(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Port" / "Out"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Port" / "Out"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "DemoStore.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "DemoStore.Test.py").write_text(
        "def test_demo_store():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "PortOutRequiresAdapterOut"
        for record in records
    )


def test_product_root_projection_reports_import_without_module_adapter_consumer(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Import"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Import"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "1-Target.py").write_text("", encoding="utf-8")
    (test_dir / "1-Target.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "ImportRequiresAdapterOutModule"
        for record in records
    )


def test_product_root_projection_reports_module_extension_conflict(
    tmp_path: Path,
) -> None:
    dto_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    query_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Query"
    test_dto_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    test_query_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Query"
    dto_dir.mkdir(parents=True)
    query_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "GetDemo.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "GetDemo.Test.ts").write_text(
        "export const value = true;\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "ModuleExtensionConflict"
        and record["findingKind"] == "ModuleExtensionConflict"
        for record in records
    )


def test_product_root_projection_reports_duplicate_source_stem(
    tmp_path: Path,
) -> None:
    dto_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    query_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Query"
    test_dto_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    test_query_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Query"
    dto_dir.mkdir(parents=True)
    query_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "Payload.py").write_text("VALUE = 2\n", encoding="utf-8")
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload_dto():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "Payload.Test.py").write_text(
        "def test_payload_query():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert sum(
        1
        for record in records
        if record["recordKind"] == "Finding"
        and record["ruleId"] == "SourceStemDuplicate"
        and record["findingKind"] == "UniquenessConflict"
    ) == 2


def test_product_root_projection_reports_extra_test_file(tmp_path: Path) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "Extra.Test.py").write_text(
        "def test_extra():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "TestMirrorExtra"
        and record["findingKind"] == "TestMirrorExtra"
        and record["pathFromRoot"][-1] == "Extra.Test.py"
        for record in records
    )


def test_product_root_projection_reports_test_area_without_source_area(
    tmp_path: Path,
) -> None:
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Domain" / "Model"
    test_dir.mkdir(parents=True)
    (test_dir / "Entity.Test.py").write_text(
        "def test_entity():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "TestMirrorExtra"
        and record["findingKind"] == "TestMirrorExtra"
        and record["pathFromRoot"][:4] == ["Package", "Demo", "Test", "Domain"]
        for record in records
    )


def test_product_root_projection_reports_invalid_test_file_name(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "PayloadSpec.py").write_text(
        "def test_payload_spec():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "TestFileNameInvalid"
        and record["findingKind"] == "TestMirrorExtra"
        and record["pathFromRoot"][-1] == "PayloadSpec.py"
        for record in records
    )


def test_product_root_projection_reports_test_extension_mismatch(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    test_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_dir / "Extra.Test.ts").write_text(
        "export const value = true;\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "TestFileNameInvalid"
        and record["findingKind"] == "TestMirrorExtra"
        and record["pathFromRoot"][-1] == "Extra.Test.ts"
        for record in records
    )


def test_product_root_projection_reports_empty_config_carrier(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Demo" / "Config").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "ConfigContainsNoFile"
        and record["findingKind"] == "CarrierValidationFailure"
        for record in records
    )


def test_product_root_projection_reports_invalid_data_test_name(
    tmp_path: Path,
) -> None:
    data_test_dir = tmp_path / "Package" / "Demo" / "Data" / "test"
    data_test_dir.mkdir(parents=True)
    (data_test_dir / "sample.json").write_text("{}\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "DataTestCarrierInvalid"
        and record["findingKind"] == "CarrierValidationFailure"
        for record in records
    )


def test_product_root_projection_reports_empty_data_test_carrier(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Demo" / "Data" / "Test").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "DataCarrierDirectoryEmpty"
        and record["findingKind"] == "CarrierValidationFailure"
        for record in records
    )


def test_product_root_projection_reports_bin_directory_carrier(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Demo" / "Bin" / "nested").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "BinCarrierInvalid"
        and record["findingKind"] == "CarrierValidationFailure"
        for record in records
    )


def test_product_root_projection_reports_empty_project_free_remainder(
    tmp_path: Path,
) -> None:
    (tmp_path / "scratch").mkdir()

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "FreeRemainderDirectoryEmpty"
        and record["findingKind"] == "CarrierValidationFailure"
        and record["pathFromRoot"] == ["scratch"]
        for record in records
    )


def test_product_root_projection_reports_empty_module_free_remainder(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Demo" / "scratch").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "FreeRemainderDirectoryEmpty"
        and record["findingKind"] == "CarrierValidationFailure"
        and record["pathFromRoot"] == ["Package", "Demo", "scratch"]
        for record in records
    )


def test_product_root_projection_reports_project_embedded_workspace_file_carrier(
    tmp_path: Path,
) -> None:
    (tmp_path / "Docs").write_text("not a workspace\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "EmbeddedWorkspaceCarrierInvalid"
        and record["pathFromRoot"] == ["Docs"]
        for record in records
    )


def test_product_root_projection_reports_empty_project_embedded_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / "Docs").mkdir()

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "EmbeddedWorkspaceEmpty"
        and record["pathFromRoot"] == ["Docs"]
        for record in records
    )


def test_product_root_projection_accepts_project_embedded_workspace_project(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "Docs" / "Documentation"
    project_dir.mkdir(parents=True)
    (project_dir / "README.md").write_text("docs\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)

    assert not any(
        record["recordKind"] == "Finding"
        and record["ruleId"].startswith("EmbeddedWorkspace")
        for record in records
    )
    assert any(
        record["recordKind"] == "StructureEntity"
        and record["entityKind"] == "Project"
        and record["pathFromRoot"] == ["Docs", "Documentation"]
        for record in records
    )


def test_product_root_projection_reports_empty_embedded_workspace_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "Docs" / "Documentation").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "ProjectDirectoryEmpty"
        and record["pathFromRoot"] == ["Docs", "Documentation"]
        for record in records
    )


def test_product_root_projection_scans_embedded_project_module_space(
    tmp_path: Path,
) -> None:
    source_dir = (
        tmp_path
        / "Docs"
        / "Documentation"
        / "Package"
        / "DocModel"
        / "Src"
        / "Application"
        / "Dto"
    )
    test_dir = (
        tmp_path
        / "Docs"
        / "Documentation"
        / "Package"
        / "DocModel"
        / "Test"
        / "Application"
        / "Dto"
    )
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "DocPage.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "DocPage.Test.py").write_text(
        "def test_doc_page():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "StructureEntity"
        and record["entityKind"] == "Module"
        and record["pathFromRoot"]
        == ["Docs", "Documentation", "Package", "DocModel"]
        for record in records
    )
    assert not any(record["recordKind"] == "Finding" for record in records)


def test_product_root_projection_reports_empty_module_embedded_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Demo" / "Tool").mkdir(parents=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "EmbeddedWorkspaceEmpty"
        and record["pathFromRoot"] == ["Package", "Demo", "Tool"]
        for record in records
    )


def test_product_root_projection_reports_module_embedded_workspace_file_child(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "Package" / "Demo" / "Tool"
    tool_dir.mkdir(parents=True)
    (tool_dir / "readme.md").write_text("tool notes\n", encoding="utf-8")

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "EmbeddedWorkspaceProjectInvalid"
        and record["pathFromRoot"] == ["Package", "Demo", "Tool", "readme.md"]
        for record in records
    )


def test_product_root_projection_reports_module_embedded_workspace_symlink_child(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "Package" / "Demo" / "Tool"
    project_dir = tmp_path / "external-tool-project"
    tool_dir.mkdir(parents=True)
    project_dir.mkdir()
    (tool_dir / "LinkedTool").symlink_to(project_dir, target_is_directory=True)

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "EmbeddedWorkspaceProjectInvalid"
        and record["pathFromRoot"] == ["Package", "Demo", "Tool", "LinkedTool"]
        for record in records
    )


def test_product_root_projection_skips_vcs_snapshot_free_remainder(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "external-snapshot"
    (snapshot / "external" / "EmptyDependency").mkdir(parents=True)
    (snapshot / ".gitmodules").write_text(
        "[submodule \"external/EmptyDependency\"]\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    assert not any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "FreeRemainderDirectoryEmpty"
        for record in records
    )


def test_product_root_projection_recognizes_module_vendor_supply_module(
    tmp_path: Path,
) -> None:
    source_dir = (
        tmp_path
        / "Package"
        / "Consumer"
        / "Vendor"
        / "SupplyProject"
        / "Package"
        / "JsonSupply"
        / "Src"
        / "Application"
        / "Dto"
    )
    test_dir = (
        tmp_path
        / "Package"
        / "Consumer"
        / "Vendor"
        / "SupplyProject"
        / "Package"
        / "JsonSupply"
        / "Test"
        / "Application"
        / "Dto"
    )
    source_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (source_dir / "JsonPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_dir / "JsonPayload.Test.py").write_text(
        "def test_json_payload():\n    assert True\n",
        encoding="utf-8",
    )

    records = scan_product_project_root(tmp_path)

    supply_project = next(
        record
        for record in records
        if record["pathFromRoot"]
        == ["Package", "Consumer", "Vendor", "SupplyProject"]
    )
    assert supply_project["entityKind"] == "Project"
    assert supply_project["vendorGoverned"] is True

    supply_module = next(
        record
        for record in records
        if record["entityKind"] == "Module"
        and record["pathFromRoot"]
        == [
            "Package",
            "Consumer",
            "Vendor",
            "SupplyProject",
            "Package",
            "JsonSupply",
        ]
    )
    assert supply_module["vendorGoverned"] is True
    assert supply_module["moduleRole"] == "Package"


def test_product_root_projection_reports_empty_vendor_supply_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "Package" / "Consumer" / "Vendor" / "SupplyProject").mkdir(
        parents=True
    )

    records = scan_product_project_root(tmp_path)

    assert any(
        record["recordKind"] == "Finding"
        and record["ruleId"] == "ProjectDirectoryEmpty"
        and record["pathFromRoot"]
        == ["Package", "Consumer", "Vendor", "SupplyProject"]
        for record in records
    )
