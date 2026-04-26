"""Strategy: `story-map` -- epic -> activity -> task hierarchy.

Each plan decomposition step is treated as a `story` (a leaf user-task
in story-map terminology). They're grouped into `activity` rows
("backbone activities") that span the user journey, and a single
`epic` work item sits above the whole thing.

Activity grouping
-----------------
We do a best-effort clustering by leading verb / noun-phrase:

  - Steps starting with similar verbs (e.g. "scaffold", "wire", "add")
    cluster into the same activity.
  - When that fails (mixed verbs), we fall back to "activity 1" =
    setup / scaffold steps, "activity 2" = wire-up steps, "activity 3"
    = polish / metrics / docs steps.

When the plan front-matter declares `story_map.activities:` as a list,
we use that verbatim instead and assign each story to the activity
whose name appears in the story text (case-insensitive). Stories that
match nothing land in an "uncategorized" activity.

Output shape
------------
The result is FLAT (a list of WorkItems) but every item has a
`metadata.row` (epic / activity / story) and `metadata.parent_index`.
The dispatch layer encodes parent links as TaskFlow `requires` edges
and the row tag in component_data so the UI can re-build the map.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from canon.decompose.base import (
    ParsedPlan,
    StrategyResult,
    WorkItem,
    suggest_executor,
)


NAME = "story-map"


# Heuristic verb buckets for fallback activity grouping.
_BUCKETS: List[Tuple[str, re.Pattern]] = [
    ("setup",   re.compile(r"^\s*(scaffold|init|set\s*up|create|bootstrap|provision)\b", re.I)),
    ("wire",    re.compile(r"^\s*(wire|integrate|hook|connect|link|bind|expose)\b", re.I)),
    ("build",   re.compile(r"^\s*(build|implement|write|add|render|generate|emit)\b", re.I)),
    ("polish",  re.compile(r"^\s*(metric|measure|polish|tune|optimize|cache|refactor)\b", re.I)),
    ("docs",    re.compile(r"^\s*(document|doc|guide|readme|tutorial|reference)\b", re.I)),
]


def _bucket_for(text: str) -> str:
    for tag, pat in _BUCKETS:
        if pat.search(text):
            return tag
    return "build"  # default bucket -- most steps are build work


def _activities_from_front_matter(plan: ParsedPlan) -> Optional[List[str]]:
    fm = plan.front_matter or {}
    sm = fm.get("story_map")
    if isinstance(sm, dict):
        acts = sm.get("activities")
        if isinstance(acts, list):
            return [str(a).strip() for a in acts if str(a).strip()]
        if isinstance(acts, str):
            return [a.strip() for a in acts.split(",") if a.strip()]
    return None


def _assign_to_declared_activities(
    plan: ParsedPlan, activities: List[str]
) -> Dict[int, str]:
    """For each step.index, return the activity name it best matches."""
    by_step: Dict[int, str] = {}
    lowered = [(a, a.lower()) for a in activities]
    for step in plan.decomposition:
        text = step.text.lower()
        chosen = None
        for orig, low in lowered:
            if low and low in text:
                chosen = orig
                break
        by_step[step.index] = chosen or "uncategorized"
    return by_step


def run(plan: ParsedPlan, **_: Any) -> StrategyResult:
    result = StrategyResult(strategy=NAME)

    # 1. Epic node (always index 1).
    epic = WorkItem(
        index=1,
        kind="epic",
        title=f"epic: {plan.spec_slug}",
        sizing=None,
        spec_slices=["## Goals", "## Success criteria"],
        plan_slices=["## Approach"],
        executor_role="gate",   # epics are usually owned by a coordinator
        priority="P1",
        metadata={"row": "epic", "parent_index": None},
    )
    result.items.append(epic)

    # 2. Activities: declared OR clustered.
    declared = _activities_from_front_matter(plan)
    if declared:
        activities = declared
        step_to_activity_name = _assign_to_declared_activities(plan, declared)
    else:
        # Cluster by bucket; preserve first-occurrence order.
        seen: List[str] = []
        step_to_bucket: Dict[int, str] = {}
        for step in plan.decomposition:
            b = _bucket_for(step.text)
            step_to_bucket[step.index] = b
            if b not in seen:
                seen.append(b)
        activities = seen
        step_to_activity_name = step_to_bucket

    # Materialize one activity work item per name; track index by name.
    activity_index_by_name: Dict[str, int] = {}
    next_idx = 2
    for name in activities:
        ai = WorkItem(
            index=next_idx,
            kind="activity",
            title=f"activity: {name}",
            sizing=None,
            spec_slices=[],
            plan_slices=["## Decomposition"],
            executor_role="agent",
            priority="P2",
            blockers=[1],   # activities depend on the epic existing
            metadata={"row": "activity", "parent_index": 1, "name": name},
        )
        result.items.append(ai)
        activity_index_by_name[name] = next_idx
        next_idx += 1

    # 3. Stories: one per decomposition step, parented under its activity.
    for step in plan.decomposition:
        act_name = step_to_activity_name.get(step.index, "uncategorized")
        # Lazily create an "uncategorized" activity if anyone landed there.
        if act_name not in activity_index_by_name:
            ai = WorkItem(
                index=next_idx,
                kind="activity",
                title="activity: uncategorized",
                sizing=None,
                spec_slices=[],
                plan_slices=["## Decomposition"],
                executor_role="agent",
                priority="P3",
                blockers=[1],
                metadata={"row": "activity", "parent_index": 1, "name": act_name},
            )
            result.items.append(ai)
            activity_index_by_name[act_name] = next_idx
            next_idx += 1

        parent_idx = activity_index_by_name[act_name]
        story = WorkItem(
            index=next_idx,
            kind="story",
            title=step.text[:120],
            sizing=step.sizing,
            spec_slices=["## Goals", "## Success criteria"],
            plan_slices=[f"## Decomposition (step {step.index})"],
            executor_role=suggest_executor(step.text),
            blockers=[parent_idx],
            metadata={"row": "story", "parent_index": parent_idx,
                      "activity_name": act_name},
        )
        result.items.append(story)
        next_idx += 1

    # Strategy extras: render the backbone for the CLI.
    result.extras["activities"] = [
        {"index": activity_index_by_name[name], "name": name}
        for name in activity_index_by_name
    ]
    result.open_questions = list(plan.open_questions)
    return result
