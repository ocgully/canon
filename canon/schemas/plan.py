"""Plan schema -- plan §3.2."""
from __future__ import annotations

from canon.schemas import FieldSchema, Schema, SubField


PLAN_SCHEMA = Schema(
    type="plan",
    description="Approach + decomposition + risks for a spec.",
    fields=[
        FieldSchema(
            name="approach",
            prompt="High-level strategy. How does this address each "
            "of the spec's goals?",
            required=True,
            clarity_dims=["goal_coverage", "specificity"],
        ),
        FieldSchema(
            name="decomposition",
            prompt="Numbered steps of the implementation. One per "
            "line as 'SIZE: step' where SIZE in {XS,S,M,L}. "
            "Example: 'M: add SQLite cache layer behind feature flag'. "
            "Each step will become a task in phase 1B.",
            required=True,
            min_items=2,
            clarity_dims=["specificity", "completeness"],
            each=[
                SubField(name="step", prompt="Step description"),
                SubField(name="sizing", prompt="XS / S / M / L"),
            ],
        ),
        FieldSchema(
            name="dependencies",
            prompt="Systems / modules this plan depends on -- one "
            "per line. Blank to skip.",
            required=False,
        ),
        FieldSchema(
            name="risks",
            prompt="Risks + mitigations -- one per line as "
            "'RISK -> MITIGATION'.",
            required=True,
            min_items=1,
            clarity_dims=["specificity"],
            each=[
                SubField(name="risk", prompt="Risk"),
                SubField(name="mitigation", prompt="Mitigation"),
            ],
        ),
        FieldSchema(
            name="order_and_parallelism",
            prompt="DAG hints for the orchestrator. Example: "
            "'steps 1,2 serial; 3,4 parallel after 2'. Blank to skip.",
            required=False,
        ),
        FieldSchema(
            name="rollout_and_rollback",
            prompt="How does this ship safely? How do we roll back? "
            "(Required for user-facing specs; blank otherwise.)",
            required=False,
            clarity_dims=["specificity", "testability"],
        ),
        FieldSchema(
            name="open_questions",
            prompt="Open questions -- one per line. Each becomes a "
            "Hopewell 'open-question' node in phase 1B. Blank to skip.",
            required=False,
        ),
    ],
)
