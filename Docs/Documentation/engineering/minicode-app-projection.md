# MiniCode App Projection

Status: active engineering inventory
Audited at: 2026-06-29
Remote baseline: `QUSETIONS/MiniCode-Python` `main` at `54d47f3dc2bca02fefe5a86aa3ae4d8c510e760f`

This document maps the current MiniCode workspace into the engineering object
model from `AGENTS.md`. It records observable app facts before any large
directory migration. It is intentionally conservative: directories listed as
materials are not deletion candidates until their entry coverage, replacement
target, and retirement condition are satisfied.

The machine-readable counterpart of this inventory lives at
`Docs/Documentation/engineering/material-inventory.json`. When a historical alias still
appears in older docs, the inventory records both the current on-disk root and
the alias rather than pretending the old path still exists.

## Current Product App

Logical product app: `product/app/minicode_frontline`

Canonical AGENTS projection: `Main/MinicodeFrontline/`

Current implementation root: `minicode/`

Reasoning:

- The user has confirmed that `minicode/` is the current app implementation.
- `Main/MinicodeFrontline/Src/Application/Entry/MiniCodeFrontline.py` now
  records the product app's observable entry contract without importing the
  legacy implementation root.
- `Main/MinicodeFrontline/Src/Application/Entry/LocalCommandSurface.py` now
  owns the local slash-command contract. `minicode/cli_commands.py` imports
  this contract and still owns the temporary command handling implementation.
- `Main/MinicodeFrontline/Src/Application/Entry/RuntimeLifecycleSurface.py`
  now owns the runtime lifecycle entry contract. `pyproject.toml` console
  scripts are tested against this contract so package entry points cannot drift
  away from the Main module projection.
- `Main/MinicodeFrontline/Src/Application/Query/CurrentRuntimeProjection.py`
  checks that the current `minicode/` implementation still provides the entry
  evidence named by that contract.
- `Main/MinicodeFrontline/Src/Application/Query/RuntimeCapabilityInventory.py`
  classifies the current `minicode/` implementation into capability slices
  before any file migration. The first tracked slices cover lifecycle entries,
  command surface, session/rewind state, provider configuration, observability,
  release readiness, tool orchestration, and research-tool residue.
- `pyproject.toml` exposes stable product entry surfaces:
  `minicode-py = "minicode.main:main"`,
  `minicode-headless = "minicode.headless:main"`, and
  `minicode-readiness = "minicode.readiness:main"`.
- `minicode/main.py` owns the interactive CLI/TUI lifecycle and wires model,
  tools, permissions, session inspection, replay, checkpoints, and rewind.
- `minicode/headless.py` owns a non-interactive one-shot lifecycle for CI,
  automation, and scripted evaluation.
- `minicode/product_surfaces.py` exposes product state surfaces for
  instructions, hooks, delegation, extensions, provider readiness, and runtime
  snapshot reporting.

The AGENTS `Main/MinicodeFrontline` module now exists as the product app
projection boundary. Runtime code still executes from `minicode/`; this keeps
the migration incremental while giving the product object an auditable module
identity and mirrored test evidence.

## Entry Surfaces

| entry surface | current point | observable result | app role |
| --- | --- | --- | --- |
| Interactive CLI/TUI | `minicode-py`, `python -m minicode.main` | terminal coding session with tools, permissions, model runtime, transcript, session commands | product app lifecycle entry |
| Headless runner | `minicode-headless`, `python -m minicode.headless` | single prompt execution with optional `MINI_CODE_HEADLESS_MESSAGES_OUT` trace | product app automation entry |
| Local command surface | `minicode/cli_commands.py` | `/session`, `/session-replay`, `/sessions`, `/checkpoints`, `/rewind`, `/readiness`, `/extensions` | product app operation surface |
| Product snapshot | `minicode/product_surfaces.py` | instruction, hook, delegation, extension, readiness, and prompt bundle summaries | product app observability surface |
| Standalone readiness gate | `minicode-readiness`, `python -m minicode.readiness --json --fail-on blocked` | machine-readable runtime/provider readiness with explicit blocked/warning threshold behavior | product app quality gate entry |
| Release readiness | `minicode/release_readiness.py`, `benchmarks/release_readiness_results.md` | compile, test, smoke, runtime profile, and provider diagnostics summary | product app quality gate evidence |

## Lifecycle Projection

Configuration:

- Runtime configuration is loaded through `minicode.config.load_runtime_config`.
- Provider readiness is observed through `collect_readiness_report` and exposed
  through `/readiness`.
- Extension, user profile, and managed policy paths are surfaced through
  `product_surfaces.py`.

Startup:

- Interactive startup enters through `minicode.main:main`.
- Headless startup enters through `minicode.headless:main`.

State, data, and logs:

- Memory/state material currently appears in `.mini-code-memory/`,
  `.mini-code-memory-local/`, `.mini-code-session-memory/`, and
  `.workbuddy/memory/`.
- Session and rewind behavior is represented in `minicode/session.py`,
  `minicode/cli_commands.py`, and related tests.
- Benchmark and release artifacts currently appear under `benchmarks/` and
  `outputs/`.

