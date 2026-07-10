from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from Package.EngineeringStructure.Src.Application.Query.StructureCompliance import (
    check_product_project_compliance,
)

MATERIAL_INVENTORY_PATH = Path("Docs/Documentation/engineering/material-inventory.json")
REQUIRED_FOCUSED_GATES = (
    "compileall",
    "product-entry-gates",
    "structure-compliance",
    "structure-compliance-artifact",
    "readiness-gate",
    "readiness-fallback-examples",
    "readiness-doctor",
    "readiness-repair-plan",
    "readiness-patch-preview",
    "readiness-bundle",
    "readiness-artifact-manifest",
    "readiness-patch-preview-gate",
    "readiness-fallback-simulation-gate",
    "fallback-switch-smoke",
    "readiness-bundle-gate",
    "release-fallback-evidence-gate",
    "release-report-gate",
    "release-markdown-report-gate",
)
README_DOCUMENTED_GATE_NAMES = (
    "release-fallback-evidence-gate",
    "release-report-gate",
    "release-markdown-report-gate",
)


def _format_path(path: object) -> str:
    if isinstance(path, list):
        return "/".join(str(part) for part in path)
    return str(path)


def _inventory_path(root: Path, raw_path: str | None) -> Path:
    if raw_path:
        candidate = Path(raw_path)
        return candidate if candidate.is_absolute() else root / candidate
    return root / MATERIAL_INVENTORY_PATH


def _material_inventory_finding(message: str, *, rule_id: str) -> dict[str, str]:
    return {
        "ruleId": rule_id,
        "message": message,
    }


def _repo_path_exists(root: Path, path_text: object) -> bool:
    path = root / str(path_text or "")
    return bool(str(path_text or "").strip()) and path.exists()


def _validate_inventory_path_list(
    *,
    root: Path,
    records: object,
    collection_label: str,
    findings: list[dict[str, str]],
    allow_missing_paths: bool = False,
) -> None:
    if not isinstance(records, list):
        findings.append(
            _material_inventory_finding(
                f"{collection_label} is not a list",
                rule_id="MaterialInventorySchema",
            )
        )
        return
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            findings.append(
                _material_inventory_finding(
                    f"{collection_label}[{index}] is not an object",
                    rule_id="MaterialInventorySchema",
                )
            )
            continue
        path_text = record.get("path")
        if not allow_missing_paths and not _repo_path_exists(root, path_text):
            findings.append(
                _material_inventory_finding(
                    f"{collection_label}[{index}] missing repo path: {path_text}",
                    rule_id="MaterialInventoryPath",
                )
            )


