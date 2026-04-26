"""Tests for canon.graph -- mermaid emission of the citation graph."""
from __future__ import annotations

from pathlib import Path

import pytest

from canon import graph as graph_mod

from tests.fixtures.lineage import build_lineage, deps_available
from tests.test_trace import _seed_cite_edges


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + taskflow required"
)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def test_build_full_includes_known_nodes(tmp_path: Path):
    build_lineage(tmp_path)
    g = graph_mod.build_full(tmp_path)
    paths = [n.raw_path for n in g.nodes.values() if n.raw_path]
    # All four expected docs show up (Pedia parses each into >=1 block;
    # we just need representation, not block count).
    assert any("north-stars/agent-first" in p for p in paths)
    assert any("constitution/technical" in p for p in paths)
    assert any("specs/001-cache-layer/spec.md" in p for p in paths)
    assert any("specs/001-cache-layer/plan.md" in p for p in paths)


def test_build_full_includes_cite_edges(tmp_path: Path):
    build_lineage(tmp_path)
    _seed_cite_edges(tmp_path)
    g = graph_mod.build_full(tmp_path)
    # At least one `cites` edge between the spec block and the
    # north-star block.
    kinds = {e.kind for e in g.edges}
    assert "cites" in kinds
    # Every edge must point to a known node.
    for e in g.edges:
        assert e.src in g.nodes
        assert e.dst in g.nodes


def test_build_neighborhood_scopes(tmp_path: Path):
    build_lineage(tmp_path)
    full = graph_mod.build_full(tmp_path)
    nbhd = graph_mod.build_neighborhood(tmp_path, "001-cache-layer", depth=1)
    # The neighborhood must be a subset of the full graph.
    assert set(nbhd.nodes).issubset(set(full.nodes))
    # At depth=1 we should still pick up the spec itself.
    assert any(
        n.raw_path and "specs/001-cache-layer/spec.md" in n.raw_path
        for n in nbhd.nodes.values()
    )


def test_build_neighborhood_unknown_id_returns_empty(tmp_path: Path):
    build_lineage(tmp_path)
    nbhd = graph_mod.build_neighborhood(tmp_path, "no-such-thing", depth=2)
    assert not nbhd.nodes


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_full_emits_mermaid_fence(tmp_path: Path):
    build_lineage(tmp_path)
    out = graph_mod.render_graph(tmp_path)
    assert out.startswith("```mermaid")
    assert "graph TD" in out
    assert out.rstrip().endswith("```")


def test_render_classifies_doc_types(tmp_path: Path):
    build_lineage(tmp_path)
    out = graph_mod.render_graph(tmp_path)
    # Class definitions are always emitted.
    assert "classDef ns" in out
    assert "classDef constitution" in out
    assert "classDef spec" in out
    assert "classDef plan" in out
    # At least one node should be tagged as each of the present types.
    assert ":::spec" in out
    assert ":::plan" in out
    assert ":::ns" in out
    assert ":::constitution" in out


def test_render_for_focus_writes_subset(tmp_path: Path):
    build_lineage(tmp_path)
    full = graph_mod.render_graph(tmp_path)
    focused = graph_mod.render_graph(tmp_path, focus="001-cache-layer", depth=1)
    # Both produce mermaid; focused should be no longer than the full
    # graph (often much shorter).
    assert focused.startswith("```mermaid")
    assert focused.count(":::") <= full.count(":::")


def test_render_empty_project_emits_placeholder(tmp_path: Path):
    # No lineage built; just make sure the function tolerates a missing index.
    (tmp_path / ".canon").mkdir()
    out = graph_mod.render_graph(tmp_path)
    assert "(no blocks indexed)" in out


def test_render_includes_supersedes_edge_after_amend(tmp_path: Path):
    """If the project has a supersedes edge (from canon.amend), the
    graph should render it with a dotted arrow, not a plain `cites`."""
    build_lineage(tmp_path)
    from canon import amend as amend_mod
    amend_mod.amend(
        tmp_path, "spec", "001-cache-layer",
        overrides={"problem_statement": "amended for graph test"},
    )
    out = graph_mod.render_graph(tmp_path)
    assert "-. supersedes .->" in out
