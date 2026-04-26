---
description: Walk Canon's citation graph up or down from any spec / plan / task / north-star id
argument-hint: <id> [--up | --down] [--depth N]
---

The user wants to trace Canon's citation graph from a given artifact.

Run:

```bash
canon trace $ARGUMENTS
```

What this does:

- `--up` (default): walks parent citations — task → plan → spec → constitution / north-star.
- `--down`: walks children — north-star → specs that cite it → plans → TaskFlow tasks → implementations.
- `--depth N`: bounds traversal (default 5).

The output is a JSON tree (or pretty-printed tree if stdout is a TTY) where every edge is a structural citation, never a filename convention.

Typical uses:

- Before refactoring a north-star: `canon trace agent-first-tooling --down` shows everything that would drift.
- Investigating a TaskFlow ticket: `canon trace HW-0042 --up` walks back to the spec, plan, and constitutional principles that motivated it.
- Drift audit: `canon trace <spec-id>` (no direction) shows both up and down.

This is the answer to SpecKit's "traceability is sibling-filename convention" weakness — Canon's traces are walks across a real typed graph (Pedia blocks + TaskFlow nodes + cites/supersedes/spec-input edges).
