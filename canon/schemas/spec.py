"""Spec schema -- plan §3.1."""
from __future__ import annotations

from canon.schemas import FieldSchema, Schema, SubField


SPEC_SCHEMA = Schema(
    type="spec",
    description="Problem + goals + non-goals + success criteria + citations.",
    fields=[
        FieldSchema(
            name="problem_statement",
            prompt="What problem is this spec solving? Be concrete -- "
            "include the observable symptom and who feels it.",
            required=True,
            clarity_dims=["specificity", "testability"],
            help_text="Bad: 'it's slow'. Good: 'cold-start latency P99 "
            "exceeds 2s on M-tier laptops; affects first-run onboarding.'",
        ),
        FieldSchema(
            name="goals",
            prompt="List the goals of this spec -- one per line. "
            "Each must be a testable statement.",
            required=True,
            min_items=1,
            clarity_dims=["testability", "completeness"],
            each=[
                SubField(
                    name="testable_statement",
                    prompt="Testable statement for this goal",
                ),
            ],
            help_text="Bad: 'fast'. Good: 'cold-start P99 < 500ms on M-tier laptops.'",
        ),
        FieldSchema(
            name="non_goals",
            prompt="List what this spec explicitly does NOT do -- "
            "one per line. Forces scope discipline.",
            required=True,
            min_items=1,
            clarity_dims=["scope_clarity"],
        ),
        FieldSchema(
            name="success_criteria",
            prompt="How will we know this shipped? Each item becomes a "
            "UAT flag. One per line.",
            required=True,
            min_items=1,
            clarity_dims=["testability"],
        ),
        FieldSchema(
            name="constraints",
            prompt="Technical / perf / compliance constraints. "
            "One per line, or blank to skip.",
            required=False,
            clarity_dims=["specificity"],
        ),
        FieldSchema(
            name="related_work",
            prompt="Related Pedia blocks (wiki-links like "
            "[[specs/other-thing]]). Blank to skip.",
            required=False,
            help_text="Canon may auto-suggest via `pedia query` in later "
            "phases; phase 1A just captures what you type.",
        ),
        FieldSchema(
            name="north_star_citation",
            prompt="Which north-star does this spec cite? Enter the "
            "slug (e.g. 'agent-first-tooling').",
            required=True,
            # No clarity dims -- slugs are identifiers, not prose; the
            # clarity-loop would wrongly flag them as 'low specificity'.
            # Presence alone (non-empty) is enough.
            clarity_dims=[],
        ),
        FieldSchema(
            name="constitutional_citations",
            prompt="Constitution chapters this spec cites -- one slug "
            "per line. Blank if no constitution exists yet.",
            required=False,
            clarity_dims=[],
        ),
    ],
)
