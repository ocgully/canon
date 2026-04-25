# canon

> **The SDD discipline tool. Buries SpecKit.**

Canon is the fifth sibling in the agent-infrastructure family:

| Tool | Owns |
|---|---|
| [mercator](https://github.com/ocgully/mercator) | code structure (layered codemap) |
| [hopewell](https://github.com/ocgully/Hopewell) | work ledger (typed node graph) |
| [pedia](https://github.com/ocgully/pedia) | knowledge / specs / context store |
| [sextant](https://github.com/ocgully/sextant) | review / navigation surface |
| **canon** | **authoring discipline -- spec, plan, task, implement, cite-everything** |

## Why bury SpecKit?

SpecKit shipped good ideas (`/specify` -> `/plan` -> `/tasks` -> `/implement`) but the seams are fragile:

- Specs are plain markdown; no semantic structure beyond convention
- Traceability is sibling-filename convention
- Each phase re-prompts the LLM for context it already "knew"
- Tasks aren't linked to specs structurally
- Drift isn't detected
- LLM-chat authoring is nondeterministic
- Universal context is not a concept

Canon replaces SpecKit's slash-command surface with a **disciplined, citation-anchored, clarity-loop-interviewed** workflow that sits on top of **Pedia** (knowledge) + **Hopewell** (work). Every artifact Canon writes is a first-class Pedia block with structural citations.

## What phase 1A ships

- `canon init` -- scaffold `.canon/config.yaml`, verify Pedia
- `canon new --north-star <slug>` / `canon new --constitution <chapter>`
- `canon specify <slug>` -- clarity-loop interviewed; writes `.pedia/specs/<N>-<slug>/spec.md`
- `canon plan <spec-id>` -- clarity-loop interviewed; writes `.pedia/specs/<N>-<slug>/plan.md`
- `canon config {get|set|list}`
- The clarity-loop evaluator (rules-first; regex heuristics for specificity, testability, completeness, consistency, scope, goal-coverage)
- Offline-capable: stdin-only by default; agent-runner integration (`--agent claude` etc.) is a subprocess hand-off, never an embedded chat client

## What phase 1B adds

- `canon decompose <spec-id> [--strategy <name>]` -- breaks a plan into
  work items via a selectable strategy (see the strategies table below).
  Generates Hopewell nodes from the plan's `## Decomposition` block;
  auto-populates each item's `spec-input` citations, sizing metadata,
  executor suggestion, and a `canon` marker for idempotent re-runs.
  Renamed from `canon tasks` in 0.5.0; the old name still works as a
  deprecated alias.
- `canon implement <task-id>` -- assembles a context bundle (cited spec
  slices + universal-context blocks + Mercator dump if present) and
  pushes the work item via `flow.push`. Targets `@orchestrator` when
  the flow network declares one; otherwise falls back to a direct
  dispatch to the item's suggested executor.
- `canon check [--strict] [--format=json]` -- citation completeness
  validator. Errors block (exit 1); warnings advisory (exit 2 only
  under `--strict`). Catches missing citations, orphan items/plans,
  broken `spec-input` paths, and step-index drift.

### Decompose strategies (0.5.0)

| Strategy         | When to use                                                                        |
| ---------------- | ---------------------------------------------------------------------------------- |
| `tasks`          | Default for solo / small change. Linear ordered list with deps. (Original 1B.)     |
| `flow`           | Hopewell-shaped network: parallel waves + `blocks` edges. Best for hand-offs.      |
| `vertical-slice` | Each item is a demo-able user-visible increment. No horizontal layer breaks.       |
| `spike-build`    | High-uncertainty: spike research item first, build items follow + are spike-blocked. |
| `story-map`      | Epic -> activity -> story hierarchy along the user journey.                        |

Strategy resolution chain (first match wins):

1. CLI flag: `canon decompose --strategy flow`
2. Plan front-matter: `strategy: flow`
3. Repo config: `.canon/config.yaml` -> `decompose.strategy: flow`
4. Smart fallback: if `.hopewell/` AND `.pedia/` are present in the repo
   tree -> `flow`; else -> `tasks`.

Use `canon amend plan <spec-id> --regenerate --strategy <name>` to swap
strategies on an existing plan. Plain `canon amend` (no `--regenerate`)
preserves the current strategy and only patches text.

## What phase 1C adds -- provenance + history

- `canon amend <type> <id>` -- runs an INCREMENTAL clarity-loop
  interview against an existing block, pre-seeded with each field's
  current value. The user `<enter>`s to keep a value verbatim, types
  delta to augment, or `accept` to commit a partial. Writes a NEW
  block with `supersedes:` front-matter pointing at the prior
  block-id; the old block stays queryable but is flagged
  `superseded_by:`. The full prior text is stashed in a sidecar
  `.amended-history` file so forensic review never loses the original
  wording. Pedia's `refs` table gets an explicit `supersedes` edge so
  `canon trace` + `canon graph` render the supersession. When a spec
  or plan is amended and Hopewell is present, Canon runs `hopewell
  spec-ref drift --all` and surfaces the output -- per HW-0034.

  ```bash
  canon amend spec 001-cache-layer
  canon amend plan 001-cache-layer
  canon amend ns agent-first-tooling          # 'ns' aliases 'north-star'
  canon amend constitution technical
  canon amend spec 001-cache-layer --dry-run  # preview without writing
  ```

- `canon trace <id> --up | --down [--depth N] [--format text|json|mermaid]`
  -- walks the citation graph. `--up` follows what `<id>` cites
  (transitively); `--down` follows what cites `<id>`. Resolves the
  identifier as a Pedia block-id, a spec slug, a north-star slug, or
  a Hopewell task-id. Pedia walks via `pedia.trace.walk`; Hopewell
  task walks compose a node-edge BFS with the cited plan-block walk.
  Leaves (no further edges in the requested direction) get a `[leaf]`
  marker so orphan / uncited entities are obvious.

  ```bash
  canon trace 001-cache-layer --up
  canon trace agent-first-tooling --down --format mermaid
  canon trace HW-0001 --depth 2 --format json
  ```

- `canon graph [--for <id>] [--depth N] [--out PATH]` -- emits a
  Mermaid diagram of the project's citation graph. Node colors track
  doc-type (north-star, constitution, spec, plan, decision, task);
  edge styles distinguish `cites` (solid arrow), `supersedes` (dotted
  arrow), `requires` / `blocks` (Hopewell overlay). `--for <id>`
  scopes to the depth-N neighborhood of that block. Renders natively
  in GitHub, VS Code, and Obsidian.

  ```bash
  canon graph                                       # full project
  canon graph --for spec/001-cache-layer --depth 3 --out graph.mmd
  ```

## Install

```bash
pip install pedia hopewell canon
```

## Quick start

```bash
cd /your/project
pedia init                     # if .pedia/ doesn't exist
canon init

# optional: author the north-star you'll cite from every spec
canon new --north-star agent-first-tooling

# optional: author a constitution chapter
canon new --constitution technical

# author a spec (the clarity-loop asks follow-ups if answers are vague)
canon specify cache-layer --from-north-star agent-first-tooling

# author its plan
canon plan 001-cache-layer

# break the plan into Hopewell work items (pick a strategy or auto-detect)
canon decompose 001-cache-layer                  # auto-detect strategy
canon decompose 001-cache-layer --strategy flow  # parallel-wave flow network
hopewell list                    # the new work items show up here

# verify the citation chain
canon check                      # exit 0 if clean
canon check --strict             # exit 2 on warnings too

# dispatch a task (routes via @orchestrator if network has one)
canon implement HW-0001
hopewell flow where HW-0001      # see where it landed

# refresh + verify with Pedia
pedia refresh
pedia check
pedia query "cache layer"
```

The files land at:

```
.pedia/
  north-stars/agent-first-tooling.md
  constitution/technical.md
  specs/001-cache-layer/
    spec.md            <- front-matter cites the north-star + constitution
    plan.md            <- front-matter cites spec.md
```

## The clarity-loop

Every field in every interview gets scored against its declared clarity dimensions:

- **specificity** -- "slow" -> low; "P99 < 500ms" -> high
- **testability** -- "should work" -> low; "returns 200" -> high
- **completeness** -- did every sub-field get addressed?
- **consistency** -- does this contradict an earlier answer?
- **scope_clarity** -- in-scope vs out-of-scope clear?
- **goal_coverage** -- (plan.approach) addresses every spec goal?

Below threshold (default 0.7) -> Canon composes a targeted follow-up, waits for augmented detail, re-scores. After `MAX_ITER` (default 5) Canon accepts-as-is and stamps the partial score onto the block's front-matter so downstream tools can see where the weak spots are.

Tunable via `canon config set clarity.threshold 0.8` etc.

## Agent-runner integration (phase 1A)

If you pass `--agent claude`:

1. Canon runs the rules-based clarity pass first
2. If a field fails to commit after MAX_ITER, Canon writes `.canon/interview-context/<session>/context.md` with the schema, current answers, and the gap list
3. Canon invokes the `claude` binary as a subprocess with that context file
4. The agent session refines the answer and returns it on stdout
5. Canon substitutes verbatim

If the binary isn't on PATH, Canon tells you where the context file was written and continues with the rules-only answer. **Canon never embeds a chat client.** (Same pattern as Sextant §6.5.)

## Storage

Canon stores nothing of its own beyond `.canon/config.yaml` and
dispatch bundles under `.canon/dispatches/<HW-id>.md` (one per
`canon implement` invocation). Every authored artifact is a Pedia
block; every task is a Hopewell node with `component_data["spec-input"]`
populated by `canon decompose`.

## Plugin installation (phase 1D)

Canon ships an optional surface layer for the two environments most agent
work happens in: Claude Code and VS Code. Both wrappers shell out to the
same `canon` CLI — they add no behavior of their own.

### Claude Code slash commands

Five commands are bundled under `canon/plugin/commands/`:

| Command           | What it does                                                     |
| ----------------- | ---------------------------------------------------------------- |
| `/canon-specify` | Authors a spec via the clarity-loop interview                    |
| `/canon-plan`    | Authors a plan from an existing spec                             |
| `/canon-decompose` | Breaks a plan into work items via a selectable strategy (0.5.0+) |
| `/canon-tasks`   | [DEPRECATED] alias for `/canon-decompose --strategy tasks`       |
| `/canon-trace`   | Walks the citation graph up or down from any id (phase 1C)       |
| `/canon-graph`   | Renders the full citation graph as JSON or mermaid (phase 1C)    |

Install (per-user):

```bash
mkdir -p ~/.claude/commands
cp -r canon/plugin/commands/* ~/.claude/commands/
```

Then `/canon-specify <slug>` becomes available in any Claude Code session.

A phase-2 skill placeholder lives at
`canon/plugin/skills/canon-review/SKILL.md` — it reserves the namespace
for the spec-quality assistant described in `canon-plan.md` §11. It
intentionally does nothing yet.

### VS Code extension

A minimal extension lives at `canon/plugin/vscode/`. It contributes five
commands under the **Canon:** category (Specify, Plan, Derive Tasks,
Check, Trace Citations). Sideload locally:

```bash
cd canon/plugin/vscode
npx --yes vsce package
code --install-extension canon-vscode-0.1.0.vsix
```

The extension uses the `canon` CLI on `PATH`; override via the
`canon.executable` setting if needed. Marketplace publication is
deferred to a later phase.

### Future: one-shot install via Flotilla

Once the Flotilla plugin marketplace lands (HW-0051), the recommended
install path will be `flotilla install canon`, which will (a)
`pip install canon`, (b) drop the slash commands into `~/.claude/commands/`,
and (c) sideload the VS Code extension — all from a single registry
entry. Until then, the manual steps above are the supported path.

## Development

```bash
git clone https://github.com/ocgully/canon
cd canon
pip install -e .
pytest
```

## License

Apache-2.0
