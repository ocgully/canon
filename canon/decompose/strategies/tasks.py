"""Strategy: `tasks` -- linear ordered task list with deps.

This is the original phase-1B behavior: each decomposition bullet
becomes one work item; order/parallelism directives become `blocks`
edges between them. Best for solo / small change scope.
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


NAME = "tasks"


def run(plan: ParsedPlan, **_: Any) -> StrategyResult:
    """Emit one work item per decomposition step + ordering blockers."""
    result = StrategyResult(strategy=NAME)

    # 1:1 mapping -- step.index becomes the WorkItem.index
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

    # Ordering edges: (blocker_index, blocked_index)
    edges = parse_order_directive(plan.order_directive)
    by_idx = {it.index: it for it in result.items}
    for (blocker, blocked) in edges:
        if blocker in by_idx and blocked in by_idx:
            tgt = by_idx[blocked]
            if blocker not in tgt.blockers:
                tgt.blockers.append(blocker)

    result.open_questions = list(plan.open_questions)
    return result
