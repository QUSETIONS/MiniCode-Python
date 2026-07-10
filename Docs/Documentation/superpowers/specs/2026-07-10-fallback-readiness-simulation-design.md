# Fallback Readiness Simulation Design

## Goal

Add a credential-safe, local-only way to evaluate a selected fallback settings
merge patch before a user edits MiniCode settings. The result must also give a
machine-readable classification for a live provider failure. This closes the
gap between a read-only patch preview and an auditable release repair decision.

The Python `minicode-py` repository is the only implementation target. The
TypeScript repository is not a dependency, source of truth, or delivery target.

## Problem

The current readiness command can generate redacted fallback examples and merge
patch previews, but it cannot answer whether a selected patch is structurally
usable without writing it to a settings file. The release report records coarse
outcomes such as `provider_api_error`, but users must infer the likely recovery
action themselves.

The current live result is intentionally not treated as a local product failure:
local gates pass, while the provider returns error `1010` and no locally ready
fallback credentials are configured. The new capability must not invent
credentials, call a provider, or convert this state into a false pass.

## Considered Approaches

1. In-memory simulation and normalized failure classification (selected).
   A pure service merges a selected preview into a copied runtime configuration,
   evaluates model/fallback selection locally, detects placeholders, and returns
   a redacted result. A separate pure classifier maps diagnostic evidence to a
   recovery category and action. This is deterministic, testable, and never
   modifies user settings.

2. Write a temporary settings file and run the normal readiness command.
   Rejected because file-based configuration can accidentally be discovered by
   other processes and makes a read-only preflight depend on filesystem state.

3. Validate only the patch JSON schema.
   Rejected because a well-formed patch can still select an unsupported model,
   leave no fallback candidate, or contain a credential placeholder.

## Architecture

### Fallback Simulation Service

Add a focused pure module under the canonical Python package. It owns:

- parsing one selected fallback preview item;
- allowlisted deep merging of the preview into an in-memory runtime mapping;
- local provider/model/fallback validation using existing runtime configuration
  and model-selection helpers;
- placeholder and redaction detection for credential fields;
- a structured result with `status`, `selected_label`, `fallback_candidates`,
  `viable_fallbacks`, `credential_state`, `issues`, `next_actions`, and a
  redacted effective configuration summary.

The service accepts mappings and returns dataclasses or mappings. It performs no
filesystem writes, no environment mutation, no adapter construction, and no
network call. It must reject unknown patch roots instead of silently merging
arbitrary configuration.

Simulation states are deliberately narrower than live readiness:

| State | Meaning |
| --- | --- |
| `ready` | A currently available local credential/configuration makes the selected fallback viable. |
| `requires-credentials` | The model and patch shape are valid, but the selected credential is absent, redacted, or a placeholder. |
| `invalid` | The selected preview is malformed, unsafe, selects no fallback, or conflicts with runtime validation. |

`requires-credentials` is never reported as `ready`, even if a placeholder has
a provider-looking shape such as `sk-...`.

### Readiness CLI and Artifact

Extend `minicode-readiness` with a read-only simulation input that selects one
item from an existing fallback patch-preview JSON artifact. It will emit one
redacted JSON payload to stdout or an explicit output path. The command will:

1. load the current runtime configuration for the requested workspace;
2. load and validate the preview artifact using the existing preview rules;
3. select exactly one preview by label, rejecting missing or ambiguous labels;
4. run the in-memory simulation; and
5. exit nonzero only when the simulation is `invalid` or when the caller opts
   into treating `requires-credentials` as a failing threshold.

The artifact will record that it is simulation-only, carries no live provider
claim, and has been redacted. It will join the readiness bundle and artifact
manifest so CI can verify its schema and hash. Existing commands and artifacts
remain backward compatible.

### Provider Failure Classification

Add a normalized provider failure record derived from existing diagnostic
evidence. It maps the current outcome, error code, and sanitized message to:

- a stable category such as `provider-rejected-request`, `authentication`,
  `rate-limited`, `provider-unavailable`, `transport`, `timeout`, or `unknown`;
- retryability;
- ownership (`local-configuration` or `external-provider`); and
- a bounded, non-secret recovery action.

Error `1010` must remain an external `provider-rejected-request` until a
provider-specific contract proves otherwise. It must not be misclassified as a
credential error or resolved fallback failure. Release JSON and Markdown will
render the classification next to the existing diagnostic and retain the raw
sanitized evidence.

## Error Handling and Safety

- All loaded JSON must be a mapping with the expected preview list.
- Preview paths and credential values are never echoed unredacted.
- Unknown labels, duplicate labels, missing merge patches, and disallowed patch
  keys return explicit `invalid` results rather than exceptions or fallback
  selection by guesswork.
- The simulation does not call `ModelSwitcher`, create a model adapter, or send
  any provider request.
- A provider failure category is advisory evidence, not a retry executor.

## Verification

Tests will cover the pure simulator, placeholder handling, allowlisted merge
rules, label selection, CLI payload and exit behavior, redaction, release
failure classification, readiness-bundle validation, and CI command wiring.
The complete Python suite, structure compliance gate, readiness bundle gate,
and release report validators must pass. The live provider may remain
`at-risk`; the expected improvement is a complete local repair decision, not a
fabricated successful provider smoke.

## Non-Goals

- Writing `~/.mini-code/settings.json` or any credential file.
- Adding credentials, selecting a paid provider, or performing a live retry.
- Altering the TypeScript repository or treating it as a dependency.
- Replacing existing readiness or release gates.
