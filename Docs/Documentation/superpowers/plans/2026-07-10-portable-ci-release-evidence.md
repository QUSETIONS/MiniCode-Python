# Portable CI and Release Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generic GitHub CI honest and cross-platform while removing developer-machine absolute paths from committed release evidence.

**Architecture:** The workflow generates readiness evidence without deployment thresholds and keeps validators as hard gates. A pure recursive normalizer in the release benchmark rewrites repository and home path prefixes before JSON/Markdown serialization, leaving validation and provider classification unchanged.

**Tech Stack:** Python 3.11+, pytest, GitHub Actions YAML, Git Bash on GitHub-hosted Windows.

## Global Constraints

- Do not inject mock mode, fake provider credentials, secrets, or live provider calls into generic CI.
- Do not weaken artifact redaction, manifest, patch-preview, simulation, fallback-switch, bundle, structure, compile, test, lint, or type gates.
- Normalize the resolved repository root to `.` and an external resolved home directory to `~`.
- Preserve the dirty local research/reference directories without staging them.

---

### Task 1: Honest Cross-Platform CI Workflow

**Files:**
- Modify: `tests/test_packaging.py:79-131`
- Modify: `.github/workflows/ci.yml:39-105`

**Interfaces:**
- Consumes: existing `minicode.readiness` report-only behavior and release artifact validators.
- Produces: a CI workflow that runs without deployment credentials on Linux, Windows, and macOS.

- [ ] **Step 1: Write failing workflow contract assertions**

Replace the readiness threshold assertions with exact report-only commands and add negative assertions:

```python
assert "python -m minicode.readiness --json" in content
assert "python -m minicode.readiness --json --fail-on blocked" not in content
assert "--bundle-out .temp/readiness-bundle --fail-on blocked" not in content
assert "MINI_CODE_MODEL_MODE" not in content
assert "OPENAI_API_KEY" not in content

mypy_step = content.split("- name: Type check (mypy baseline)", 1)[1]
assert "shell: bash" in mypy_step.split("- name:", 1)[0]
```

- [ ] **Step 2: Run the workflow contract test and verify RED**

Run: `python3 -m pytest -q tests/test_packaging.py::test_ci_workflow_runs_release_quality_gates --tb=short`

Expected: FAIL because readiness commands still include `--fail-on blocked` and the mypy step lacks `shell: bash`.

- [ ] **Step 3: Make readiness generation report-only and declare Bash for mypy**

Change the six readiness generation commands to omit `--fail-on blocked`. Keep every following validator command unchanged. Add the shell declaration directly under the mypy step:

```yaml
      - name: Type check (mypy baseline)
        shell: bash
        run: |
```

- [ ] **Step 4: Run workflow tests and local no-config commands**

Run:

```bash
python3 -m pytest -q tests/test_packaging.py tests/test_engineering_inventory.py --tb=short
python3 -m minicode.readiness --json >/dev/null
python3 -m minicode.readiness --bundle-out .temp/readiness-bundle >/dev/null
python3 -m minicode.release_readiness --check-readiness-bundle .temp/readiness-bundle
```

Expected: all commands exit 0; the bundle validator reports 6 valid artifacts even though local readiness may remain `blocked`.

- [ ] **Step 5: Commit the CI fix**

```bash
git add .github/workflows/ci.yml tests/test_packaging.py
git commit -m "fix: make generic readiness CI portable"
```

### Task 2: Portable Release Evidence Paths

**Files:**
- Modify: `tests/test_release_readiness_benchmark.py`
- Modify: `benchmarks/release_readiness.py:48-50,754-786`

**Interfaces:**
- Consumes: arbitrary nested JSON-compatible values and Markdown strings.
- Produces: `_normalize_evidence_paths(value: object, *, repo_root: Path, home: Path) -> object`.

- [ ] **Step 1: Write failing recursive normalization tests**

Import `_normalize_evidence_paths` and add:

```python
def test_release_evidence_paths_are_portable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    payload = {
        "path": str(repo / ".temp" / "trace.json"),
        "command": f"python {repo / 'benchmarks' / 'release_readiness.py'}",
        "home_path": str(home / ".mini-code" / "settings.json"),
        "nested": [str(repo), 7, False, None],
    }

    normalized = _normalize_evidence_paths(payload, repo_root=repo, home=home)

    assert normalized == {
        "path": ".temp/trace.json",
        "command": "python benchmarks/release_readiness.py",
        "home_path": "~/.mini-code/settings.json",
        "nested": [".", 7, False, None],
    }
```

