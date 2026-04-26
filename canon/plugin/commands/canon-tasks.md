---
description: "[DEPRECATED] Alias for /canon-decompose --strategy tasks. Use /canon-decompose instead."
argument-hint: <spec-id>
---

The user invoked the legacy slash command. `canon tasks` was renamed to
`canon decompose` in 0.5.0; the original behavior is now one of five
selectable strategies. This alias preserves prior behavior verbatim and
will be removed in a future major release.

Run:

```bash
canon decompose $ARGUMENTS --strategy tasks
```

What this does:

1. Loads `.pedia/specs/<spec-id>/plan.md` and parses its decomposition.
2. Forces the `tasks` strategy (linear ordered work items with deps),
   skipping the resolver chain.
3. Materializes each work item as a TaskFlow node with `spec-input`,
   `executor-suggestion`, `sizing`, and a `canon` marker.

Prefer `/canon-decompose <spec-id> [--strategy <name>]` going forward.
See `/canon-decompose` for the full strategy catalog.

Requires:

- `pip install canon`.
- `.taskflow/` (or legacy `.hopewell/`) initialized in the project.
