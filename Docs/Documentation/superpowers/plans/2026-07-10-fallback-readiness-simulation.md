# Fallback Readiness Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a credential-safe fallback patch simulator and normalized provider failure classification to the Python MiniCode readiness and release evidence.

**Architecture:** A new pure simulation module converts an allowlisted settings merge patch into a copied runtime mapping, neutralizes placeholder credentials, and delegates provider/fallback evaluation to the existing readiness surface. Provider diagnostics gain a pure normalized classification that flows through runtime-profile and release JSON/Markdown. CLI, bundle, manifest, CI, inventory, and tests consume these two focused interfaces.

**Tech Stack:** Python 3.11+, dataclasses, argparse, JSON, pytest, existing `minicode.config`, `minicode.product_surfaces`, and `minicode.release_readiness` utilities.

## Global Constraints

- The Python `minicode-py` repository is the only implementation target.
- Do not write `~/.mini-code/settings.json`, credentials, or process environment variables.
- Do not construct a model adapter or call a provider during simulation.
- Placeholder or redacted credentials must never produce `ready`.
- Error `1010` remains an external `provider-rejected-request` until a provider-specific contract proves otherwise.
- Preserve existing readiness CLI behavior when simulation options are absent.
- Every new artifact must be redacted, manifested, and accepted by the structure/release gates.

---

### Task 1: Pure Fallback Patch Simulation

**Files:**
- Create: `minicode/fallback_simulation.py`
- Create: `tests/test_fallback_simulation.py`

**Interfaces:**
- Consumes: `build_readiness_report(cwd, runtime=...) -> ReadinessReport`.
- Produces: `FallbackSimulation`, `select_fallback_preview(payload, label)`, and `simulate_fallback_patch(cwd, runtime, preview)`.

- [ ] **Step 1: Write failing tests for selection, placeholders, ready credentials, and unsafe roots**

```python
from minicode.fallback_simulation import (
    select_fallback_preview,
    simulate_fallback_patch,
)


def _openai_preview(key: str = "sk-...") -> dict:
    return {
        "label": "OpenAI fallback",
        "target_path": "/ignored/settings.json",
        "merge_patch": {
            "fallbackModels": ["gpt-4o"],
            "env": {
                "OPENAI_API_KEY": key,
                "OPENAI_BASE_URL": "https://api.openai.com",
            },
        },
        "safety": "preview-only; no settings are modified",
    }


def test_placeholder_patch_requires_credentials() -> None:
    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "authToken": "primary-token",
            "baseUrl": "https://api.anthropic.com",
        },
        preview=_openai_preview(),
    )
    assert result.status == "requires-credentials"
    assert result.credential_state == "placeholder"
    assert result.fallback_candidates == ["gpt-4o"]
    assert result.viable_fallbacks == []
    assert result.live_provider_claim is False


def test_existing_real_runtime_credential_can_be_ready() -> None:
    result = simulate_fallback_patch(
        ".",
        runtime={
            "model": "claude-sonnet-4-20250514",
            "authToken": "primary-token",
            "baseUrl": "https://api.anthropic.com",
            "openaiApiKey": "existing-local-secret",
            "openaiBaseUrl": "https://api.openai.com",
        },
        preview=_openai_preview(key="[REDACTED]"),
    )
    assert result.status == "ready"
    assert result.credential_state == "existing-local"
    assert result.viable_fallbacks == ["gpt-4o"]


def test_unknown_patch_root_is_invalid() -> None:
    preview = _openai_preview()
    preview["merge_patch"]["mcpServers"] = {"unsafe": {"command": "sh"}}
    result = simulate_fallback_patch(".", runtime={"model": "x"}, preview=preview)
    assert result.status == "invalid"
    assert "mcpServers" in result.issues[0]


def test_preview_selection_rejects_duplicate_labels() -> None:
    payload = {"fallback_settings_patch_preview": [_openai_preview(), _openai_preview()]}
    selected, error = select_fallback_preview(payload, "OpenAI fallback")
    assert selected is None
    assert "ambiguous" in error
```

