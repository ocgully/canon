---
description: Render Canon's full citation graph (or a subgraph) as JSON or mermaid
argument-hint: [--for <id>] [--format json|mermaid] [--include drift|orphans]
---

The user wants a graph view of Canon's citation network.

Run:

```bash
canon graph $ARGUMENTS
```

What this does:

- Default (no args): emits the full project graph — every north-star, constitution chapter, spec, plan, task, and the cites / supersedes / spec-input edges between them.
- `--for <id>`: scopes to the connected component containing `<id>`.
- `--format json` (default): typed JSON, suitable for piping into another tool.
- `--format mermaid`: emits a Mermaid diagram block — paste into a markdown file or GitHub PR description for a rendered view.
- `--include drift`: adds drift annotations on edges where a downstream artifact's `cites:` is stale relative to the upstream's `supersedes` chain.
- `--include orphans`: surfaces blocks with no incoming or outgoing citations (likely dead specs or never-cited north-stars).

This complements `canon trace` (single-id walk) with a holistic view. Useful before milestone planning or after merging multiple feature branches that touched the spec layer.

Like every Canon command, the graph is sourced from real Pedia blocks + TaskFlow nodes — there's no separate state file to drift.