Observation and health:

- `/readiness` reports provider and fallback readiness.
- `minicode-readiness --json --fail-on blocked` exposes the same readiness
  facts as a standalone gate suitable for CI and release automation.
- `minicode-readiness --examples-out <path>` exports read-only fallback
  configuration examples as an artifact without mutating user settings.
- `minicode-readiness --doctor-out <path>` exports a read-only Markdown
  readiness repair report for CI and release bundles.
- `/session`, `/session-replay`, `/sessions`, and `/checkpoints` expose durable
  session state.
- `tests/test_cli_commands.py` verifies the product command surfaces.
- `tests/test_packaging.py` verifies console script imports and CI quality gate
  wiring.

## Material Inventory

| material | current identity | observed entry/value | coverage status | retirement condition |
| --- | --- | --- | --- | --- |
| `ts-src/py-src/` (`py-src/` historical alias) | legacy Python source material | nested legacy package mirror with overlapping `minicode` modules and tests | module-level burn-down closed; 11 legacy-only modules are retired with no current caller | reopen only if a current product caller, documented product surface, and focused tests are added in `minicode/` |
| `ts-src/` | legacy TypeScript/material surface | docs site, TypeScript-era source, external material, node package and launchers | archive approved; no current product app ownership; user guide no longer links into it | physical deletion can proceed after inventory gates pass and dirty-worktree handling is explicit |
| `MiniCode-fork/` | comparison material | forked source/docs tree plus nested external MiniCode-Python copy | archive approved; no current product or test caller | physical deletion can proceed after inventory gates pass and dirty-worktree handling is explicit |
| `MiniCode-main-work/` | comparison/material workspace | current-looking docs/site, node workspace, TS tests, and nested external copy | archive approved; parity provenance migrated; no product runtime caller | physical deletion can proceed after inventory gates pass and dirty-worktree handling is explicit |
| `claude-code-src/` | fuel/reference vendor | Claude Code comparison/reference source | no product ownership | only documented comparison value remains, or reference is replaced by narrower docs |
| `superpowers-zh/` | support/fuel vendor | local Superpowers Chinese materials and skills | support material | stable support entry is documented, or copied ability is no longer needed |
| `.dead-modules-backup/` | retired-code evidence | backup for removed modules such as gateway, cron runner, protocol, safe execution | deletion blocked by audit value | removed modules stay skipped/covered, and owner approves final archival/deletion |
| `experiments/` (`paper_experiments/` historical alias) | research app/material | current research reports and captured experiment transcripts; older paper docs still use the alias | research boundary documented; executable retrieval probe rebound to current benchmark/test files | research entry is explicitly modeled as its own tool/app or moved out of product workspace |
| `outputs/` | generated evidence | benchmark, smoke, ablation, runtime, and release artifacts | evidence archive | artifacts are linked from reports or regenerated by current gates |

## Migration Already Done

- Root package entry points now resolve to `minicode.main` and
  `minicode.headless`.
- `Main/MinicodeFrontline` now exists as the canonical AGENTS Main module for
  the product app entry contract, with a mirrored `.Test.py` file.
- Local slash-command metadata has moved from `minicode/cli_commands.py` into
  the Main module's Entry contract; the handler remains in `minicode/` until a
  later Usecase/Boot migration closes the executable path.
- Runtime lifecycle entry metadata for `minicode-py` and `minicode-headless`
  now lives under the Main module's Entry contract; the executable targets still
  point to `minicode.main:main` and `minicode.headless:main`.
- `Main/MinicodeFrontline` now also exposes a pure query projection of the
  current runtime root, so the Main module can verify its legacy implementation
  evidence before any implementation files are moved.
- `Main/MinicodeFrontline` now carries a runtime capability inventory. Its next
  migration candidates are `minicode/main.py`, `minicode/headless.py`, and
  `minicode/cli_commands.py`, because they are the product lifecycle and
  operation entry surfaces.
- Product surfaces for memory/session/rewind/readiness are present in current
  Python code and local command tests.
- Standalone readiness gate support is present through `minicode/readiness.py`
  and the `minicode-readiness` console script. CI treats blocked readiness as a
  local gate failure while preserving provider warning evidence.
- Gateway and cron runner tests are explicitly skipped as removed dead code,
  with backups retained under `.dead-modules-backup/`.
- README/product homepage assets exist under `Docs/Documentation/assets/readme/`.

## Migration Still Open

- Runtime implementation files have not moved from `minicode/` into the
  canonical Main module; the Main module currently carries the entry contract
  plus local command contract, runtime-evidence, and capability-inventory
  queries, not the executable implementation.
- Runtime support objects are still implicit in config/provider/tool setup
  rather than modeled under `runtime/`.
- AGENTS product-root profile scanning now has a canonical pure query module
  at `Package/EngineeringStructure/Src/Application/Query/ProductRootProjection.py`.
  `minicode.engineering_structure` remains a compatibility surface for the
  current product package. The mirrored structure test is
  `Package/EngineeringStructure/Test/Application/Query/ProductRootProjection.Test.py`.
  The scanner now recognizes role spaces, Package/Main module candidates,
  module direct reserved items, `Src` source files, and exact `Test` mirrors.
  The root documentation workspace has been renamed to canonical `Docs/Documentation/`, so it
  is recognized as a legal project-level embedded workspace. The newly added
  `Package/EngineeringStructure` module closes its own source/test mirror.
