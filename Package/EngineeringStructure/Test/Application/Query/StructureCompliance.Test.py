from __future__ import annotations

from pathlib import Path

from Package.EngineeringStructure.Src.Application.Query.StructureCompliance import (
    check_product_project_compliance,
)


def test_structure_compliance_passes_current_repository() -> None:
    result = check_product_project_compliance(Path.cwd())

    assert result["passed"] is True
    assert result["summary"]["total_finding_count"] == 0
    assert result["summary"]["dependency_finding_count"] == 0
    assert result["summary"]["dependency_edge_count"] > 0
    assert all(edge["allowed"] for edge in result["dependencyEdges"])


def test_structure_compliance_reports_application_query_to_entry_dependency(
    tmp_path: Path,
) -> None:
    query_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Query"
    entry_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Entry"
    test_query_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Query"
    test_entry_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Entry"
    query_dir.mkdir(parents=True)
    entry_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    test_entry_dir.mkdir(parents=True)
    (entry_dir / "Contract.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "BadQuery.py").write_text(
        "from Main.Demo.Src.Application.Entry.Contract import VALUE\n",
        encoding="utf-8",
    )
    (test_entry_dir / "Contract.Test.py").write_text(
        "def test_contract():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "BadQuery.Test.py").write_text(
        "def test_query():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert any(
        finding["ruleId"] == "ModuleInternalDependencyBoundary"
        for finding in result["findings"]
    )
    assert any(not edge["allowed"] for edge in result["dependencyEdges"])