def check_material_inventory(
    root: str | Path,
    *,
    inventory_path: str | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    path = _inventory_path(root_path, inventory_path)
    findings: list[dict[str, str]] = []

    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        findings.append(
            _material_inventory_finding(
                f"material inventory unreadable: {exc}",
                rule_id="MaterialInventoryReadable",
            )
        )
        return {
            "path": str(path),
            "passed": False,
            "summary": {
                "focused_gate_count": 0,
                "material_count": 0,
                "finding_count": len(findings),
            },
            "findings": findings,
        }

    if not isinstance(inventory, dict):
        findings.append(
            _material_inventory_finding(
                "material inventory is not an object",
                rule_id="MaterialInventorySchema",
            )
        )
        inventory = {}
    if inventory.get("schemaVersion") != 2:
        findings.append(
            _material_inventory_finding(
                f"material inventory schemaVersion is not 2: {inventory.get('schemaVersion')}",
                rule_id="MaterialInventorySchema",
            )
        )

    current_app = inventory.get("currentProductApp")
    if not isinstance(current_app, dict):
        findings.append(
            _material_inventory_finding(
                "currentProductApp is not an object",
                rule_id="MaterialInventorySchema",
            )
        )
        current_app = {}
    if current_app.get("logicalBoundary") != "product/app/minicode_frontline":
        findings.append(
            _material_inventory_finding(
                "currentProductApp logicalBoundary is not product/app/minicode_frontline",
                rule_id="MaterialInventoryProductApp",
            )
        )
    if current_app.get("currentSourceRoot") != "minicode":
        findings.append(
            _material_inventory_finding(
                "currentProductApp currentSourceRoot is not minicode",
                rule_id="MaterialInventoryProductApp",
            )
        )
    for collection in ("entrySurfaces", "coverageEvidence"):
        if not current_app.get(collection):
            findings.append(
                _material_inventory_finding(
                    f"currentProductApp.{collection} is empty",
                    rule_id="MaterialInventoryProductApp",
                )
            )
    _validate_inventory_path_list(
        root=root_path,
        records=current_app.get("entrySurfaces"),
        collection_label="currentProductApp.entrySurfaces",
        findings=findings,
    )
    _validate_inventory_path_list(
        root=root_path,
        records=current_app.get("coverageEvidence"),
        collection_label="currentProductApp.coverageEvidence",
        findings=findings,
    )

    materials = inventory.get("materials")
    if not isinstance(materials, list):
        findings.append(
            _material_inventory_finding(
                "materials is not a list",
                rule_id="MaterialInventorySchema",
            )
        )
        materials = []
    for index, material in enumerate(materials):
        if not isinstance(material, dict):
            findings.append(
                _material_inventory_finding(
                    f"materials[{index}] is not an object",
                    rule_id="MaterialInventorySchema",
                )
            )
            continue
        path_text = material.get("path")
        presence_policy = str(material.get("presencePolicy") or "required").strip()
        optional_workspace_material = presence_policy == "optional-workspace-material"
        if presence_policy not in {"required", "optional-workspace-material"}:
            findings.append(
                _material_inventory_finding(
                    f"materials[{index}] has invalid presencePolicy: {presence_policy}",
                    rule_id="MaterialInventoryMaterial",
                )
            )
        if not optional_workspace_material and not _repo_path_exists(root_path, path_text):
            findings.append(
                _material_inventory_finding(
                    f"materials[{index}] missing repo path: {path_text}",
                    rule_id="MaterialInventoryPath",
                )
            )
        for field in (
            "identity",
            "status",
            "callerSummary",
            "replacementTarget",
            "retirementCondition",
        ):
            if not str(material.get(field) or "").strip():
                findings.append(
                    _material_inventory_finding(
                        f"materials[{index}] missing {field}",
                        rule_id="MaterialInventoryMaterial",
                    )
                )
        for collection in (
            "observedEntries",
            "coverageEvidence",
            "currentCallers",
            "historicalReferences",
        ):
            records = material.get(collection, [])
            if collection in {"observedEntries", "coverageEvidence"} and not records:
                findings.append(
                    _material_inventory_finding(
                        f"materials[{index}] missing {collection}",
                        rule_id="MaterialInventoryMaterial",
                    )
                )
            _validate_inventory_path_list(
                root=root_path,
                records=records,
                collection_label=f"materials[{index}].{collection}",
                findings=findings,
                allow_missing_paths=(
                    optional_workspace_material and collection == "observedEntries"
                ),
            )
        burndown_manifest = material.get("burndownManifest")
        if burndown_manifest and not _repo_path_exists(root_path, burndown_manifest):
            findings.append(
                _material_inventory_finding(
                    f"materials[{index}] missing burndownManifest path: {burndown_manifest}",
                    rule_id="MaterialInventoryPath",
                )
            )

    focused_gates = inventory.get("focusedGates")
    if not isinstance(focused_gates, list):
        findings.append(
            _material_inventory_finding(
                "focusedGates is not a list",
                rule_id="MaterialInventorySchema",
            )
        )
        focused_gates = []
    gates: dict[str, dict[str, Any]] = {}
    for index, gate in enumerate(focused_gates):
        if not isinstance(gate, dict):
            findings.append(
                _material_inventory_finding(
                    f"focusedGates[{index}] is not an object",
                    rule_id="MaterialInventorySchema",
                )
            )
            continue
        name = str(gate.get("name") or "").strip()
        command = str(gate.get("command") or "").strip()
        portable = str(gate.get("portableFallback") or "").strip()
        if not name:
            findings.append(
                _material_inventory_finding(
                    f"focusedGates[{index}] missing name",
                    rule_id="MaterialInventoryGate",
                )
            )
            continue
        gates[name] = gate
        if not command.startswith("python -m "):
            findings.append(
                _material_inventory_finding(
                    f"focused gate {name} command is not portable python -m: {command}",
                    rule_id="MaterialInventoryGate",
                )
            )
        if not portable.startswith("python3 -m "):
            findings.append(
                _material_inventory_finding(
                    f"focused gate {name} portableFallback is not python3 -m: {portable}",
                    rule_id="MaterialInventoryGate",
                )
            )
    for required_gate in REQUIRED_FOCUSED_GATES:
        if required_gate not in gates:
            findings.append(
                _material_inventory_finding(
                    f"focusedGates missing {required_gate}",
                    rule_id="MaterialInventoryGate",
                )
            )

    readme_text = ""
    readme_zh_text = ""
    for readme_name, target in (("README.md", "readme_text"), ("README.zh-CN.md", "readme_zh_text")):
        try:
            text = (root_path / readme_name).read_text(encoding="utf-8")
        except OSError as exc:
            findings.append(
                _material_inventory_finding(
                    f"{readme_name} unreadable: {exc}",
                    rule_id="MaterialInventoryReadme",
                )
            )
            text = ""
        if target == "readme_text":
            readme_text = text
        else:
            readme_zh_text = text
    for gate_name in README_DOCUMENTED_GATE_NAMES:
        gate = gates.get(gate_name)
        if not gate:
            continue
        command = str(gate.get("command") or "").strip()
        if command and command not in readme_text:
            findings.append(
                _material_inventory_finding(
                    f"README.md missing focused gate command: {gate_name}",
                    rule_id="MaterialInventoryReadme",
                )
            )
        if command and command not in readme_zh_text:
            findings.append(
                _material_inventory_finding(
                    f"README.zh-CN.md missing focused gate command: {gate_name}",
                    rule_id="MaterialInventoryReadme",
                )
            )

    return {
        "path": str(path),
        "passed": not findings,
        "summary": {
            "focused_gate_count": len(gates),
            "material_count": len(materials),
            "finding_count": len(findings),
        },
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="minicode-structure-check",
        description="Check AGENTS directory, file, and module dependency compliance.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to check. Defaults to the current directory.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full compliance payload as JSON.",
    )
    parser.add_argument(
        "--report",
        help="Write the full compliance payload to this JSON file.",
    )
    parser.add_argument(
        "--hotspots",
        type=int,
        default=0,
        metavar="N",
        help="Print the top N dependency and import impact hotspots.",
    )
    parser.add_argument(
        "--max-dependency-upstream",
        type=int,
        metavar="N",
        help="Fail when any source file has more than N direct upstream dependents.",
    )
    parser.add_argument(
        "--max-import-upstream",
        type=int,
        metavar="N",
        help="Fail when any module has more than N transitive upstream import dependents.",
    )
    parser.add_argument(
        "--check-material-inventory",
        action="store_true",
        help="Validate Docs/Documentation/engineering/material-inventory.json and documented gates.",
    )
    parser.add_argument(
        "--material-inventory",
        metavar="PATH",
        help="Inventory path used with --check-material-inventory. Defaults to Docs/Documentation/engineering/material-inventory.json.",
    )
    args = parser.parse_args(argv)

    result = check_product_project_compliance(Path(args.root))
    summary = result["summary"]
    quality_gate_findings: list[dict[str, str]] = []
    if (
        args.max_dependency_upstream is not None
        and summary["max_dependency_direct_upstream_count"]
        > args.max_dependency_upstream
    ):
        hotspot = next(iter(result["dependencyImpactHotspots"]), None)
        hotspot_path = (
            f": {_format_path(hotspot['sourcePathFromRoot'])}" if hotspot else ""
        )
        quality_gate_findings.append(
            {
                "ruleId": "DependencyImpactThreshold",
                "message": (
                    "max dependency direct upstream "
                    f"{summary['max_dependency_direct_upstream_count']} exceeds "
                    f"{args.max_dependency_upstream}{hotspot_path}"
                ),
            }
        )
    if (
        args.max_import_upstream is not None
        and summary["max_import_transitive_upstream_count"] > args.max_import_upstream
    ):
        hotspot = next(iter(result["importImpactHotspots"]), None)
        hotspot_path = f": {_format_path(hotspot['moduleRoot'])}" if hotspot else ""
        quality_gate_findings.append(
            {
                "ruleId": "ImportImpactThreshold",
                "message": (
                    "max import transitive upstream "
                    f"{summary['max_import_transitive_upstream_count']} exceeds "
                    f"{args.max_import_upstream}{hotspot_path}"
                ),
            }
        )
    material_inventory: dict[str, Any] | None = None
    if args.check_material_inventory:
        material_inventory = check_material_inventory(
            Path(args.root),
            inventory_path=args.material_inventory,
        )
        for finding in material_inventory["findings"]:
            quality_gate_findings.append(
                {
                    "ruleId": str(finding.get("ruleId") or "MaterialInventory"),
                    "message": str(finding.get("message") or ""),
                }
            )
    cli_passed = result["passed"] and not quality_gate_findings
    result = {
        **result,
        "qualityGatePassed": not quality_gate_findings,
        "qualityGateFindings": quality_gate_findings,
        "cliPassed": cli_passed,
    }
    if material_inventory is not None:
        result["materialInventory"] = material_inventory
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "passed" if cli_passed else "failed"
        print(f"AGENTS structure compliance: {status}")
        print(f"records: {summary['record_count']}")
        print(f"structure findings: {summary['finding_count']}")
        print(f"dependency edges: {summary['dependency_edge_count']}")
        print(f"dependency impact nodes: {summary['dependency_impact_node_count']}")
        print(f"dependency impact hotspots: {len(result['dependencyImpactHotspots'])}")
        if args.hotspots > 0:
            for hotspot in result["dependencyImpactHotspots"][: args.hotspots]:
                print(
                    "  - "
                    f"{hotspot['directUpstreamCount']} direct upstream: "
                    f"{_format_path(hotspot['sourcePathFromRoot'])}"
                )
        print(
            "max dependency direct upstream: "
            f"{summary['max_dependency_direct_upstream_count']}"
        )
        print(f"import dependency edges: {summary['import_dependency_edge_count']}")
        print(
            "same-project import dependency edges: "
            f"{summary['same_project_import_dependency_edge_count']}"
        )
        print(
            "vendor import dependency edges: "
            f"{summary['vendor_import_dependency_edge_count']}"
        )
        print(
            "cross-project import dependency edges: "
            f"{summary['cross_project_import_dependency_edge_count']}"
        )
        print(f"import impact nodes: {summary['import_impact_node_count']}")
        print(f"import impact hotspots: {len(result['importImpactHotspots'])}")
        if args.hotspots > 0:
            for hotspot in result["importImpactHotspots"][: args.hotspots]:
                print(
                    "  - "
                    f"{hotspot['transitiveUpstreamCount']} transitive upstream: "
                    f"{_format_path(hotspot['moduleRoot'])}"
                )
        print(
            "max import transitive upstream: "
            f"{summary['max_import_transitive_upstream_count']}"
        )
        print(f"import findings: {summary['import_finding_count']}")
        print(f"dependency findings: {summary['dependency_finding_count']}")
        print(f"total findings: {summary['total_finding_count']}")
        if material_inventory is not None:
            inventory_summary = material_inventory["summary"]
            print(
                "material inventory gates: "
                f"{inventory_summary['focused_gate_count']}"
            )
            print(
                "material inventory materials: "
                f"{inventory_summary['material_count']}"
            )
            print(
                "material inventory findings: "
                f"{inventory_summary['finding_count']}"
            )
        print(f"quality gate findings: {len(quality_gate_findings)}")
        for finding in quality_gate_findings:
            print(f"- {finding['ruleId']}: {finding['message']}")
        for finding in result["findings"]:
            path = "/".join(finding.get("pathFromRoot") or []) or "."
            print(f"- {finding.get('ruleId')}: {path}: {finding.get('message')}")

    return 0 if cli_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
