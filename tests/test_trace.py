"""Tests for canon.trace -- id resolution + walk wrapping + formatting."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from canon import trace as trace_mod

from tests.fixtures.lineage import build_lineage, deps_available


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + hopewell required"
)


def _seed_cite_edges(root: Path) -> None:
    """The lineage fixture ships wiki-links in `path` form which Pedia's
    auto-resolver classifies as ambiguous `term` lookups (no `defines:`
    is set on the targets). To exercise the trace/graph wrappers we
    seed the `cites` edges directly into the index -- mirroring what
    Pedia would have written if the wiki-link forms resolved.
    """
    from pedia import config as pcfg
    from pedia import index as idx
    conn = idx.connect(pcfg.db_path(root))
    try:
        def first_block_for(path: str) -> str:
            row = conn.execute(
                "SELECT id FROM blocks WHERE doc_path = ? "
                "ORDER BY line_start LIMIT 1",
                (path,),
            ).fetchone()
            return row["id"]

        spec_id = first_block_for("specs/001-cache-layer/spec.md")
        plan_id = first_block_for("specs/001-cache-layer/plan.md")
        ns_id = first_block_for("north-stars/agent-first.md")
        con_id = first_block_for("constitution/technical.md")
        edges = [
            (spec_id, ns_id, "cites"),
            (spec_id, con_id, "cites"),
            (plan_id, spec_id, "cites"),
        ]
        for src, dst, kind in edges:
            conn.execute(
                "INSERT OR IGNORE INTO refs(src_id, dst_id, kind) VALUES (?,?,?)",
                (src, dst, kind),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# id resolution
# ---------------------------------------------------------------------------


def test_resolve_spec_slug(tmp_path: Path):
    build_lineage(tmp_path)
    r = trace_mod.resolve(tmp_path, "001-cache-layer")
    assert r.kind == "pedia-block"
    assert r.pedia_id is not None
    assert r.doc_path == "specs/001-cache-layer/spec.md"


def test_resolve_north_star_slug(tmp_path: Path):
    build_lineage(tmp_path)
    r = trace_mod.resolve(tmp_path, "agent-first")
    assert r.kind == "pedia-block"
    assert r.doc_path == "north-stars/agent-first.md"


def test_resolve_hopewell_id(tmp_path: Path):
    build_lineage(tmp_path)
    r = trace_mod.resolve(tmp_path, "HW-0001")
    assert r.kind == "hopewell-task"
    assert r.task_id == "HW-0001"


def test_resolve_unknown(tmp_path: Path):
    build_lineage(tmp_path)
    r = trace_mod.resolve(tmp_path, "totally-not-a-slug")
    assert r.kind == "pedia-block"
    assert r.pedia_id is None


# ---------------------------------------------------------------------------
# pedia walk (up + down)
# ---------------------------------------------------------------------------


def test_trace_up_from_spec_finds_north_star(tmp_path: Path):
    build_lineage(tmp_path)
    _seed_cite_edges(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=5)
    assert tr.direction == "up"
    paths = [r.get("doc_path") for r in tr.pedia_walk]
    # The north-star should appear somewhere in the upstream walk.
    assert any(p and "north-stars/agent-first" in p for p in paths)
    # And the constitution chapter should also be reachable.
    assert any(p and "constitution/technical" in p for p in paths)


def test_trace_down_from_north_star_finds_spec(tmp_path: Path):
    build_lineage(tmp_path)
    _seed_cite_edges(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "agent-first", direction="down", depth=5)
    paths = [r.get("doc_path") for r in tr.pedia_walk]
    # The spec must reappear as a downstream consumer.
    assert any(p and "specs/001-cache-layer/spec.md" in p for p in paths)


def test_trace_depth_bounds_walk(tmp_path: Path):
    build_lineage(tmp_path)
    deep = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=5)
    shallow = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=0)
    assert len(shallow.pedia_walk) <= len(deep.pedia_walk)
    # depth=0 should still emit the seed row itself.
    assert shallow.pedia_walk
    assert shallow.pedia_walk[0]["depth"] == 0


def test_trace_marks_leaves(tmp_path: Path):
    build_lineage(tmp_path)
    _seed_cite_edges(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=5)
    # The north-star is a sink in the upstream direction (it cites
    # nothing) -- it should be marked leaf.
    ns_rows = [
        r for r in tr.pedia_walk
        if r.get("doc_path") and "north-stars/agent-first" in r["doc_path"]
    ]
    assert ns_rows
    assert all(r["leaf"] for r in ns_rows)


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------


def test_format_text_includes_header_and_blocks(tmp_path: Path):
    build_lineage(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=5)
    text = trace_mod.format_text(tr)
    assert "canon trace --up 001-cache-layer" in text
    assert "[block:" in text


def test_format_json_round_trip(tmp_path: Path):
    build_lineage(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=5)
    payload = json.loads(trace_mod.format_json(tr))
    assert payload["direction"] == "up"
    assert payload["root_id"] == "001-cache-layer"
    assert isinstance(payload["pedia_walk"], list)
    assert payload["pedia_walk"]


def test_format_mermaid_emits_valid_fence(tmp_path: Path):
    build_lineage(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=5)
    out = trace_mod.format_mermaid(tr)
    assert out.startswith("```mermaid")
    assert "graph TD" in out
    # Each block-id should appear as a node prefixed with `n_`.
    for r in tr.pedia_walk:
        assert f"n_{r['id']}" in out


def test_unknown_format_raises(tmp_path: Path):
    build_lineage(tmp_path)
    tr = trace_mod.run_trace(tmp_path, "001-cache-layer", direction="up", depth=1)
    with pytest.raises(ValueError):
        trace_mod.format_result(tr, "garbled")


def test_invalid_direction_raises(tmp_path: Path):
    build_lineage(tmp_path)
    with pytest.raises(ValueError):
        trace_mod.run_trace(tmp_path, "001-cache-layer", direction="sideways")
