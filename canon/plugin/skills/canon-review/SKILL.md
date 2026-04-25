---
name: canon-review
description: "[Phase 2 — RESERVED] Review an in-progress Canon spec against existing Pedia content for conflicts, synergies, and gaps. Not yet implemented."
---

# canon-review — phase 2 placeholder

This skill namespace is **reserved** for the phase-2 spec-quality assistant
described in `patterns/drafts/canon-plan.md` §11 ("Spec-quality assistant").

## Why this file exists now (phase 1D)

Reserving the skill name in the plugin layout so:

1. Phase-1 users who try `/canon-review` get a clear "not yet" message
   instead of a missing-skill error.
2. The Flotilla manifest (HW-0051) can list `canon-review` as a planned
   capability without breaking on a missing file.
3. Phase-2 work can drop in a real implementation under the same
   namespace without renaming.

## What phase 2 will do

When implemented, this skill will:

- Take an in-progress Canon spec / plan as input (spec-id or path).
- Query Pedia for related blocks (`pedia query` over the spec's slug,
  goal terms, defined terms).
- Flag, with citations:
  - **Conflicts** — existing blocks that contradict the new spec's
    constraints, non-goals, or success criteria.
  - **Synergies** — existing blocks that solve adjacent problems and
    could be cited or composed.
  - **Gaps** — referenced concepts that have no Pedia block yet and
    should be authored before this spec is finalized.
- Surface the report as a structured markdown block the user can paste
  into the spec's `## related work` section, with citations as
  `[[wiki-links]]` so Pedia indexes them.

## When phase 2 lands

Tracking ticket: **HW-0057 follow-up** (filed as a child of the Canon
phase-1 epic once 1D ships).

Until then, this skill intentionally does nothing. If Claude Code
invokes it, respond with:

> The `canon-review` skill is reserved for Canon phase 2. See
> `canon/plugin/skills/canon-review/SKILL.md` and `canon-plan.md` §11.
> For now, run `pedia query <terms>` manually to surface related blocks
> and cite them in your spec.
