---
description: Author a Canon spec via the clarity-loop interview (writes .pedia/specs/<N>-<slug>/spec.md)
argument-hint: <slug> [--from-north-star <ns-slug>]
---

The user wants to author a new Canon spec.

Run the Canon CLI in this project's working directory:

```bash
canon specify $ARGUMENTS
```

What this does:

1. Opens the **clarity-loop interview** — Canon asks structured questions about problem statement, goals, non-goals, success criteria, constraints, and citations. Vague answers trigger targeted follow-ups (specificity / testability / completeness / consistency / scope / goal-coverage).
2. Requires at least one **north-star or constitution citation** — pass `--from-north-star <slug>` to pre-seed, or pick interactively.
3. Writes `.pedia/specs/<N>-<slug>/spec.md` with structural front-matter (citations as `[[wiki-links]]`, `defines:` for any new terms).
4. Pedia indexes the new block automatically; `pedia check` should pass after.

Notes for this session:

- Canon is **offline-capable** — the interview runs against stdin by default. Ask the user clarifying questions yourself if running interactively in this Claude Code session, then forward the polished answers to the CLI subprocess via stdin.
- If no north-star exists yet, suggest `canon new --north-star <slug>` first; specs without a citation will be blocked.
- After completion, surface the resulting spec id (e.g. `001-cache-layer`) so the user can immediately follow up with `/canon-plan 001-cache-layer`.

Do NOT bypass the clarity-loop by hand-writing the spec.md — Canon's value is the structured-input discipline. The graph (citations + supersedes + spec-input) is the product.