- [ ] **Step 2: Run the normalizer test and verify RED**

Run: `python3 -m pytest -q tests/test_release_readiness_benchmark.py::test_release_evidence_paths_are_portable --tb=short`

Expected: collection ERROR because `_normalize_evidence_paths` does not exist.

- [ ] **Step 3: Implement the pure recursive normalizer**

Add a function near `REPO_ROOT` that handles dictionaries, lists, tuples, strings, and scalar values. Normalize the repository prefix before the home prefix so repositories located under home become `.` paths:

```python
def _normalize_evidence_paths(value, *, repo_root: Path = REPO_ROOT, home: Path | None = None):
    if isinstance(value, dict):
        return {key: _normalize_evidence_paths(item, repo_root=repo_root, home=home) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_evidence_paths(item, repo_root=repo_root, home=home) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_evidence_paths(item, repo_root=repo_root, home=home) for item in value)
    if not isinstance(value, str):
        return value
    repo_text = str(repo_root.resolve())
    home_text = str((home or Path.home()).resolve())
    normalized = value.replace(repo_text + os.sep, "")
    if normalized == repo_text:
        normalized = "."
    if home_text != repo_text:
        normalized = normalized.replace(home_text + os.sep, "~/")
        if normalized == home_text:
            normalized = "~"
    return normalized
```

- [ ] **Step 4: Normalize JSON and Markdown immediately before serialization**

After building `payload` and `markdown`, call:

```python
payload = _normalize_evidence_paths(payload)
markdown = _normalize_evidence_paths(markdown)
```

Keep `check_release_report` and `check_release_markdown` after file writes so the normalized artifacts validate through production entry points.

- [ ] **Step 5: Run benchmark unit tests**

Run: `python3 -m pytest -q tests/test_release_readiness_benchmark.py tests/test_release_readiness.py --tb=short`

Expected: all tests pass.

- [ ] **Step 6: Commit the normalizer**

```bash
git add benchmarks/release_readiness.py tests/test_release_readiness_benchmark.py
git commit -m "fix: normalize release evidence paths"
```

### Task 3: Refresh Evidence and Verify the Remote Branch

**Files:**
- Modify: `benchmarks/release_readiness_results.json`
- Modify: `benchmarks/release_readiness_results.md`
- Modify if regenerated: `benchmarks/runtime_profile_eval_results.json`
- Modify if regenerated: `benchmarks/runtime_profile_eval_results.md`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: portable committed evidence and a GitHub PR with check-runs.

- [ ] **Step 1: Regenerate release evidence**

Run: `python3 benchmarks/release_readiness.py`

Expected: exit 0 in report-only mode; generated JSON/Markdown validate even when provider status is `blocked` or `at-risk`.

- [ ] **Step 2: Verify path portability**

Run:

```bash
rg -n '/home/tim|桌面/minicode' benchmarks/release_readiness_results.json benchmarks/release_readiness_results.md
python3 -m minicode.release_readiness --check-release-report benchmarks/release_readiness_results.json
python3 -m minicode.release_readiness --check-release-markdown benchmarks/release_readiness_results.md --release-json benchmarks/release_readiness_results.json
```

Expected: `rg` exits 1 with no matches; both validators exit 0.

- [ ] **Step 3: Run complete clean-checkout gates**

Run from a detached temporary worktree at the new HEAD:

```bash
python3 -m compileall -q minicode tests benchmarks Main Package
python3 -m minicode.structure_check --root . --hotspots 5 --max-dependency-upstream 4 --check-material-inventory --report .temp/structure-compliance.json
python3 -m pytest -q --tb=short
```

Expected: compile exit 0, structure findings 0, full pytest exit 0.

- [ ] **Step 4: Commit refreshed evidence**

```bash
git add benchmarks/release_readiness_results.json benchmarks/release_readiness_results.md benchmarks/runtime_profile_eval_results.json benchmarks/runtime_profile_eval_results.md
git commit -m "docs: refresh portable release evidence"
```

- [ ] **Step 5: Push and create the pull request**

Push `fix/test-pollution-and-provider-detection`, create a PR targeting `main`, and verify GitHub check-runs appear for all six OS/Python matrix jobs. Do not persist a token in Git configuration or credential storage.
