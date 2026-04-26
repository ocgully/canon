# canon-vscode

Minimal VS Code surface for [Canon](https://github.com/ocgully/canon) — the SDD discipline tool that buries SpecKit.

This is a thin wrapper around the `canon` CLI. Every command shells out
to a project-installed `canon` executable; the extension contains zero
domain logic of its own. That keeps the VS Code surface, the Claude Code
slash commands, and the bare CLI behaviorally identical.

## Phase 1D status

- Bundled with the Canon repo at `canon/plugin/vscode/`
- **Manual sideload only** — not yet published to the VS Code Marketplace
- Five commands wired:
  - `Canon: Specify` — prompts for a slug, runs `canon specify` in a terminal
  - `Canon: Plan` — prompts for a spec id, runs `canon plan`
  - `Canon: Derive Tasks` — runs `canon tasks <spec-id>`
  - `Canon: Check` — runs `canon check`, streams output into a dedicated channel
  - `Canon: Trace Citations` — runs `canon trace`, opens result as a markdown preview

Phase-2 work (HW-0057 follow-up): tree-view of the `.pedia/specs/`
directory, inline clarity-loop diagnostics from the language server,
and a Marketplace publication.

## Prerequisites

- VS Code 1.80 or later
- Python 3.10+ with Canon installed:

  ```bash
  pip install canon
  # or, for the TaskFlow-aware tasks command:
  pip install 'canon[taskflow]'
  ```

- The `canon` executable on `PATH`. If it lives elsewhere, set
  `canon.executable` in your VS Code settings.

## Sideload (development)

From the repo root:

```bash
cd canon/plugin/vscode
npm install --no-save @types/vscode    # only needed if you edit extension.js
npx --yes vsce package                 # produces canon-vscode-0.1.0.vsix
code --install-extension canon-vscode-0.1.0.vsix
```

Reload VS Code. The commands are then available from the command
palette (`Cmd/Ctrl+Shift+P`) under the **Canon:** category.

## Future: Flotilla install

Once the Flotilla plugin marketplace lands (HW-0051), the recommended
install path will be:

```bash
flotilla install canon
```

That command will (a) `pip install canon`, (b) drop the slash commands
into `~/.claude/commands/`, and (c) sideload this VS Code extension —
all from a single registry entry. See `canon-plan.md` §10 (consumer
surface) for the full integration sketch.

## Configuration

| Setting           | Default | Description                                              |
| ----------------- | ------- | -------------------------------------------------------- |
| `canon.executable` | `canon` | Path to the `canon` CLI. Override if not on `PATH`.      |
