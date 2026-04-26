"""Tests for canon.tasks -- plan parsing, executor heuristics, ordering,
derive_tasks against a real TaskFlow project.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from canon.tasks import (
    parse_plan,
    derive_tasks,
    suggest_executor,
    parse_order_directive,
    sizing_estimate,
)
from tests.fixtures.lineage import build_lineage, deps_available


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + taskflow required"
)


def test_parse_plan_extracts_decomposition_and_open_questions(tmp_path: Path):
    build_lineage(tmp_path)
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")
    assert plan.spec_slug == "001-cache-layer"
    assert len(plan.decomposition) == 3
    sizes = [s.sizing for s in plan.decomposition]
    assert sizes == ["M", "S", "M"]
    assert "scaffold cache module" in plan.decomposition[0].text
    assert plan.open_questions == ["should the cache persist across sessions?"]
    assert "after" in plan.order_directive


def test_suggest_executor_classifies_step_text():
    assert suggest_executor("scaffold cache module returning 200") == "agent"
    assert suggest_executor("deploy the new service to prod") == "service"
    assert suggest_executor("review + sign off on the migration plan") == "gate"


def test_parse_order_directive_extracts_after_pairs():
    edges = parse_order_directive("2 after 1; 3 after 1")
    assert (1, 2) in edges
    assert (1, 3) in edges


def test_parse_order_directive_handles_arrows():
    edges = parse_order_directive("1 -> 2 -> 3")
    assert (1, 2) in edges
    assert (2, 3) in edges


def test_sizing_estimate_maps_sizes_to_hours():
    assert sizing_estimate("M") == {"size": "M", "estimate_hours": 16}
    assert sizing_estimate("XS") == {"size": "XS", "estimate_hours": 1}
    assert sizing_estimate("XXL") is None
    assert sizing_estimate(None) is None


def test_derive_tasks_creates_nodes_with_spec_input(tmp_path: Path):
    build_lineage(tmp_path)
    from taskflow import project as hw_project
    project = hw_project.Project.load(start=tmp_path)
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")

    result = derive_tasks(project, plan)
    assert len(result.created) == 3
    assert len(result.open_questions) == 1
    # ordering: 1 blocks 2, 1 blocks 3
    assert len(result.edges) == 2

    # Inspect the first created node.
    n = project.node(result.created[0])
    assert "spec-input" in n.component_data
    cited_paths = [s["path"] for s in n.component_data["spec-input"]["specs"]]
    assert "specs/001-cache-layer/spec.md" in cited_paths
    assert "specs/001-cache-layer/plan.md" in cited_paths

    # Sizing metadata.
    assert n.component_data["sizing"]["size"] == "M"

    # Executor suggestion.
    assert n.component_data["executor-suggestion"]["role"] == "agent"

    # Canon idempotency marker.
    assert n.component_data["canon"]["spec_slug"] == "001-cache-layer"
    assert n.component_data["canon"]["plan_step_index"] == 1


def test_derive_tasks_is_idempotent(tmp_path: Path):
    build_lineage(tmp_path)
    from taskflow import project as hw_project
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")

    project = hw_project.Project.load(start=tmp_path)
    first = derive_tasks(project, plan)
    assert len(first.created) == 3
    assert len(first.open_questions) == 1

    # Re-run on a freshly loaded project.
    project2 = hw_project.Project.load(start=tmp_path)
    second = derive_tasks(project2, plan)
    assert second.created == []         # nothing new
    assert second.open_questions == []  # nothing new
    assert len(second.skipped) == 4     # the 3 task nodes + 1 OQ node


def test_dry_run_does_not_persist(tmp_path: Path):
    build_lineage(tmp_path)
    from taskflow import project as hw_project
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")

    project = hw_project.Project.load(start=tmp_path)
    result = derive_tasks(project, plan, dry_run=True)
    assert all("dry-run" in s for s in result.created)
    # No nodes actually created.
    project2 = hw_project.Project.load(start=tmp_path)
    assert project2.all_nodes() == []