- [ ] **Step 2: Run the focused tests and confirm the missing module failure**

Run: `python3 -m pytest -q tests/test_fallback_simulation.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'minicode.fallback_simulation'`.

- [ ] **Step 3: Implement the minimal pure simulation service**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minicode.product_surfaces import build_readiness_report


ALLOWED_PATCH_ROOTS = {
    "fallbackModels",
    "anthropicFallbackModels",
    "openaiFallbackModels",
    "openrouterFallbackModels",
    "customFallbackModels",
    "env",
}
ENV_RUNTIME_KEYS = {
    "ANTHROPIC_API_KEY": "apiKey",
    "ANTHROPIC_AUTH_TOKEN": "authToken",
    "ANTHROPIC_BASE_URL": "baseUrl",
    "OPENAI_API_KEY": "openaiApiKey",
    "OPENAI_BASE_URL": "openaiBaseUrl",
    "OPENROUTER_API_KEY": "openrouterApiKey",
    "OPENROUTER_BASE_URL": "openrouterBaseUrl",
    "CUSTOM_API_KEY": "customApiKey",
    "CUSTOM_API_BASE_URL": "customBaseUrl",
}
PLACEHOLDERS = {"", "[REDACTED]", "sk-...", "sk-or-..."}


@dataclass(frozen=True, slots=True)
class FallbackSimulation:
    status: str
    selected_label: str
    credential_state: str
    fallback_candidates: list[str] = field(default_factory=list)
    viable_fallbacks: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    effective_config: dict[str, Any] = field(default_factory=dict)
    simulation_only: bool = True
    live_provider_claim: bool = False


def select_fallback_preview(payload: Any, label: str) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(payload, dict):
        return None, "fallback preview payload is not an object"
    previews = payload.get("fallback_settings_patch_preview")
    if not isinstance(previews, list):
        return None, "fallback preview list is missing"
    matches = [item for item in previews if isinstance(item, dict) and item.get("label") == label]
    if not matches:
        return None, f"fallback preview label not found: {label}"
    if len(matches) != 1:
        return None, f"fallback preview label is ambiguous: {label}"
    return matches[0], ""
```

Complete `simulate_fallback_patch` by copying `runtime`, validating root keys,
mapping allowlisted `env` keys through `ENV_RUNTIME_KEYS`, preserving an existing
real credential when the patch value is redacted, blanking placeholder-only
credentials, copying fallback model lists, and calling
`build_readiness_report(cwd, runtime=effective_runtime)`. Return `ready` only
when `report.viable_fallbacks` is non-empty; return `requires-credentials` for a
valid candidate blocked only by missing/placeholder credentials; otherwise
return `invalid`. Expose only provider names, model lists, base URLs, and
credential presence booleans in `effective_config`.

- [ ] **Step 4: Run the focused tests**

Run: `python3 -m pytest -q tests/test_fallback_simulation.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the pure simulator**

```bash
git add minicode/fallback_simulation.py tests/test_fallback_simulation.py
git commit -m "feat: add fallback readiness simulation"
```

### Task 2: Readiness CLI and Simulation Artifact

**Files:**
- Modify: `minicode/readiness.py`
- Modify: `minicode/release_readiness.py`
- Modify: `tests/test_release_integration.py`
- Modify: `tests/test_release_readiness.py`

**Interfaces:**
- Consumes: Task 1 `select_fallback_preview` and `simulate_fallback_patch`.
- Produces: `--simulate-fallback-patch`, `--fallback-label`, `--simulation-out`, `--simulation-fail-on`, `check_fallback_simulation_payload`, and `check_fallback_simulation`.

- [ ] **Step 1: Add failing black-box and artifact-validator tests**

