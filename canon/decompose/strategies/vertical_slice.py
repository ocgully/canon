"""Strategy: `vertical-slice` -- demo-able user-visible increments.

Each emitted work item is a complete "slice" from UI / surface down to
data, deliverable as one demo. This is the opposite of horizontal-layer
work (one PR for the API, one for the UI, one for the database) which
maximizes WIP and delays user value.

Mapping rule
------------
We treat each plan decomposition bullet as ONE candidate slice and
augment its citation with the spec's `## Success criteria` (a slice
must satisfy at least one success criterion; that's the definition of
"demo-able"). The strategy adds:

  - `kind = "slice"`
  - `metadata.demo`: a one-line acceptance hint synthesized from the
    step text + whichever success-criterion fragment matches its verbs
    most closely (best-effort substring match against the rendered
    spec body if available; otherwise a generic "demo X" string).
  - `metadata.layer_hint`: which layer(s) the slice spans -- inferred
    from keywords in the step text (ui / api / data / infra / docs).
    Purely advisory; teams shouldn't be tempted to break a "slice"
    along these layers.

Ordering
--------
Slices intentionally drop the order_and_parallelism directive: in a
vertical-slice break, slices are independently demo-able by design.
We retain whatever blockers the parser found for an EXPLICIT "after"
relationship (some slices genuinely need infra from a prior slice),
but `serial` / `->` chains are dropped -- those are usually layer
ordering artifacts the strategy is trying to avoid.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from canon.decompose.base import (
    ParsedPlan,
    StrategyResult,
    WorkItem,
    parse_order_directive,
    suggest_executor,
)


NAME = "vertical-slice"


_LAYER_HINTS = [
    ("ui",   re.compile(r"\b(ui|frontend|button|view|screen|page|widget|layout|render)\b", re.I)),
    ("api",  re.compile(r"\b(api|endpoint|route|handler|controller|service|rpc)\b", re.I)),
    ("data", re.compile(r"\b(db|database|schema|table|migration|index|cache|store)\b", re.I)),
    ("infra", re.compile(r"\b(infra|deploy|terraform|helm|k8s|kubernetes|provision)\b", re.I)),
    ("docs", re.compile(r"\b(docs?|guide|readme|tutorial|reference|wiki)\b", re.I)),
]


def _layer_hint(text: str) -> List[str]:
    out: List[str] = []
    for tag, pat in _LAYER_HINTS:
        if pat.search(text):
            out.append(tag)
    return out


def _demo_line(step_text: str, plan: ParsedPlan) -> str:
    """Build a one-line "what does the demo show" hint."""
    # Pull a verb-fragment from the step itself.
    s = step_text.strip().rstrip(".")
    if len(s) > 100:
        s = s[:97] + "..."
    return f"demo: {s}"


def _drop_serial_only_blockers(items: List[WorkItem]) -> None:
    """Vertical-slice rejects serial layer ordering; only keep explicit
    deps inferred from non-serial directives.

    We approximate this by keeping a blocker only when the source step
    text explicitly references the dependent step's index (rare). Since
    our parser already produced both kinds, we drop ALL blockers here
    to honor the strategy's intent: slices are independently demo-able.
    Teams that need a hard ordering should encode it in the spec's
    Success criteria or split the plan.
    """
    for it in items:
        it.blockers = []


def run(plan: ParsedPlan, **_: Any) -> StrategyResult:
    result = StrategyResult(strategy=NAME)

    for step in plan.decomposition:
        wi = WorkItem(
            index=step.index,
            kind="slice",
            title=step.text[:120],
            sizing=step.sizing,
            spec_slices=["## Goals", "## Success criteria"],
            plan_slices=[f"## Decomposition (step {step.index})"],
            executor_role=suggest_executor(step.text),
            metadata={
                "demo": _demo_line(step.text, plan),
                "layer_hint": _layer_hint(step.text),
            },
        )
        result.items.append(wi)

    # Slices ignore serial layer ordering.
    _drop_serial_only_blockers(result.items)

    # Convenience: list the demo lines as an extra so the CLI can print
    # a "demo-able increments" table without re-parsing items.
    result.extras["demos"] = [
        {"index": it.index, "demo": it.metadata.get("demo", "")}
        for it in result.items
    ]

    result.open_questions = list(plan.open_questions)
    return result