def test_structure_compliance_resolves_allowed_relative_import(tmp_path: Path) -> None:
    dto_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Dto"
    query_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Query"
    test_dto_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Dto"
    test_query_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Query"
    dto_dir.mkdir(parents=True)
    query_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "GoodQuery.py").write_text(
        "from ..Dto.Payload import VALUE\n",
        encoding="utf-8",
    )
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "GoodQuery.Test.py").write_text(
        "def test_query():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["dependency_impact_node_count"] == 2
    assert result["summary"]["max_dependency_direct_upstream_count"] == 1
    assert any(
        edge["importStyle"] == "relative"
        and edge["originalImportedModule"] == "..Dto.Payload"
        and edge["importedModule"] == "Main.Demo.Src.Application.Dto.Payload"
        and edge["targetPathFromRoot"]
        == ["Main", "Demo", "Src", "Application", "Dto", "Payload.py"]
        and edge["allowed"] is True
        for edge in result["dependencyEdges"]
    )
    impact_by_path = {
        tuple(record["sourcePathFromRoot"]): record
        for record in result["dependencyImpact"]
    }
    assert impact_by_path[
        ("Main", "Demo", "Src", "Application", "Dto", "Payload.py")
    ]["directUpstreamSourcePaths"] == [
        ["Main", "Demo", "Src", "Application", "Query", "GoodQuery.py"]
    ]
    assert impact_by_path[
        ("Main", "Demo", "Src", "Application", "Query", "GoodQuery.py")
    ]["directUpstreamSourcePaths"] == []
    assert result["dependencyImpactHotspots"] == [
        impact_by_path[
            ("Main", "Demo", "Src", "Application", "Dto", "Payload.py")
        ]
    ]


def test_structure_compliance_reports_relative_query_to_entry_dependency(
    tmp_path: Path,
) -> None:
    entry_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Entry"
    query_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Query"
    test_entry_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Entry"
    test_query_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Query"
    entry_dir.mkdir(parents=True)
    query_dir.mkdir(parents=True)
    test_entry_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    (entry_dir / "Contract.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "BadQuery.py").write_text(
        "from ..Entry.Contract import VALUE\n",
        encoding="utf-8",
    )
    (test_entry_dir / "Contract.Test.py").write_text(
        "def test_contract():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "BadQuery.Test.py").write_text(
        "def test_query():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert any(
        edge["importStyle"] == "relative"
        and edge["importedModule"] == "Main.Demo.Src.Application.Entry.Contract"
        and edge["allowed"] is False
        for edge in result["dependencyEdges"]
    )


def test_structure_compliance_resolves_embedded_project_relative_import(
    tmp_path: Path,
) -> None:
    dto_dir = (
        tmp_path / "Docs" / "Documentation" / "Package" / "Demo" / "Src" / "Application" / "Dto"
    )
    query_dir = (
        tmp_path / "Docs" / "Documentation" / "Package" / "Demo" / "Src" / "Application" / "Query"
    )
    test_dto_dir = (
        tmp_path / "Docs" / "Documentation" / "Package" / "Demo" / "Test" / "Application" / "Dto"
    )
    test_query_dir = (
        tmp_path / "Docs" / "Documentation" / "Package" / "Demo" / "Test" / "Application" / "Query"
    )
    dto_dir.mkdir(parents=True)
    query_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    test_query_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (query_dir / "GoodQuery.py").write_text(
        "from ..Dto.Payload import VALUE\n",
        encoding="utf-8",
    )
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (test_query_dir / "GoodQuery.Test.py").write_text(
        "def test_query():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert any(
        edge["importStyle"] == "relative"
        and edge["importedModule"]
        == "Docs.Documentation.Package.Demo.Src.Application.Dto.Payload"
        and edge["targetModuleRoot"]
        == ["Docs", "Documentation", "Package", "Demo"]
        and edge["allowed"] is True
        for edge in result["dependencyEdges"]
    )


def test_structure_compliance_allows_stdlib_import(tmp_path: Path) -> None:
    dto_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    test_dto_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    dto_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text(
        "import json\nVALUE = json.dumps({'ok': True})\n",
        encoding="utf-8",
    )
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["dependency_finding_count"] == 0


def test_structure_compliance_reports_external_import_without_supply_boundary(
    tmp_path: Path,
) -> None:
    dto_dir = tmp_path / "Package" / "Demo" / "Src" / "Application" / "Dto"
    test_dto_dir = tmp_path / "Package" / "Demo" / "Test" / "Application" / "Dto"
    dto_dir.mkdir(parents=True)
    test_dto_dir.mkdir(parents=True)
    (dto_dir / "Payload.py").write_text(
        "import requests\nVALUE = requests.__name__\n",
        encoding="utf-8",
    )
    (test_dto_dir / "Payload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert any(
        finding["ruleId"] == "ExternalImportWithoutSupplyBoundary"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_entry_to_usecase_dependency(
    tmp_path: Path,
) -> None:
    entry_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Entry"
    usecase_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Usecase"
    boot_dir = tmp_path / "Main" / "Demo" / "Src" / "Boot"
    test_entry_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Entry"
    test_usecase_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Usecase"
    test_boot_dir = tmp_path / "Main" / "Demo" / "Test" / "Boot"
    for directory in (
        entry_dir,
        usecase_dir,
        boot_dir,
        test_entry_dir,
        test_usecase_dir,
        test_boot_dir,
    ):
        directory.mkdir(parents=True)
    (usecase_dir / "RunDemo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (entry_dir / "BadEntry.py").write_text(
        "from ..Usecase.RunDemo import VALUE\n",
        encoding="utf-8",
    )
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_usecase_dir / "RunDemo.Test.py").write_text(
        "def test_run_demo():\n    assert True\n",
        encoding="utf-8",
    )
    (test_entry_dir / "BadEntry.Test.py").write_text(
        "def test_entry():\n    assert True\n",
        encoding="utf-8",
    )
    (test_boot_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert any(
        finding["ruleId"] == "ModuleInternalDependencyBoundary"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_adapter_in_to_import_dependency(
    tmp_path: Path,
) -> None:
    adapter_dir = tmp_path / "Main" / "Demo" / "Src" / "Adapter" / "In" / "Cli"
    import_dir = tmp_path / "Main" / "Demo" / "Src" / "Import"
    usecase_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Usecase"
    boot_dir = tmp_path / "Main" / "Demo" / "Src" / "Boot"
    test_adapter_dir = tmp_path / "Main" / "Demo" / "Test" / "Adapter" / "In" / "Cli"
    test_import_dir = tmp_path / "Main" / "Demo" / "Test" / "Import"
    test_usecase_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Usecase"
    test_boot_dir = tmp_path / "Main" / "Demo" / "Test" / "Boot"
    for directory in (
        adapter_dir,
        import_dir,
        usecase_dir,
        boot_dir,
        test_adapter_dir,
        test_import_dir,
        test_usecase_dir,
        test_boot_dir,
    ):
        directory.mkdir(parents=True)
    (import_dir / "1-Target.py").write_text("VALUE = 1\n", encoding="utf-8")
    (adapter_dir / "BadCli.py").write_text(
        "from ....Import.Target import VALUE\n",
        encoding="utf-8",
    )
    (usecase_dir / "RunDemo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_import_dir / "1-Target.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (test_adapter_dir / "BadCli.Test.py").write_text(
        "def test_cli():\n    assert True\n",
        encoding="utf-8",
    )
    (test_usecase_dir / "RunDemo.Test.py").write_text(
        "def test_run_demo():\n    assert True\n",
        encoding="utf-8",
    )
    (test_boot_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert any(
        finding["ruleId"] == "ModuleInternalDependencyBoundary"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_boot_to_domain_dependency(
    tmp_path: Path,
) -> None:
    boot_dir = tmp_path / "Main" / "Demo" / "Src" / "Boot"
    domain_dir = tmp_path / "Main" / "Demo" / "Src" / "Domain"
    usecase_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Usecase"
    test_boot_dir = tmp_path / "Main" / "Demo" / "Test" / "Boot"
    test_domain_dir = tmp_path / "Main" / "Demo" / "Test" / "Domain"
    test_usecase_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Usecase"
    for directory in (
        boot_dir,
        domain_dir,
        usecase_dir,
        test_boot_dir,
        test_domain_dir,
        test_usecase_dir,
    ):
        directory.mkdir(parents=True)
    (domain_dir / "Entity.py").write_text("VALUE = 1\n", encoding="utf-8")
    (usecase_dir / "RunDemo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (boot_dir / "CreateApp.py").write_text(
        "from ..Domain.Entity import VALUE\n",
        encoding="utf-8",
    )
    (test_domain_dir / "Entity.Test.py").write_text(
        "def test_entity():\n    assert True\n",
        encoding="utf-8",
    )
    (test_usecase_dir / "RunDemo.Test.py").write_text(
        "def test_run_demo():\n    assert True\n",
        encoding="utf-8",
    )
    (test_boot_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert any(
        finding["ruleId"] == "ModuleInternalDependencyBoundary"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_impure_import_file(tmp_path: Path) -> None:
    import_dir = tmp_path / "Package" / "Demo" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "Demo" / "Test" / "Import"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    (import_dir / "1-Target.py").write_text(
        "def build_target():\n    return object()\n",
        encoding="utf-8",
    )
    (test_import_dir / "1-Target.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert any(
        finding["ruleId"] == "ImportFileNotPureBinding"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_boot_platform_read(tmp_path: Path) -> None:
    boot_dir = tmp_path / "Main" / "Demo" / "Src" / "Boot"
    usecase_dir = tmp_path / "Main" / "Demo" / "Src" / "Application" / "Usecase"
    test_boot_dir = tmp_path / "Main" / "Demo" / "Test" / "Boot"
    test_usecase_dir = tmp_path / "Main" / "Demo" / "Test" / "Application" / "Usecase"
    boot_dir.mkdir(parents=True)
    usecase_dir.mkdir(parents=True)
    test_boot_dir.mkdir(parents=True)
    test_usecase_dir.mkdir(parents=True)
    (usecase_dir / "RunDemo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (boot_dir / "CreateApp.py").write_text(
        "import os\nVALUE = os.environ.get('TOKEN')\n",
        encoding="utf-8",
    )
    (test_usecase_dir / "RunDemo.Test.py").write_text(
        "def test_run_demo():\n    assert True\n",
        encoding="utf-8",
    )
    (test_boot_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert any(finding["ruleId"] == "BootPlatformRead" for finding in result["findings"])


def test_structure_compliance_reports_invalid_import_stem(tmp_path: Path) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    (import_dir / "bad.py").write_text("", encoding="utf-8")
    (test_import_dir / "bad.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(finding["ruleId"] == "ImportStemInvalid" for finding in result["findings"])


def test_structure_compliance_reports_import_stem_with_leading_zero(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    target_src_dir = tmp_path / "Package" / "TargetModule" / "Src" / "Application" / "Dto"
    target_test_dir = (
        tmp_path / "Package" / "TargetModule" / "Test" / "Application" / "Dto"
    )
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (import_dir / "02-Package-TargetModule.py").write_text("", encoding="utf-8")
    (test_import_dir / "02-Package-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(finding["ruleId"] == "ImportStemInvalid" for finding in result["findings"])


def test_structure_compliance_accepts_import_file_targeting_existing_module(
    tmp_path: Path,
) -> None:
    boot_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Boot"
    usecase_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Application" / "Usecase"
    adapter_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Adapter" / "Out" / "Module"
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_boot_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Boot"
    test_usecase_dir = (
        tmp_path / "Package" / "SourceModule" / "Test" / "Application" / "Usecase"
    )
    test_adapter_dir = (
        tmp_path / "Package" / "SourceModule" / "Test" / "Adapter" / "Out" / "Module"
    )
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    target_src_dir = tmp_path / "Package" / "TargetModule" / "Src" / "Application" / "Dto"
    target_test_dir = (
        tmp_path / "Package" / "TargetModule" / "Test" / "Application" / "Dto"
    )
    boot_dir.mkdir(parents=True)
    usecase_dir.mkdir(parents=True)
    adapter_dir.mkdir(parents=True)
    import_dir.mkdir(parents=True)
    test_boot_dir.mkdir(parents=True)
    test_usecase_dir.mkdir(parents=True)
    test_adapter_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (usecase_dir / "RunSource.py").write_text("VALUE = 1\n", encoding="utf-8")
    (adapter_dir / "TargetBinding.py").write_text("VALUE = 1\n", encoding="utf-8")
    (import_dir / "1-TargetModule.py").write_text("", encoding="utf-8")
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
    (test_import_dir / "1-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["import_finding_count"] == 0
    assert result["summary"]["same_project_import_dependency_edge_count"] == 1
    assert result["summary"]["vendor_import_dependency_edge_count"] == 0
    assert result["summary"]["cross_project_import_dependency_edge_count"] == 0
    assert result["importDependencyEdges"][0]["sameProjectScope"] is True


def test_structure_compliance_reports_noncanonical_import_stem(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    target_src_dir = tmp_path / "Package" / "TargetModule" / "Src" / "Application" / "Dto"
    target_test_dir = (
        tmp_path / "Package" / "TargetModule" / "Test" / "Application" / "Dto"
    )
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (import_dir / "2-Package-TargetModule.py").write_text("", encoding="utf-8")
    (test_import_dir / "2-Package-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(
        finding["ruleId"] == "ImportStemNotCanonical"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_import_target_without_public_surface(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    target_src_dir = tmp_path / "Package" / "TargetModule" / "Src" / "Domain" / "Model"
    target_test_dir = tmp_path / "Package" / "TargetModule" / "Test" / "Domain" / "Model"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (import_dir / "1-TargetModule.py").write_text("", encoding="utf-8")
    (test_import_dir / "1-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "Entity.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "Entity.Test.py").write_text(
        "def test_entity():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(
        finding["ruleId"] == "ImportTargetNotDependable"
        for finding in result["findings"]
    )


def test_structure_compliance_accepts_main_import_to_package_module(
    tmp_path: Path,
) -> None:
    boot_dir = tmp_path / "Main" / "SourceApp" / "Src" / "Boot"
    usecase_dir = tmp_path / "Main" / "SourceApp" / "Src" / "Application" / "Usecase"
    adapter_dir = tmp_path / "Main" / "SourceApp" / "Src" / "Adapter" / "Out" / "Module"
    import_dir = tmp_path / "Main" / "SourceApp" / "Src" / "Import"
    test_boot_dir = tmp_path / "Main" / "SourceApp" / "Test" / "Boot"
    test_usecase_dir = (
        tmp_path / "Main" / "SourceApp" / "Test" / "Application" / "Usecase"
    )
    test_adapter_dir = (
        tmp_path / "Main" / "SourceApp" / "Test" / "Adapter" / "Out" / "Module"
    )
    test_import_dir = tmp_path / "Main" / "SourceApp" / "Test" / "Import"
    target_src_dir = tmp_path / "Package" / "TargetModule" / "Src" / "Application" / "Dto"
    target_test_dir = (
        tmp_path / "Package" / "TargetModule" / "Test" / "Application" / "Dto"
    )
    boot_dir.mkdir(parents=True)
    usecase_dir.mkdir(parents=True)
    adapter_dir.mkdir(parents=True)
    import_dir.mkdir(parents=True)
    test_boot_dir.mkdir(parents=True)
    test_usecase_dir.mkdir(parents=True)
    test_adapter_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (usecase_dir / "RunSource.py").write_text("VALUE = 1\n", encoding="utf-8")
    (adapter_dir / "TargetBinding.py").write_text("VALUE = 1\n", encoding="utf-8")
    (import_dir / "2-Package-TargetModule.py").write_text("", encoding="utf-8")
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
    (test_import_dir / "2-Package-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["import_finding_count"] == 0


def test_structure_compliance_accepts_embedded_project_package_import(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "Docs" / "Documentation" / "Package" / "SourceModule"
    target_root = tmp_path / "Docs" / "Documentation" / "Package" / "TargetModule"
    boot_dir = source_root / "Src" / "Boot"
    usecase_dir = source_root / "Src" / "Application" / "Usecase"
    adapter_dir = source_root / "Src" / "Adapter" / "Out" / "Module"
    import_dir = source_root / "Src" / "Import"
    test_boot_dir = source_root / "Test" / "Boot"
    test_usecase_dir = source_root / "Test" / "Application" / "Usecase"
    test_adapter_dir = source_root / "Test" / "Adapter" / "Out" / "Module"
    test_import_dir = source_root / "Test" / "Import"
    target_src_dir = target_root / "Src" / "Application" / "Dto"
    target_test_dir = target_root / "Test" / "Application" / "Dto"
    for directory in (
        boot_dir,
        usecase_dir,
        adapter_dir,
        import_dir,
        test_boot_dir,
        test_usecase_dir,
        test_adapter_dir,
        test_import_dir,
        target_src_dir,
        target_test_dir,
    ):
        directory.mkdir(parents=True)
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (usecase_dir / "RunSource.py").write_text("VALUE = 1\n", encoding="utf-8")
    (adapter_dir / "TargetBinding.py").write_text("VALUE = 1\n", encoding="utf-8")
    (import_dir / "1-TargetModule.py").write_text("", encoding="utf-8")
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
    (test_import_dir / "1-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["import_dependency_edge_count"] == 1
    assert result["summary"]["same_project_import_dependency_edge_count"] == 1
    assert result["summary"]["vendor_import_dependency_edge_count"] == 0
    assert result["summary"]["cross_project_import_dependency_edge_count"] == 0
    assert result["importDependencyEdges"][0]["sourceModuleRoot"] == [
        "Docs",
        "Documentation",
        "Package",
        "SourceModule",
    ]
    assert result["importDependencyEdges"][0]["targetModuleRoot"] == [
        "Docs",
        "Documentation",
        "Package",
        "TargetModule",
    ]
    assert result["importDependencyEdges"][0]["sameProjectScope"] is True


def test_structure_compliance_accepts_package_import_to_own_vendor_supply_module(
    tmp_path: Path,
) -> None:
    consumer_boot = tmp_path / "Package" / "Consumer" / "Src" / "Boot"
    consumer_usecase = tmp_path / "Package" / "Consumer" / "Src" / "Application" / "Usecase"
    consumer_adapter = tmp_path / "Package" / "Consumer" / "Src" / "Adapter" / "Out" / "Module"
    consumer_import = tmp_path / "Package" / "Consumer" / "Src" / "Import"
    consumer_test_boot = tmp_path / "Package" / "Consumer" / "Test" / "Boot"
    consumer_test_usecase = (
        tmp_path / "Package" / "Consumer" / "Test" / "Application" / "Usecase"
    )
    consumer_test_adapter = (
        tmp_path / "Package" / "Consumer" / "Test" / "Adapter" / "Out" / "Module"
    )
    consumer_test_import = tmp_path / "Package" / "Consumer" / "Test" / "Import"
    supply_src = (
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
    supply_test = (
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
    for directory in (
        consumer_boot,
        consumer_usecase,
        consumer_adapter,
        consumer_import,
        consumer_test_boot,
        consumer_test_usecase,
        consumer_test_adapter,
        consumer_test_import,
        supply_src,
        supply_test,
    ):
        directory.mkdir(parents=True)
    (consumer_boot / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (consumer_usecase / "RunConsumer.py").write_text("VALUE = 1\n", encoding="utf-8")
    (consumer_adapter / "JsonBinding.py").write_text("VALUE = 1\n", encoding="utf-8")
    (consumer_import / "0-Vendor-SupplyProject-Package-JsonSupply.py").write_text(
        "",
        encoding="utf-8",
    )
    (consumer_test_boot / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )
    (consumer_test_usecase / "RunConsumer.Test.py").write_text(
        "def test_run_consumer():\n    assert True\n",
        encoding="utf-8",
    )
    (consumer_test_adapter / "JsonBinding.Test.py").write_text(
        "def test_json_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (consumer_test_import / "0-Vendor-SupplyProject-Package-JsonSupply.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (supply_src / "JsonPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (supply_test / "JsonPayload.Test.py").write_text(
        "def test_json_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["import_dependency_edge_count"] == 1
    assert result["summary"]["same_project_import_dependency_edge_count"] == 0
    assert result["summary"]["vendor_import_dependency_edge_count"] == 1
    assert result["summary"]["cross_project_import_dependency_edge_count"] == 0
    assert result["importDependencyEdges"][0]["targetModuleRoot"] == [
        "Package",
        "Consumer",
        "Vendor",
        "SupplyProject",
        "Package",
        "JsonSupply",
    ]
    assert result["importDependencyEdges"][0]["sameProjectScope"] is False


def test_structure_compliance_reports_main_import_to_main_module(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "Main" / "SourceApp" / "Src" / "Import"
    test_import_dir = tmp_path / "Main" / "SourceApp" / "Test" / "Import"
    target_src_dir = tmp_path / "Main" / "TargetApp" / "Src" / "Application" / "Dto"
    target_test_dir = tmp_path / "Main" / "TargetApp" / "Test" / "Application" / "Dto"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (import_dir / "1-TargetApp.py").write_text("", encoding="utf-8")
    (test_import_dir / "1-TargetApp.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(
        finding["ruleId"] == "ImportRoleDependencyInvalid"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_package_import_to_main_module(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    target_src_dir = tmp_path / "Main" / "TargetApp" / "Src" / "Application" / "Dto"
    target_test_dir = tmp_path / "Main" / "TargetApp" / "Test" / "Application" / "Dto"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (import_dir / "2-Main-TargetApp.py").write_text("", encoding="utf-8")
    (test_import_dir / "2-Main-TargetApp.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(
        finding["ruleId"] == "ImportRoleDependencyInvalid"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_embedded_main_import_to_root_package(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "Docs" / "Documentation" / "Main" / "SourceApp"
    import_dir = source_root / "Src" / "Import"
    adapter_dir = source_root / "Src" / "Adapter" / "Out" / "Module"
    boot_dir = source_root / "Src" / "Boot"
    usecase_dir = source_root / "Src" / "Application" / "Usecase"
    test_import_dir = source_root / "Test" / "Import"
    test_adapter_dir = source_root / "Test" / "Adapter" / "Out" / "Module"
    test_boot_dir = source_root / "Test" / "Boot"
    test_usecase_dir = source_root / "Test" / "Application" / "Usecase"
    target_src_dir = tmp_path / "Package" / "RootTarget" / "Src" / "Application" / "Dto"
    target_test_dir = tmp_path / "Package" / "RootTarget" / "Test" / "Application" / "Dto"
    for directory in (
        import_dir,
        adapter_dir,
        boot_dir,
        usecase_dir,
        test_import_dir,
        test_adapter_dir,
        test_boot_dir,
        test_usecase_dir,
        target_src_dir,
        target_test_dir,
    ):
        directory.mkdir(parents=True)
    (import_dir / "4-Package-RootTarget.py").write_text("", encoding="utf-8")
    (adapter_dir / "TargetBinding.py").write_text("VALUE = 1\n", encoding="utf-8")
    (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
    (usecase_dir / "RunSource.py").write_text("VALUE = 1\n", encoding="utf-8")
    (test_import_dir / "4-Package-RootTarget.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (test_adapter_dir / "TargetBinding.Test.py").write_text(
        "def test_target_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (test_boot_dir / "CreateApp.Test.py").write_text(
        "def test_create_app():\n    assert True\n",
        encoding="utf-8",
    )
    (test_usecase_dir / "RunSource.Test.py").write_text(
        "def test_run_source():\n    assert True\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(
        finding["ruleId"] == "ImportRoleDependencyInvalid"
        for finding in result["findings"]
    )


def test_structure_compliance_reports_missing_import_target(tmp_path: Path) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    (import_dir / "1-MissingModule.py").write_text("", encoding="utf-8")
    (test_import_dir / "1-MissingModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(finding["ruleId"] == "ImportTargetMissing" for finding in result["findings"])


def test_structure_compliance_reports_import_self_dependency(tmp_path: Path) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    (import_dir / "2-Package-SourceModule.py").write_text("", encoding="utf-8")
    (test_import_dir / "2-Package-SourceModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(finding["ruleId"] == "ImportSelfDependency" for finding in result["findings"])


def test_structure_compliance_reports_invalid_import_target_path(
    tmp_path: Path,
) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    (import_dir / "3-Package-TargetModule.py").write_text("", encoding="utf-8")
    (test_import_dir / "3-Package-TargetModule.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 1
    assert any(
        finding["ruleId"] == "ImportTargetPathInvalid" for finding in result["findings"]
    )


def test_structure_compliance_reports_duplicate_import_stem(tmp_path: Path) -> None:
    import_dir = tmp_path / "Package" / "SourceModule" / "Src" / "Import"
    test_import_dir = tmp_path / "Package" / "SourceModule" / "Test" / "Import"
    target_src_dir = tmp_path / "Package" / "TargetModule" / "Src" / "Application" / "Dto"
    target_test_dir = (
        tmp_path / "Package" / "TargetModule" / "Test" / "Application" / "Dto"
    )
    import_dir.mkdir(parents=True)
    test_import_dir.mkdir(parents=True)
    target_src_dir.mkdir(parents=True)
    target_test_dir.mkdir(parents=True)
    (import_dir / "1-TargetModule.py").write_text("", encoding="utf-8")
    (import_dir / "1-TargetModule.pyi").write_text("", encoding="utf-8")
    (test_import_dir / "1-TargetModule.Test.py").write_text(
        "def test_import_binding_py():\n    assert True\n",
        encoding="utf-8",
    )
    (test_import_dir / "1-TargetModule.Test.pyi").write_text(
        "def test_import_binding_pyi(): ...\n",
        encoding="utf-8",
    )
    (target_src_dir / "TargetPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target_test_dir / "TargetPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_finding_count"] == 2
    assert sum(
        1 for finding in result["findings"] if finding["ruleId"] == "DuplicateImportStem"
    ) == 2


def test_structure_compliance_reports_import_impact_transitive_upstream(
    tmp_path: Path,
) -> None:
    def write_importing_module(module_name: str, target_name: str) -> None:
        module_root = tmp_path / "Package" / module_name
        boot_dir = module_root / "Src" / "Boot"
        usecase_dir = module_root / "Src" / "Application" / "Usecase"
        adapter_dir = module_root / "Src" / "Adapter" / "Out" / "Module"
        import_dir = module_root / "Src" / "Import"
        test_boot_dir = module_root / "Test" / "Boot"
        test_usecase_dir = module_root / "Test" / "Application" / "Usecase"
        test_adapter_dir = module_root / "Test" / "Adapter" / "Out" / "Module"
        test_import_dir = module_root / "Test" / "Import"
        for directory in (
            boot_dir,
            usecase_dir,
            adapter_dir,
            import_dir,
            test_boot_dir,
            test_usecase_dir,
            test_adapter_dir,
            test_import_dir,
        ):
            directory.mkdir(parents=True)
        (boot_dir / "CreateApp.py").write_text("VALUE = 1\n", encoding="utf-8")
        (usecase_dir / f"Run{module_name}.py").write_text(
            "VALUE = 1\n",
            encoding="utf-8",
        )
        (adapter_dir / f"{target_name}Binding.py").write_text(
            "VALUE = 1\n",
            encoding="utf-8",
        )
        (import_dir / f"1-{target_name}.py").write_text("", encoding="utf-8")
        (test_boot_dir / "CreateApp.Test.py").write_text(
            "def test_create_app():\n    assert True\n",
            encoding="utf-8",
        )
        (test_usecase_dir / f"Run{module_name}.Test.py").write_text(
            "def test_run_module():\n    assert True\n",
            encoding="utf-8",
        )
        (test_adapter_dir / f"{target_name}Binding.Test.py").write_text(
            "def test_binding():\n    assert True\n",
            encoding="utf-8",
        )
        (test_import_dir / f"1-{target_name}.Test.py").write_text(
            "def test_import_binding():\n    assert True\n",
            encoding="utf-8",
        )

    def write_dto_module(module_name: str) -> None:
        source_dir = tmp_path / "Package" / module_name / "Src" / "Application" / "Dto"
        test_dir = tmp_path / "Package" / module_name / "Test" / "Application" / "Dto"
        source_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)
        (source_dir / f"{module_name}Payload.py").write_text(
            "VALUE = 1\n",
            encoding="utf-8",
        )
        (test_dir / f"{module_name}Payload.Test.py").write_text(
            "def test_payload():\n    assert True\n",
            encoding="utf-8",
        )

    write_importing_module("Alpha", "Beta")
    write_importing_module("Beta", "Core")
    write_dto_module("Core")

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is True
    assert result["summary"]["import_dependency_edge_count"] == 2
    assert result["summary"]["import_impact_node_count"] == 3
    assert result["summary"]["max_import_transitive_upstream_count"] == 2
    impact_by_module = {
        tuple(record["moduleRoot"]): record for record in result["importImpact"]
    }
    assert impact_by_module[("Package", "Beta")]["directUpstreamModuleRoots"] == [
        ["Package", "Alpha"]
    ]
    assert impact_by_module[("Package", "Beta")]["transitiveUpstreamModuleRoots"] == [
        ["Package", "Alpha"]
    ]
    assert impact_by_module[("Package", "Core")]["directUpstreamModuleRoots"] == [
        ["Package", "Beta"]
    ]
    assert impact_by_module[("Package", "Core")]["transitiveUpstreamModuleRoots"] == [
        ["Package", "Alpha"],
        ["Package", "Beta"],
    ]
    assert result["importImpactHotspots"][0] == impact_by_module[("Package", "Core")]
    assert result["importImpactHotspots"][1] == impact_by_module[("Package", "Beta")]


def test_structure_compliance_reports_package_import_cycle(tmp_path: Path) -> None:
    alpha_import_dir = tmp_path / "Package" / "Alpha" / "Src" / "Import"
    alpha_import_test_dir = tmp_path / "Package" / "Alpha" / "Test" / "Import"
    alpha_dto_dir = tmp_path / "Package" / "Alpha" / "Src" / "Application" / "Dto"
    alpha_dto_test_dir = tmp_path / "Package" / "Alpha" / "Test" / "Application" / "Dto"
    beta_import_dir = tmp_path / "Package" / "Beta" / "Src" / "Import"
    beta_import_test_dir = tmp_path / "Package" / "Beta" / "Test" / "Import"
    beta_dto_dir = tmp_path / "Package" / "Beta" / "Src" / "Application" / "Dto"
    beta_dto_test_dir = tmp_path / "Package" / "Beta" / "Test" / "Application" / "Dto"
    for directory in (
        alpha_import_dir,
        alpha_import_test_dir,
        alpha_dto_dir,
        alpha_dto_test_dir,
        beta_import_dir,
        beta_import_test_dir,
        beta_dto_dir,
        beta_dto_test_dir,
    ):
        directory.mkdir(parents=True)
    (alpha_import_dir / "1-Beta.py").write_text("", encoding="utf-8")
    (alpha_import_test_dir / "1-Beta.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (alpha_dto_dir / "AlphaPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (alpha_dto_test_dir / "AlphaPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )
    (beta_import_dir / "1-Alpha.py").write_text("", encoding="utf-8")
    (beta_import_test_dir / "1-Alpha.Test.py").write_text(
        "def test_import_binding():\n    assert True\n",
        encoding="utf-8",
    )
    (beta_dto_dir / "BetaPayload.py").write_text("VALUE = 1\n", encoding="utf-8")
    (beta_dto_test_dir / "BetaPayload.Test.py").write_text(
        "def test_payload():\n    assert True\n",
        encoding="utf-8",
    )

    result = check_product_project_compliance(tmp_path)

    assert result["passed"] is False
    assert result["summary"]["import_dependency_edge_count"] == 2
    assert result["summary"]["import_finding_count"] == 1
    assert result["summary"]["same_project_import_dependency_edge_count"] == 2
    assert result["summary"]["vendor_import_dependency_edge_count"] == 0
    assert result["summary"]["cross_project_import_dependency_edge_count"] == 0
    assert all(edge["sameProjectScope"] for edge in result["importDependencyEdges"])
    assert any(finding["ruleId"] == "PackageImportCycle" for finding in result["findings"])