```python
def test_readiness_simulates_selected_patch_without_writing_settings(tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.json"
    output_path = tmp_path / "simulation.json"
    preview_path.write_text(json.dumps({
        "status": "warning",
        "risk_scope": "no-fallback-configured",
        "fallback_settings_patch_preview": [{
            "label": "OpenAI fallback",
            "target_path": "/must/not/be/written.json",
            "merge_patch": {
                "fallbackModels": ["gpt-4o"],
                "env": {"OPENAI_API_KEY": "sk-...", "OPENAI_BASE_URL": "https://api.openai.com"},
            },
            "safety": "preview-only; no settings are modified",
        }],
    }), encoding="utf-8")
    completed = subprocess.run([
        sys.executable, "-m", "minicode.readiness",
        "--cwd", str(tmp_path),
        "--simulate-fallback-patch", str(preview_path),
        "--fallback-label", "OpenAI fallback",
        "--simulation-out", str(output_path),
    ], cwd=tmp_path, env=_release_env(tmp_path), capture_output=True, text=True, check=False)
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "requires-credentials"
    assert payload["simulation_only"] is True
    assert payload["live_provider_claim"] is False
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert not (tmp_path / "must" / "not" / "be" / "written.json").exists()
```

Add validator tests asserting a valid payload passes, while a payload with
`status="ready"` plus `credential_state="placeholder"`,
`live_provider_claim=True`, a missing selected label, or a leaked secret fails.

- [ ] **Step 2: Run the focused tests and confirm argument/function failures**

Run: `python3 -m pytest -q tests/test_release_integration.py tests/test_release_readiness.py -k 'simulation'`

Expected: failures report unrecognized CLI arguments and missing validator imports.

- [ ] **Step 3: Implement CLI output and validator**

Add an argparse output option carrying the preview path, require
`--fallback-label` with it, load JSON, validate it with
`check_fallback_patch_preview_payload`, select one item, call the Task 1 service,
redact `asdict(result)`, print it, and optionally write it through `_write_json`.
Implement `--simulation-fail-on` with choices `requires-credentials` and
`invalid`; without it, only `invalid` exits nonzero.

```python
SIMULATION_STATUS_ORDER = {"ready": 0, "requires-credentials": 1, "invalid": 2}


def _should_fail_simulation(status: str, fail_on: str | None) -> bool:
    threshold = fail_on or "invalid"
    return SIMULATION_STATUS_ORDER.get(status, 2) >= SIMULATION_STATUS_ORDER[threshold]
```

Implement `check_fallback_simulation_payload(payload)` so it requires the three
states, `simulation_only is True`, `live_provider_claim is False`, one selected
label, lists for candidates/viable models/issues/actions, a credential state,
and no sensitive-text leaks. Reject `ready` unless viable fallbacks exist and
the credential state is `existing-local`.

- [ ] **Step 4: Run CLI and validator tests**

Run: `python3 -m pytest -q tests/test_fallback_simulation.py tests/test_release_integration.py tests/test_release_readiness.py -k 'fallback or simulation or readiness'`

Expected: all selected tests pass.

- [ ] **Step 5: Commit CLI and artifact validation**

```bash
git add minicode/readiness.py minicode/release_readiness.py tests/test_release_integration.py tests/test_release_readiness.py
git commit -m "feat: expose fallback simulation artifact"
```

### Task 3: Normalized Provider Failure Classification

**Files:**
- Modify: `minicode/runtime_profile_eval.py`
- Modify: `benchmarks/runtime_profile_eval.py`
- Modify: `tests/test_runtime_profile_benchmark.py`
- Modify: `tests/test_runtime_profile_eval.py`

**Interfaces:**
- Produces: `ProviderFailureClassification` and `classify_provider_failure(outcome, error_code, summary, risk_scope)`.
- Extends: `ProviderDiagnostic` with `failure_category`, `retryable`, `ownership`, and `recovery_action`.

- [ ] **Step 1: Add failing tests for error 1010 and common provider classes**

```python
from minicode.runtime_profile_eval import classify_provider_failure


def test_provider_error_1010_is_external_rejected_request() -> None:
    result = classify_provider_failure(
        outcome="provider_api_error",
        error_code="1010",
        summary="Model API error (RuntimeError): error code: 1010",
        risk_scope="external-provider",
    )
    assert result.category == "provider-rejected-request"
    assert result.retryable is False
    assert result.ownership == "external-provider"
    assert "provider contract" in result.recovery_action


def test_common_codes_have_stable_failure_classes() -> None:
    assert classify_provider_failure("provider_api_error", "401", "", "provider-config").category == "authentication"
    assert classify_provider_failure("provider_api_error", "429", "", "external-provider").category == "rate-limited"
    assert classify_provider_failure("provider_outage", "503", "", "external-provider").category == "provider-unavailable"
    assert classify_provider_failure("timeout", "", "", "external-provider").category == "timeout"
```

