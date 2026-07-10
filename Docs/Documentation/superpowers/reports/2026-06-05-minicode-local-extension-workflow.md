# MiniCode Local Extension Workflow

Date: 2026-06-05

## Goal

Document the lightweight local extension workflow that now ships with
`minicode`.

## Manifest format

Each extension bundle is a directory with an `extension.json` manifest.

Required fields used by the current product surface:

- `name`
- `version`
- `description`
- `enabled`
- `entrypoint`

Example:

```json
{
  "name": "git-helpers",
  "version": "1.0.0",
  "description": "Local helper bundle",
  "enabled": true,
  "entrypoint": "bundle.py"
}
```

## Search roots

MiniCode currently discovers extensions in two places:

- global: `%USERPROFILE%\\.mini-code\\extensions\\<name>\\extension.json`
- project: `<workspace>\\.mini-code\\extensions\\<name>\\extension.json`

Project extensions intentionally override the local workspace experience, while
global extensions remain available across repos.

## Operator commands

The product surface now exposes these commands:

- `/extensions`
  - list discovered extension bundles and show enabled state
- `/extension-inspect <name>`
  - inspect the resolved manifest, entrypoint path, and scope
- `/extension-enable <name>`
  - enable a bundle in place by updating its manifest
- `/extension-disable <name>`
  - disable a bundle in place by updating its manifest

If both project and global bundles share the same name, use an explicit scope:

- `project:git-helpers`
- `global:git-helpers`

## Sharing workflow

The intended lightweight sharing workflow is local-first:

1. Create a folder under `.mini-code/extensions/<bundle-name>/`.
2. Add `extension.json` and the declared entrypoint file.
3. Verify discovery with `/extensions`.
4. Validate the bundle with `/extension-inspect <bundle-name>`.
5. Toggle it with `/extension-enable` or `/extension-disable` as needed.

For team sharing, commit the project extension folder into the repo so every
developer gets the same bundle through the workspace copy.

## Product surfaces

Extension state is now visible in all three major product views:

- live TUI session summaries
- saved session inspect and replay surfaces
- local slash-command inspection flows

This keeps local extension packaging aligned with the broader "lightweight
Claude Code" product direction: inspectable, local-first, and easy to replay.
