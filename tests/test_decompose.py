"""Tests for the new `canon decompose` surface (HW-0065 / 0.5.0).

Covers:
  - Each strategy emits the expected work-item shape against the
    `001-cache-layer` lineage fixture.
  - The resolver picks strategies in the right priority (cli ->
    front-matter -> config -> smart-default).
  - End-to-end: `canon decompose` materializes Hopewell nodes carrying
    the correct `canon` marker for every strategy.
  - The deprecated `canon tasks` alias still works and forwards to the
    `tasks` strategy.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pytest

from canon.decompose.base import parse_plan
from canon.decompose.dispatch import (
    DecomposeResult,
    cmd_decompose,
    cmd_tasks_alias,
    run_strategy,
)
from canon.decompose.resolver import (
    KNOWN_STRATEGIES,
    resolve_strategy,
)
from canon.decompose.strategies import REGISTRY

from tests.fixtures.lineage import build_lineage, deps_available


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + hopewell required"
)


# ---------------------------------------------------------------------------
# Strategies (unit) -- shape of StrategyResult against the canned plan
# ---------------------------------------------------------------------------


def _load_canned_plan(tmp_path: Path):
    build_lineage(tmp_path)
    return parse_plan(
        tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md"
    )


def test_strategy_tasks_emits_linear_items_with_blockers(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    sresult = REGISTRY["tasks"].run(plan)
    assert sresult.strategy == "tasks"
    assert len(sresult.items) == 3
    assert all(it.kind == "task" for it in sresult.items)
    # The plan's "2 after 1; 3 after 1" directive => 2 + 3 blocked by 1.
    by_idx = {it.index: it for it in sresult.items}
    assert by_idx[2].blockers == [1]
    assert by_idx[3].blockers == [1]
    assert by_idx[1].blockers == []
    # Open questions surface separately.
    assert sresult.open_questions == ["should the cache persist across sessions?"]


def test_strategy_flow_assigns_waves_and_parallel_with(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    sresult = REGISTRY["flow"].run(plan)
    assert sresult.strategy == "flow"
    by_idx = {it.index: it for it in sresult.items}
    # Item 1 is the root -> wave 0.
    assert by_idx[1].wave == 0
    # Items 2 + 3 both blocked by 1 -> wave 1, parallel with each other.
    assert by_idx[2].wave == 1
    assert by_idx[3].wave == 1
    assert sorted(by_idx[2].parallel_with) == [3]
    assert sorted(by_idx[3].parallel_with) == [2]
    assert by_idx[1].parallel_with == []  # alone in wave 0
    # Strategy extras carry the wave grouping.
    waves = sresult.extras["waves"]
    assert waves["0"] == [1]
    assert waves["1"] == [2, 3]


def test_strategy_vertical_slice_drops_serial_blockers(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    sresult = REGISTRY["vertical-slice"].run(plan)
    assert sresult.strategy == "vertical-slice"
    assert len(sresult.items) == 3
    assert all(it.kind == "slice" for it in sresult.items)
    # Vertical-slice intentionally removes ordering; every slice is independent.
    for it in sresult.items:
        assert it.blockers == [], f"slice {it.index} should have no blockers"
    # Each slice carries a demo hint.
    for it in sresult.items:
        assert "demo" in it.metadata
        assert it.metadata["demo"].startswith("demo:")
    # Extras list the demos for CLI rendering.
    assert len(sresult.extras["demos"]) == 3


def test_strategy_spike_build_inserts_research_first(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    sresult = REGISTRY["spike-build"].run(plan)
    assert sresult.strategy == "spike-build"
    # 1 spike + 3 build = 4 items.
    assert len(sresult.items) == 4
    spike = sresult.items[0]
    assert spike.kind == "spike"
    assert spike.index == 1
    # The spike folds in open questions.
    assert spike.metadata["questions_to_resolve"] == [
        "should the cache persist across sessions?"
    ]
    # Build items follow at indexes 2..4 and ALL blocked by the spike.
    for build in sresult.items[1:]:
        assert build.kind == "build"
        assert 1 in build.blockers
    # Build item 3 (originally step 2) keeps its "after step 1" -> shifted to
    # "after build-2" (index 2 in the new numbering). Item 4 (originally
    # step 3) similarly blocked by build-2.
    by_idx = {it.index: it for it in sresult.items}
    assert 2 in by_idx[3].blockers   # original "2 after 1" -> 3 after 2
    assert 2 in by_idx[4].blockers   # original "3 after 1" -> 4 after 2
    # Open-question nodes are NOT surfaced separately under spike-build.
    assert sresult.open_questions == []


def test_strategy_story_map_creates_epic_activity_story_hierarchy(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    sresult = REGISTRY["story-map"].run(plan)
    assert sresult.strategy == "story-map"
    epics = [it for it in sresult.items if it.kind == "epic"]
    activities = [it for it in sresult.items if it.kind == "activity"]
    stories = [it for it in sresult.items if it.kind == "story"]
    assert len(epics) == 1
    assert len(activities) >= 1
    assert len(stories) == 3   # one per decomposition step
    # Epic blocks every activity (well, activities depend on the epic).
    for a in activities:
        assert 1 in a.blockers
    # Stories all have a parent activity.
    for s in stories:
        assert s.metadata["parent_index"] in {a.index for a in activities}
    # Extras render the backbone for the CLI.
    assert "activities" in sresult.extras


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_resolver_cli_flag_wins_over_everything(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    # Even if config + front-matter say otherwise, --strategy wins.
    plan.front_matter["strategy"] = "story-map"
    from canon import config as cfg_mod
    cfg_mod.set_key(tmp_path, "decompose.strategy", "flow")
    name, source = resolve_strategy("vertical-slice", plan, tmp_path, cwd=tmp_path)
    assert (name, source) == ("vertical-slice", "cli")


def test_resolver_front_matter_wins_over_config(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    plan.front_matter["strategy"] = "spike-build"
    from canon import config as cfg_mod
    cfg_mod.set_key(tmp_path, "decompose.strategy", "flow")
    name, source = resolve_strategy(None, plan, tmp_path, cwd=tmp_path)
    assert (name, source) == ("spike-build", "front-matter")


def test_resolver_config_wins_over_smart_default(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    plan.front_matter.pop("strategy", None)
    from canon import config as cfg_mod
    cfg_mod.set_key(tmp_path, "decompose.strategy", "story-map")
    name, source = resolve_strategy(None, plan, tmp_path, cwd=tmp_path)
    assert (name, source) == ("story-map", "config")


def test_resolver_smart_default_picks_flow_when_both_present(tmp_path: Path):
    # build_lineage gives us BOTH .pedia/ and .hopewell/ at tmp_path.
    plan = _load_canned_plan(tmp_path)
    plan.front_matter.pop("strategy", None)
    name, source = resolve_strategy(None, plan, tmp_path, cwd=tmp_path)
    assert (name, source) == ("flow", "smart-default")


def test_resolver_smart_default_picks_tasks_without_hopewell(tmp_path: Path):
    # Bare directory: no .hopewell/, no .pedia/.
    bare = tmp_path / "bare"
    bare.mkdir()
    name, source = resolve_strategy(None, None, None, cwd=bare)
    assert (name, source) == ("tasks", "smart-default")


def test_resolver_rejects_unknown_strategy_loudly():
    with pytest.raises(ValueError):
        resolve_strategy("not-a-real-thing", None, None)


# ---------------------------------------------------------------------------
# Dispatch -- end-to-end against a Hopewell project
# ---------------------------------------------------------------------------


def test_run_strategy_materializes_tasks_into_hopewell(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    result, name, source = run_strategy(
        root=tmp_path, plan=plan, cli_strategy="tasks",
    )
    assert name == "tasks"
    assert source == "cli"
    assert len(result.created) == 3
    # The plan's "2 after 1; 3 after 1" -> 2 edges.
    assert len(result.edges) == 2
    # Idempotency: re-run skips everything.
    result2, _, _ = run_strategy(
        root=tmp_path, plan=plan, cli_strategy="tasks",
    )
    assert result2.created == []
    # 3 work items + 1 open question = 4 skipped.
    assert len(result2.skipped) == 4


@pytest.mark.parametrize("strategy", list(KNOWN_STRATEGIES))
def test_run_strategy_against_every_strategy(tmp_path: Path, strategy: str):
    plan = _load_canned_plan(tmp_path)
    result, name, _ = run_strategy(
        root=tmp_path, plan=plan, cli_strategy=strategy,
    )
    assert name == strategy
    # Every strategy creates AT LEAST one node.
    assert len(result.created) >= 1
    # The created nodes carry the right strategy marker.
    from hopewell import project as hw_project
    project = hw_project.Project.load(start=tmp_path)
    for nid in result.created:
        node = project.node(nid)
        canon_meta = node.component_data.get("canon", {})
        assert canon_meta.get("strategy") == strategy
        assert canon_meta.get("spec_slug") == "001-cache-layer"


def test_dry_run_does_not_persist(tmp_path: Path):
    plan = _load_canned_plan(tmp_path)
    result, name, _ = run_strategy(
        root=tmp_path, plan=plan, cli_strategy="flow", dry_run=True,
    )
    assert all("dry-run" in s for s in result.created)
    # The Hopewell project should still be empty.
    from hopewell import project as hw_project
    project = hw_project.Project.load(start=tmp_path)
    assert project.all_nodes() == []


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def _run_cli(monkeypatch, tmp_path: Path, argv: list[str]) -> tuple[int, str, str]:
    """Helper: chdir into tmp_path and invoke `canon` with argv."""
    from canon import cli
    monkeypatch.chdir(tmp_path)
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out_buf)
    monkeypatch.setattr(sys, "stderr", err_buf)
    rc = cli.main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def test_cli_decompose_each_strategy(tmp_path: Path, monkeypatch):
    build_lineage(tmp_path)
    for strategy in KNOWN_STRATEGIES:
        rc, out, err = _run_cli(
            monkeypatch, tmp_path,
            ["decompose", "001-cache-layer", "--strategy", strategy, "--json"],
        )
        # Every strategy completes cleanly on the canned plan.
        assert rc == 0, f"strategy={strategy}: rc={rc}, err={err}"
        # JSON shape includes the strategy + at least one created id.
        import json as _json
        payload = _json.loads(out)
        assert payload["strategy"] == strategy


def test_cli_tasks_alias_warns_and_forwards(tmp_path: Path, monkeypatch):
    build_lineage(tmp_path)
    rc, out, err = _run_cli(
        monkeypatch, tmp_path, ["tasks", "001-cache-layer"],
    )
    assert rc == 0
    # The deprecation warning lands on stderr.
    assert "deprecated" in err.lower()
    # Output looks like the decompose summary, not nothing.
    assert "canon decompose" in out


def test_amend_regenerate_with_strategy(tmp_path: Path):
    """`canon amend plan --regenerate --strategy flow` should swap in the
    flow strategy's work items (in addition to any tasks-strategy items
    already present)."""
    build_lineage(tmp_path)
    # First, materialize the tasks strategy.
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")
    run_strategy(root=tmp_path, plan=plan, cli_strategy="tasks")

    # Now regenerate with the flow strategy.
    from canon import amend as amend_mod
    result = amend_mod.amend(
        tmp_path, "plan", "001-cache-layer",
        regenerate=True, strategy="flow",
    )
    assert result["regenerated"] is True
    assert result["strategy"] == "flow"
    # Flow items have a different (slug, strategy, index) key than tasks
    # items, so they should all be created fresh.
    assert len(result["result"].created) == 3


def test_amend_regenerate_rejects_non_plan_doc(tmp_path: Path):
    build_lineage(tmp_path)
    from canon import amend as amend_mod
    with pytest.raises(ValueError):
        amend_mod.amend(
            tmp_path, "spec", "001-cache-layer",
            regenerate=True, strategy="flow",
        )