- [ ] **Step 2: Run focused tests and confirm the missing classifier failure**

Run: `python3 -m pytest -q tests/test_runtime_profile_benchmark.py tests/test_runtime_profile_eval.py`

Expected: import or attribute failures for the new classifier fields.

- [ ] **Step 3: Implement classification and diagnostic propagation**

```python
@dataclass(frozen=True, slots=True)
class ProviderFailureClassification:
    category: str
    retryable: bool
    ownership: str
    recovery_action: str


def classify_provider_failure(
    outcome: str,
    error_code: str = "",
    summary: str = "",
    risk_scope: str = "unknown",
) -> ProviderFailureClassification:
    code = str(error_code).strip().lower()
    if outcome == "answered":
        return ProviderFailureClassification("none", False, "none", "No recovery action required.")
    if code in {"401", "403"}:
        return ProviderFailureClassification("authentication", False, "local-configuration", "Verify the configured provider credential and endpoint.")
    if code == "429":
        return ProviderFailureClassification("rate-limited", True, "external-provider", "Honor provider retry guidance or switch to a ready fallback.")
    if outcome == "provider_api_error" and code == "1010":
        return ProviderFailureClassification("provider-rejected-request", False, "external-provider", "Inspect the provider contract, selected model, and sanitized request evidence.")
    if outcome == "provider_outage" or code.startswith("5"):
        return ProviderFailureClassification("provider-unavailable", True, "external-provider", "Retry the provider smoke or switch to a ready fallback.")
    if outcome == "timeout":
        return ProviderFailureClassification("timeout", True, "external-provider", "Retry within the bounded smoke timeout or switch fallback.")
    if outcome in {"provider_channel_unavailable"}:
        return ProviderFailureClassification("configuration", False, "local-configuration", "Repair model-to-provider channel configuration.")
    if outcome == "empty_output":
        return ProviderFailureClassification("provider-response", True, "external-provider", "Inspect the sanitized response trace before retrying.")
    return ProviderFailureClassification("unknown", False, risk_scope or "unknown", "Inspect sanitized provider diagnostics before choosing a recovery action.")
```

In `_classify_provider_diagnostic`, call this function after determining outcome
and context, then populate all four new `ProviderDiagnostic` fields. Extend the
runtime profile Markdown diagnostic table with category, retryability,
ownership, and recovery action.

- [ ] **Step 4: Run runtime profile tests**

Run: `python3 -m pytest -q tests/test_runtime_profile_benchmark.py tests/test_runtime_profile_eval.py`

Expected: all tests pass.

- [ ] **Step 5: Commit provider failure classification**

```bash
git add minicode/runtime_profile_eval.py benchmarks/runtime_profile_eval.py tests/test_runtime_profile_benchmark.py tests/test_runtime_profile_eval.py
git commit -m "feat: classify provider failures"
```

### Task 4: Bundle, Release, Structure, and CI Integration

