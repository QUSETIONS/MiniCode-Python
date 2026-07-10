# Portable CI and Release Evidence Design

## Goal

Make the pushed Python branch reproducible on GitHub-hosted Linux, Windows, and
macOS runners without fake provider readiness, while keeping release evidence
portable across machines.

## Problems

The generic CI workflow currently treats missing deployment credentials as a
code failure by passing `--fail-on blocked` to readiness report generation.
Fresh GitHub runners have no MiniCode settings or provider credentials, so these
steps fail before the artifact validators can run. The Windows matrix also runs
Bash-only mypy threshold syntax under the default PowerShell shell. Finally,
committed release reports contain developer-machine absolute paths.

## Selected Design

### Honest Readiness Reporting

Generic CI generates readiness reports and artifacts without a failure
threshold. A missing model remains visibly `blocked`; CI does not rewrite it as
ready and does not inject mock modes, placeholder credentials, secrets, or live
provider calls. Artifact redaction, manifest integrity, patch-preview schema,
fallback simulation, fallback-switch behavior, and bundle validation remain
failing gates.

Deployment-specific workflows may opt into `--fail-on blocked` or stricter
thresholds when they intentionally provide deployment configuration. This
generic repository workflow does not make that claim.

### Cross-Platform Mypy Gate

The mypy baseline step declares `shell: bash`. GitHub-hosted Windows runners
provide Git Bash, so the existing count-and-threshold script keeps one behavior
across the full OS matrix without duplicating PowerShell logic.

### Portable Release Evidence

Before writing release JSON or Markdown, the release benchmark recursively
normalizes strings:

- the resolved repository root becomes `.`;
- the resolved user home becomes `~` when it is outside the repository root;
- credentials and other sensitive values continue through the existing
  redaction layer.

Paths in generated manifests and diagnostic links therefore remain meaningful
when commands are run from the repository root. Validators continue resolving
relative paths against the caller's current repository root. No validator is
weakened.

## Rejected Designs

- Injecting mock mode or fake credentials into CI would create readiness claims
  that are not backed by a provider and violates the repository's no-fake-pass
  rule.
- Requiring live provider secrets for every pull request would make code quality
  gates depend on external availability, spend, and secret exposure.
- Skipping readiness artifacts entirely would remove the evidence needed by the
  bundle and release validators.

## Verification

- Packaging tests assert that generic CI readiness commands omit failure
  thresholds and that no mock/provider credential environment is injected.
- Packaging tests assert that the mypy step uses Bash.
- Release benchmark tests assert recursive repository/home path normalization.
- Generated release JSON and Markdown contain no developer-machine absolute
  repository path.
- Clean-checkout `compileall`, AGENTS structure scanning, focused tests, and the
  full pytest suite pass.
- The updated branch is pushed and a pull request is created so GitHub Actions
  runs the six-platform matrix.
