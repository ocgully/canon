---
description: Author a Canon plan for an existing spec via clarity-loop (writes .pedia/specs/<spec-id>/plan.md)
argument-hint: <spec-id>
---

The user wants to author a Canon plan derived from an existing spec.

Run:

```bash
canon plan $ARGUMENTS
```

What this does:

1. Loads `.pedia/specs/<spec-id>/spec.md` and uses its goals as the **goal-coverage** target for the clarity-loop.
2. Walks the user through: approach, decomposition sketch, dependencies (auto-suggested via CodeAtlas if present), risks + mitigations, implementation order / parallelism hints, rollout + rollback (required for user-facing specs), open questions.
3. Each open question becomes a TaskFlow node tagged `open-question` (if TaskFlow is installed).
4. Writes `.pedia/specs/<spec-id>/plan.md` with structural citations back to spec blocks. Plan front-matter `cites:` includes the spec by block id.

Notes:

- `<spec-id>` looks like `001-cache-layer` — the directory name under `.pedia/specs/`.
- The clarity-loop's `goal_coverage` dimension fires if the approach doesn't address every goal in the spec; expect targeted follow-ups.
- After completion, the natural next step is `/canon-decompose <spec-id> [--strategy <name>]` to break the plan into work items. Pick a strategy that matches your shape (tasks / flow / vertical-slice / spike-build / story-map); the default is smart-detected from `.taskflow/` (or legacy `.hopewell/`) + `.pedia/` presence.

Cite-everything is enforced — a plan without a spec citation is blocked.
