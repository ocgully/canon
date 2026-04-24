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

**Deferred** (phase 1B+): `canon tasks`, `canon implement`, `canon check`, `canon amend`, `canon trace`, `canon graph`, VS Code extension.

## Install

```bash
pip install pedia canon        # pedia is a runtime dep
# optional, for phase-1B task derivation:
pip install 'canon[hopewell]'
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

Canon stores nothing of its own beyond `.canon/config.yaml`. Every authored artifact is a Pedia block. Phase 1B adds Hopewell nodes for tasks.

## Development

```bash
git clone https://github.com/ocgully/canon
cd canon
pip install -e .
pytest
```

## License

Apache-2.0
