"""North-star schema. Short, pithy, universal."""
from __future__ import annotations

from canon.schemas import FieldSchema, Schema


NORTH_STAR_SCHEMA = Schema(
    type="north-star",
    description="Medium-term directional statement. Universal-context.",
    fields=[
        FieldSchema(
            name="title",
            prompt="North-star title (one line).",
            required=True,
            # Title is a label; presence alone is enough.
            clarity_dims=[],
        ),
        FieldSchema(
            name="framing",
            prompt="One-sentence framing. Sharp and testable.",
            required=True,
            clarity_dims=["specificity", "testability"],
        ),
        FieldSchema(
            name="horizon",
            prompt="3-5 year horizon statement. Where do we want to be?",
            required=True,
            clarity_dims=["specificity"],
        ),
        FieldSchema(
            name="rationale",
            prompt="Why is this the right north-star for this project?",
            required=True,
            clarity_dims=["specificity"],
        ),
    ],
)
