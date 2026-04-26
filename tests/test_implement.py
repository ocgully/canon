"""Tests for canon.implement -- bundle assembly + dispatch."""
from __future__ import annotations

from pathlib import Path

import pytest

from canon.implement import (
    has_orchestrator,
    assemble_bundle,
    _direct_target,
    ORCHESTRATOR_EXECUTOR_ID,
)
from canon.tasks import parse_plan, derive_tasks
from tests.fixtures.lineage import build_lineage, deps_available


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + taskflow required"
)


def _bootstrap_default_network(tmp_path: Path):
    """Equivalent to `taskflow network defaults bootstrap`."""
    from taskflow import network as hw_network
    from taskflow import network_defaults as hw_defaults
    hw_network.ensure_network_dir(tmp_path)
    hw_defaults.write_default_template(tmp_path)


def _make_project_with_tasks(tmp_path: Path):
    build_lineage(tmp_path)
    from taskflow import project as hw_project
    project = hw_project.Project.load(start=tmp_path)
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")
    derive_tasks(project, plan)
    return hw_project.Project.load(start=tmp_path)


def test_has_orchestrator_false_without_network(tmp_path: Path):
    project = _make_project_with_tasks(tmp_path)
    assert has_orchestrator(project) is False


def test_has_orchestrator_true_after_default_template(tmp_path: Path):
    project = _make_project_with_tasks(tmp_path)
    _bootstrap_default_network(tmp_path)
    from taskflow import project as hw_project
    project2 = hw_project.Project.load(start=tmp_path)
    # TaskFlow's default template includes @orchestrator.
    assert has_orchestrator(project2) is True


def test_assemble_bundle_writes_dispatch_file(tmp_path: Path):
    project = _make_project_with_tasks(tmp_path)
    node = project.all_nodes()[0]

    bundle = assemble_bundle(
        project, node, root=tmp_path,
        via_orchestrator=False, target_executor="agent",
    )
    assert bundle.bundle_path is not None
    assert bundle.bundle_path.exists()
    body = bundle.bundle_path.read_text(encoding="utf-8")
    # Bundle includes citations + universal context. Path separator
    # varies by platform; check pieces independently.
    assert "Universal context:" in body
    assert "agent-first.md" in body
    assert "technical.md" in body
    assert "Cited block:" in body
    assert node.id in body


def test_direct_target_uses_executor_suggestion_when_present(tmp_path: Path):
    project = _make_project_with_tasks(tmp_path)
    _bootstrap_default_network(tmp_path)
    from taskflow import project as hw_project
    project = hw_project.Project.load(start=tmp_path)

    node = project.all_nodes()[0]
    # The executor-suggestion is "agent" -- if "agent" is in the network,
    # it should win; else the first sorted executor is used.
    target = _direct_target(project, node)
    assert target is not None
    from taskflow import network as hw_network
    net = hw_network.load_network(tmp_path)
    if "agent" in net.executors:
        assert target == "agent"
    else:
        assert target in net.executors


def test_direct_target_returns_none_with_empty_network(tmp_path: Path):
    project = _make_project_with_tasks(tmp_path)
    node = project.all_nodes()[0]
    # No network bootstrapped at all.
    assert _direct_target(project, node) is None
