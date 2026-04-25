"""Strategy: `spike-build` -- emit a research spike, then build items.

Best for high-uncertainty work: rather than committing to a full
decomposition up front, we land a single time-boxed `spike` work item
that produces a written outcome (technical findings + go/no-go
recommendation), and queue the planned build items as
spike-blocked. The build items keep their ordering relative to each
other but ALL are blocked by the spike's completion.

Sizing rules
------------
- The spike is sized "S" by default (capped 4h timebox). If the user
  explicitly sized step #1 of the plan as "M" or "L", we forward that
  instead -- the user signal wins.
- Build items keep their original sizing.

Spike content
-------------
The spike's title is synthesized from the spec slug + the first
decomposition step. Its `metadata.spike_outcome` lists the questions
the spike is meant to answer (drawn from `## Open questions` PLUS the
spec's `## Constraints` headings).

Open questions become spike content
-----------------------------------
This is the strategy's distinctive behavior: open questions don't
become separate "open question" nodes (that's the `tasks` default).
Instead they're folded INTO the spike as questions to resolve. If
there are no open questions, we still emit a spike (the bare fact
"this is uncertain enough to warrant spike-build" carries weight).
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


NAME = "spike-build"


def _spike_title(plan: ParsedPlan) -> str:
    return f"spike: clarify approach for {plan.spec_slug}"[:120]


def run(plan: ParsedPlan, **_: Any) -> StrategyResult:
    result = StrategyResult(strategy=NAME)

    # Start indexing at 1; the spike is index 1, build items follow.
    spike = WorkItem(
        index=1,
        kind="spike",
        title=_spike_title(plan),
        sizing="S",  # default timebox; user can override later
        spec_slices=["## Problem statement", "## Constraints"],
        plan_slices=["## Approach", "## Open questions"],
        executor_role="agent",
        priority="P1",
        metadata={
            "timebox_hours": 4,
            "spike_outcome": (
                "Written findings + go/no-go recommendation. "
                "Resolve open questions; identify tooling/library choices; "
                "surface unknowns that should re-shape the plan."
            ),
            "questions_to_resolve": list(plan.open_questions),
        },
    )
    # User sizing override: if step 1 was M/L, escalate spike timebox.
    if plan.decomposition and plan.decomposition[0].sizing in {"M", "L"}:
        spike.sizing = plan.decomposition[0].sizing
        spike.metadata["timebox_hours"] = (
            16 if spike.sizing == "M" else 40
        )
    result.items.append(spike)

    # Build items: shifted by +1 since spike took index 1.
    edge_pairs = parse_order_directive(plan.order_directive)
    shift = 1  # add to every original step index to land in the new numbering
    for step in plan.decomposition:
        new_idx = step.index + shift
        bi = WorkItem(
            index=new_idx,
            kind="build",
            title=step.text[:120],
            sizing=step.sizing,
            spec_slices=["## Goals", "## Success criteria"],
            plan_slices=[f"## Decomposition (step {step.index})"],
            executor_role=suggest_executor(step.text),
            blockers=[1],  # ALL build items are blocked by the spike
        )
        result.items.append(bi)

    # Apply original ordering between build items (with index shift).
    by_idx = {it.index: it for it in result.items}
    for (blocker, blocked) in edge_pairs:
        b1 = blocker + shift
        b2 = blocked + shift
        if b1 in by_idx and b2 in by_idx:
            tgt = by_idx[b2]
            if b1 not in tgt.blockers:
                tgt.blockers.append(b1)

    # Open questions are folded into the spike, not surfaced as tasks.
    result.open_questions = []  # intentional; questions live on the spike
    result.extras["spike_questions"] = list(plan.open_questions)
    return result