- AGENTS compliance checking now has a tool entry at
  `python -m minicode.structure_check --root . --report .temp/structure-compliance.json`.
  It combines directory/file structure findings with the first Python
  dependency-boundary check for AGENTS modules, including Application
  child-section import rules and direct cross-module source-import violations.
  The dependency check resolves both absolute imports and relative imports,
  and the JSON report records original imports, resolved imports, import style,
  target area, and whether each edge is allowed.
  `Src/Import/` files are now recognized as Import file entities and checked
  for basic encoded stem shape and duplicate stem conflicts inside one module.
  The CLI can now print impact hotspots with `--hotspots N`, and can enforce
  gate thresholds with `--max-dependency-upstream N` and
  `--max-import-upstream N`. These thresholds turn dependency concentration and
  module import impact into explicit failure exits while preserving the full
  JSON evidence payload.
  The report path lives under `.temp/`, which is ignored and excluded from
  root structure scanning.
- Runtime/provider readiness now has a standalone gate entry at
  `python -m minicode.readiness --json --fail-on blocked`. This keeps provider
  warnings visible without conflating external channel availability with local
  product and structure gate failures.
  The same tool can export fallback configuration examples with
  `--examples-out`, keeping the repair path visible while avoiding automatic
  credential writes. It can also export a Markdown doctor report with
  `--doctor-out`, which packages issues, next actions, and safe config examples
  into a release artifact.
- Material inventory now has first capability-by-capability burn-down manifests
  for `ts-src/py-src/`, `ts-src/`, `MiniCode-fork/`, `MiniCode-main-work/`,
  and `experiments/`.
- `ts-src/py-src/` module-level burn-down is closed: 11 legacy-only modules are
  retired and current-code name residues are cleared.
- `ts-src/` now has a reference-material burn-down manifest; product-facing
  user-guide links have moved to current docs, while historical `CODE_WIKI.md`
  references are explicitly marked as comparison-only. Archive approval is
  recorded, but the directory remains in place.
- `MiniCode-fork/` now has a comparison-material burn-down manifest; deletion
  is now an owner/archive decision because `Docs/Documentation/CODE_WIKI.md` references are
  explicitly historical. Archive approval is recorded, but the directory
  remains in place.
- `MiniCode-main-work/` now has a parity-source burn-down manifest; direct test
  provenance moved to `Docs/Documentation/engineering/ts-parity-provenance.json`, so deletion
  is now an owner/archive decision rather than a pytest path dependency.
  Archive approval is recorded, but the directory remains in place.
- Research benchmark work under `experiments/` now has a reproducible benchmark
  path (`benchmarks/paper_a_retrieval_probe_eval.py` plus
  `tests/test_paper_a_retrieval_probe_eval.py`), but it is still
  artifact-backed rather than a live retrieval pipeline and remains outside the
  product app.

## Next Minimal Closed Loop

The next closed loop should be:

1. Keep `minicode/` as the active product app source root.
2. Treat `Docs/Documentation/engineering/material-inventory.json` as the single source of
   truth for current material roots and historical aliases.
3. Continue by moving from inventory to action: migrate or explicitly retain
   the remaining Docs/Documentation/test links that block deletion of comparison materials.
4. Run focused gates after every inventory update:
   `python -m compileall -q minicode tests benchmarks Main Package`,
   `python -m minicode.structure_check --root . --hotspots 5 --max-dependency-upstream 4 --report .temp/structure-compliance.json`,
   `python -m minicode.readiness --json --fail-on blocked`,
   `python -m minicode.readiness --examples-out .temp/readiness-fallback-examples.json --fail-on blocked`,
   `python -m minicode.readiness --doctor-out .temp/readiness-doctor.md --fail-on blocked`,
   `python -m pytest -q --import-mode=importlib Main/MinicodeFrontline/Test/Application/Dto/AppProjection.Test.py Main/MinicodeFrontline/Test/Application/Entry/MiniCodeFrontline.Test.py Main/MinicodeFrontline/Test/Application/Entry/LocalCommandSurface.Test.py Main/MinicodeFrontline/Test/Application/Entry/RuntimeLifecycleSurface.Test.py Main/MinicodeFrontline/Test/Application/Query/CurrentRuntimeProjection.Test.py Main/MinicodeFrontline/Test/Application/Query/RuntimeCapabilityInventory.Test.py Package/EngineeringStructure/Test/Application/Query/ProductRootProjection.Test.py Package/EngineeringStructure/Test/Application/Query/StructureCompliance.Test.py tests/test_packaging.py tests/test_cli_commands.py tests/test_engineering_inventory.py tests/test_engineering_structure.py`,
   and `python -m pytest -q tests/test_paper_a_retrieval_probe_eval.py` when
   touching research surfaces.

This closes the current handoff without pretending that old materials are
already migrated. It also gives the next migration round a safe burn-down map.
