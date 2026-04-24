"""Schema integrity tests."""
from __future__ import annotations

from canon.schemas import CLARITY_DIMS, FieldSchema, Schema
from canon.schemas.constitution import CONSTITUTION_SCHEMA
from canon.schemas.north_star import NORTH_STAR_SCHEMA
from canon.schemas.plan import PLAN_SCHEMA
from canon.schemas.spec import SPEC_SCHEMA


ALL = [SPEC_SCHEMA, PLAN_SCHEMA, NORTH_STAR_SCHEMA, CONSTITUTION_SCHEMA]


def test_schemas_are_nonempty():
    for s in ALL:
        assert s.type
        assert s.fields, f"{s.type} has no fields"


def test_all_clarity_dims_are_known():
    for s in ALL:
        for f in s.fields:
            for d in f.clarity_dims:
                assert d in CLARITY_DIMS, f"{s.type}.{f.name} has unknown dim {d}"


def test_spec_has_required_citation_field():
    names = [f.name for f in SPEC_SCHEMA.fields]
    assert "north_star_citation" in names
    assert "problem_statement" in names
    assert "goals" in names
    assert "non_goals" in names
    assert "success_criteria" in names


def test_plan_cites_spec_implicitly_via_decomposition_and_risks():
    names = [f.name for f in PLAN_SCHEMA.fields]
    assert "approach" in names
    assert "decomposition" in names
    assert "risks" in names


def test_required_fields_have_prompts():
    for s in ALL:
        for f in s.fields:
            assert f.prompt.strip(), f"{s.type}.{f.name} missing prompt"


def test_min_items_only_on_list_fields():
    # sanity: all min_items schemas make sense (>=1)
    for s in ALL:
        for f in s.fields:
            if f.min_items is not None:
                assert f.min_items >= 1
