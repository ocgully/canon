---
description: Decompose a Canon plan into work items via a selectable strategy (tasks / flow / vertical-slice / spike-build / story-map)
argument-hint: <spec-id> [--strategy <name>]
---

The user wants to break a finalized Canon plan into work items.

Run:

```bash
canon decompose $ARGUMENTS
```

What this does:

1. Loads `.pedia/specs/<spec-id>/plan.md` and parses its `## Decomposition` block.
2. Resolves a strategy from (in order):
   - `--strategy <name>` flag,
   - the plan's front-matter (`strategy: <name>`),
   - `.canon/config.yaml` (`decompose.strategy: <name>`),
   - smart fallback: `flow` when `.hopewell/` AND `.pedia/` are present, else `tasks`.
3. Runs the strategy and -- when a Hopewell project is present -- materializes
   each work item as a Hopewell node with:
   - `spec-input` auto-populated (spec slices + plan slice the item derives from),
   - `executor-suggestion` (agent / service / gate, advisory),
   - `sizing` metadata when the bullet declared XS/S/M/L,
   - `canon` marker carrying `{spec_slug, strategy, strategy_index, kind, ...}`,
   - `wave` / `parallel_with` for the `flow` strategy.
4. Adds `blocks` edges per the strategy's ordering (or per the plan's
   `## Order + parallelism` directive when the strategy honors it).
5. Open questions become their own work items (except in `spike-build`,
   where they fold into the spike's `metadata.questions_to_resolve`).

Strategies available:

| Name             | When to use                                                     |
| ---------------- | --------------------------------------------------------------- |
| `tasks`          | Default for solo / small change. Linear ordered list with deps. |
| `flow`           | Hopewell-shaped network with parallel waves. Best when handing  |
|                  | items off across executors (agents / services / gates).         |
| `vertical-slice` | Each item is a demo-able user-visible increment (no horizontal  |
|                  | layer breaks). Drops serial layer ordering.                     |
| `spike-build`    | High-uncertainty work: emits a research spike first, build      |
|                  | items follow + are blocked by the spike.                        |
| `story-map`      | epic -> activity -> story hierarchy along the user journey.     |

Requires:

- `pip install canon` (canon ships with hopewell as a runtime dep).
- `.hopewell/` initialized in the project (run `hopewell init` once).

After this step, run `hopewell ready` (NOT `ls .hopewell/`) to see what's
available to pick up, or `/canon-implement <work-item-id>` to dispatch via
the orchestrator.

Re-running `canon decompose` is idempotent: items already created for
this (spec, strategy) pair are skipped.
