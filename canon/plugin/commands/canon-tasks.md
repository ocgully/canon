---
description: Derive Hopewell tasks from a Canon plan's decomposition sketch (each task gets spec-input citations)
argument-hint: <spec-id>
---

The user wants to derive Hopewell tasks from a finalized Canon plan.

Run:

```bash
canon tasks $ARGUMENTS
```

What this does:

1. Loads `.pedia/specs/<spec-id>/plan.md` and parses its decomposition sketch.
2. For each bullet, creates a Hopewell node with:
   - `hopewell new --components work-item --title "<plan bullet>"`
   - `spec-input` component_data auto-populated:
     - `specs[0].path = specs/<spec-id>/spec.md` + extracted block slices the task derives from
     - `specs[1].path = specs/<spec-id>/plan.md` + the proposing plan block
3. Adds Hopewell `blocks` edges matching the plan's order/parallelism hints.
4. The narrow interview at this phase asks for: task sizing (XS/S/M/L), suggested executor component, and any spec-slice citations the heuristic couldn't determine.

Requires:

- The `canon[hopewell]` extra installed (`pip install 'canon[hopewell]'`).
- `.hopewell/` initialized in the project.

After this step, the user can run `hopewell ready` (NOT `ls .hopewell/`) to see what's available to pick up, or `/canon-implement <task-id>` to dispatch via the orchestrator.

Tasks without spec-input citations are blocked — Canon refuses to create orphan tickets.
