"""Strategy: `flow` -- Hopewell-shaped flow network.

Emits typed work items + `blocks` edges + parallel waves, optimized for
the Hopewell `flow.push` runtime (push-to-inbox semantics; see
`hopewell/flow.py`). Each item carries:

  - `wave`: integer (0-based) -- items in the same wave can run in
    parallel; items in wave N depend on at least one item in wave <N.
  - `parallel_with`: indexes of sibling items in the same wave (handy
    for UIs rendering swim-lanes).

When the surrounding project has `.hopewell/` initialized, the
dispatch layer materializes these items as Hopewell nodes and writes
real `blocks` edges into the graph. When Hopewell is absent (e.g.
`canon decompose --strategy flow` in a bare repo), the dispatch layer
falls back to plain JSON output that preserves the same shape.

Wave assignment: longest-blocking-path topological levels. Items with
no blockers land in wave 0. Item X lands in wave (max(wave[blocker])+1).
Cycles aren't expected (the parser produces a DAG); if one slips
through we cap at len(items) waves to avoid infinite recursion.
"""
from __future__ import annotations

from typing import Any, Dict, List

from canon.decompose.base import (
    ParsedPlan,
    StrategyResult,
    WorkItem,
    parse_order_directive,
    suggest_executor,
)


NAME = "flow"


def _assign_waves(items: List[WorkItem]) -> None:
    """Mutate `items` in place: set `.wave` via topological levels."""
    by_idx = {it.index: it for it in items}
    cap = len(items) + 1  # safety cap on cycle traversal

    # Iteratively raise waves until stable.
    for _ in range(cap):
        changed = False
        for it in items:
            if not it.blockers:
                if it.wave != 0:
                    it.wave = 0
                    changed = True
                continue
            blocker_waves = [
                by_idx[b].wave for b in it.blockers
                if b in by_idx and by_idx[b].wave is not None
            ]
            if not blocker_waves:
                # Blocker hasn't been scheduled yet; pin to 1 and revisit.
                if it.wave is None:
                    it.wave = 1
                    changed = True
                continue
            target = max(blocker_waves) + 1
            if it.wave != target:
                it.wave = target
                changed = True
        if not changed:
            break

    # Final pass: anything still None goes to wave 0 (defensive).
    for it in items:
        if it.wave is None:
            it.wave = 0


def _populate_parallel_with(items: List[WorkItem]) -> None:
    """For each item, list the indexes of OTHER items in the same wave."""
    by_wave: Dict[int, List[int]] = {}
    for it in items:
        by_wave.setdefault(it.wave or 0, []).append(it.index)
    for it in items:
        siblings = by_wave.get(it.wave or 0, [])
        it.parallel_with = [i for i in siblings if i != it.index]


def run(plan: ParsedPlan, **_: Any) -> StrategyResult:
    result = StrategyResult(strategy=NAME)

    for step in plan.decomposition:
        wi = WorkItem(
            index=step.index,
            kind="task",
            title=step.text[:120],
            sizing=step.sizing,
            spec_slices=["## Goals", "## Non-goals", "## Success criteria"],
            plan_slices=[f"## Decomposition (step {step.index})"],
            executor_role=suggest_executor(step.text),
        )
        result.items.append(wi)

    # Apply blockers from the plan's order directive.
    edges = parse_order_directive(plan.order_directive)
    by_idx = {it.index: it for it in result.items}
    for (blocker, blocked) in edges:
        if blocker in by_idx and blocked in by_idx:
            tgt = by_idx[blocked]
            if blocker not in tgt.blockers:
                tgt.blockers.append(blocker)

    # Now the wave structure.
    _assign_waves(result.items)
    _populate_parallel_with(result.items)

    # Strategy extras: a wave-keyed dict, oldest wave first.
    waves: Dict[int, List[int]] = {}
    for it in result.items:
        waves.setdefault(it.wave or 0, []).append(it.index)
    result.extras["waves"] = {
        str(w): sorted(idxs) for w, idxs in sorted(waves.items())
    }

    result.open_questions = list(plan.open_questions)
    return result