**Files:**
- Modify: `minicode/readiness.py`
- Modify: `minicode/release_readiness.py`
- Modify: `benchmarks/release_readiness.py`
- Modify: `tests/test_release_readiness.py`
- Modify: `tests/test_release_readiness_benchmark.py`
- Modify: `tests/test_release_integration.py`
- Modify: `tests/test_packaging.py`
- Modify: `tests/test_engineering_inventory.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `Docs/Documentation/engineering/material-inventory.json`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Consumes: Tasks 1-3 simulation and classification payloads.
- Produces: bundle artifact `readiness-fallback-simulations.json`, manifest label `fallback_simulations_json`, smoke `fallback-simulation`, and release diagnostic classification evidence.

- [ ] **Step 1: Add failing integration assertions**

Extend bundle tests to require `readiness-fallback-simulations.json`, require its
manifest entry, and validate every result. Extend release JSON/Markdown fixtures
so each failed provider diagnostic includes:

```python
{
    "failure_category": "provider-rejected-request",
    "retryable": False,
    "ownership": "external-provider",
    "recovery_action": "Inspect the provider contract, selected model, and sanitized request evidence.",
}
```

Add packaging and inventory assertions for these exact commands:

```text
python -m minicode.release_readiness --check-fallback-simulation .temp/readiness-bundle/readiness-fallback-simulations.json
python -m minicode.release_readiness --check-release-report benchmarks/release_readiness_results.json
```

- [ ] **Step 2: Run focused integration tests and confirm missing artifact/evidence failures**

Run: `python3 -m pytest -q tests/test_release_readiness.py tests/test_release_readiness_benchmark.py tests/test_release_integration.py tests/test_packaging.py tests/test_engineering_inventory.py`

Expected: failures identify the missing simulation artifact, manifest label,
smoke, diagnostic fields, and documented inventory command.

- [ ] **Step 3: Generate all preview simulations in the bundle**

When `_write_bundle` receives the unredacted current runtime and preview payload,
simulate each explicitly listed preview; do not pick a default. Write:

```json
{
  "simulation_only": true,
  "live_provider_claim": false,
  "simulations": []
}
```

Populate `simulations` in preview order, redact before writing, add
`fallback_simulations_json` to the bundle manifest and returned paths, and make
`check_readiness_bundle` call the simulation payload validator for every item.

- [ ] **Step 4: Require normalized failure evidence in release reports**

For every provider diagnostic whose outcome is not `answered`, require non-empty
`failure_category`, `ownership`, and `recovery_action`, and require `retryable`
to be a boolean. Render these fields in release Markdown. Preserve the existing
coarse outcome so status calculation stays backward compatible.

- [ ] **Step 5: Wire benchmark smoke, manifest, CI, inventory, and README commands**

Add the bundle simulation validator as a benchmark smoke and artifact-manifest
entry. Add the CLI validator command to CI after bundle creation. Add a focused
gate named `readiness-fallback-simulation-gate` to the material inventory and
document the same command in both READMEs. Do not add a live provider call to CI.

- [ ] **Step 6: Run focused integration and structure checks**

Run: `python3 -m pytest -q tests/test_fallback_simulation.py tests/test_release_readiness.py tests/test_release_readiness_benchmark.py tests/test_release_integration.py tests/test_runtime_profile_benchmark.py tests/test_runtime_profile_eval.py tests/test_packaging.py tests/test_engineering_inventory.py tests/test_engineering_structure.py`

Expected: all selected tests pass.

Run: `python3 -m minicode.structure_check --root . --hotspots 5 --max-dependency-upstream 4 --check-material-inventory --report .temp/structure-compliance.json`

Expected: structure compliance passes with zero material-inventory and quality-gate findings.

- [ ] **Step 7: Run complete verification**

Run: `python3 -m compileall -q minicode tests benchmarks Main Package`

Expected: exit code 0.

Run: `python3 -m pytest -q --import-mode=importlib`

Expected: all tests pass; the two existing skips remain the only skips.

Run: `python3 benchmarks/release_readiness.py`

Expected: local gates and new simulation/classification smokes pass. Provider
status may remain `at-risk` with error `1010`, now carrying normalized recovery
evidence.

- [ ] **Step 8: Commit release integration**

```bash
git add minicode/readiness.py minicode/release_readiness.py benchmarks/release_readiness.py tests/test_release_readiness.py tests/test_release_readiness_benchmark.py tests/test_release_integration.py tests/test_packaging.py tests/test_engineering_inventory.py .github/workflows/ci.yml Docs/Documentation/engineering/material-inventory.json README.md README.zh-CN.md benchmarks/release_readiness_results.json benchmarks/release_readiness_results.md benchmarks/runtime_profile_eval_results.json benchmarks/runtime_profile_eval_results.md
git commit -m "feat: gate fallback simulation evidence"
```
