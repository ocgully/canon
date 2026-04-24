"""Schemas for the artifacts Canon authors.

A schema is a list of FieldSchema objects. The clarity-loop interview
engine walks them in declared order. Each field declares a prompt, a
required/optional flag, the clarity dimensions the evaluator should
score, and optional sub-fields for list-shaped answers.

All schemas are plain Python objects -- no YAML loader, no pydantic --
keeping the runtime stdlib-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


# Clarity dimensions. Each evaluator produces a score in [0, 1]; the
# field's composite is the min (weakest-link) of the selected dims.
CLARITY_DIMS = {
    "specificity",       # "slow" bad;  "< 500ms p99" good
    "testability",       # "should work" bad; "returns 200 on valid input" good
    "completeness",      # did every required sub-field get addressed?
    "consistency",       # contradicts earlier answer?
    "scope_clarity",     # in-scope vs out-of-scope clear?
    "goal_coverage",     # plan.approach must address each spec goal
}


@dataclass
class SubField:
    """One named field inside a list-element (e.g. each goal has a
    testable_statement)."""

    name: str
    prompt: str
    required: bool = True


@dataclass
class FieldSchema:
    """One clarity-interviewed field on an artifact."""

    name: str
    prompt: str
    required: bool = True
    clarity_dims: List[str] = field(default_factory=list)
    min_items: Optional[int] = None          # for list fields
    each: List[SubField] = field(default_factory=list)  # shape of each list-item
    threshold: float = 0.7                    # accept when score >= threshold
    required_if: Optional[Callable[[dict], bool]] = None
    help_text: str = ""

    def is_required(self, context: dict) -> bool:
        if self.required:
            return True
        if self.required_if and self.required_if(context):
            return True
        return False


@dataclass
class Schema:
    """A full artifact schema."""

    type: str                        # "spec" / "plan" / "north-star" / "constitution"
    fields: List[FieldSchema]
    description: str = ""
