"""Back-compat shim for canon.tasks (deprecated since 0.5.0).

The real implementation lives in `canon.decompose` (HW-0065 split out
the original "tasks"-only behavior into one of five selectable
strategies). This module re-exports the names downstream code depends
on so existing imports keep working unchanged:

    from canon.tasks import parse_plan, derive_tasks, suggest_executor,
                            parse_order_directive, sizing_estimate,
                            ParsedPlan, DecompStep, TasksResult

A future major release will remove this shim. New code should import
directly from `canon.decompose`.
"""
from __future__ import annotations

from typing import Any

from canon.decompose.base import (  # noqa: F401
    DecompStep,
    ParsedPlan,
    SIZING_HOURS,
    parse_order_directive,
    parse_plan,
    sizing_estimate,
    suggest_executor,
)
from canon.decompose.dispatch import (  # noqa: F401
    DecomposeResult,
    TasksResult,         # alias of DecomposeResult, retained for back-compat
    cmd_tasks_alias as cmd_tasks,
)


def derive_tasks(project, plan: ParsedPlan, *, dry_run: bool = False) -> TasksResult:
    """Run the `tasks` strategy + materialize into a Hopewell project.

    Pre-0.5.0 callers use this signature. Internally we now route via
    the strategy registry so behavior matches `canon decompose --strategy tasks`.
    """
    from canon.decompose.dispatch import run_strategy

    # plan.path = <root>/.pedia/specs/<slug>/plan.md  -> 4 parents up = root
    root = plan.plan_path.parents[3]
    result, _, _ = run_strategy(
        root=root,
        plan=plan,
        cli_strategy="tasks",
        dry_run=dry_run,
        project=project,
    )
    return result
