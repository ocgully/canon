"""Constitution-chapter schema. Universal context."""
from __future__ import annotations

from canon.schemas import FieldSchema, Schema


CONSTITUTION_SCHEMA = Schema(
    type="constitution",
    description="A constitutional chapter -- an inviolable project principle.",
    fields=[
        FieldSchema(
            name="chapter",
            prompt="Chapter name (e.g. 'technical', 'product', 'ethics').",
            required=True,
            # Chapter is a label.
            clarity_dims=[],
        ),
        FieldSchema(
            name="principles",
            prompt="Principles -- one per line. Each MUST be stated "
            "as 'we WILL X' or 'we will NEVER X' -- not wishes.",
            required=True,
            min_items=1,
            clarity_dims=["specificity", "testability"],
        ),
        FieldSchema(
            name="rationale",
            prompt="Why do these principles apply? What's the cost of "
            "violating them?",
            required=True,
            clarity_dims=["specificity"],
        ),
    ],
)
