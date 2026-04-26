"""Tests for canon.amend -- prior-block resolution, supersedes edges,
amendment-history section, drift surfacing.

Uses the same lineage fixture 1B's tests use; substrate is the
``001-cache-layer`` spec/plan pair.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from canon import amend as amend_mod
from canon import pedia_bridge as pb

from tests.fixtures.lineage import build_lineage, deps_available


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + taskflow required"
)


# ---------------------------------------------------------------------------
# prior-block loading
# ---------------------------------------------------------------------------


def test_load_prior_spec_recovers_fields(tmp_path: Path):
    build_lineage(tmp_path)
    prior = amend_mod.load_prior(tmp_path, "spec", "001-cache-layer")
    assert prior.doc_type == "spec"
    assert prior.slug == "001-cache-layer"
    assert prior.path.exists()
    # Field recovery: rendered bullets flatten to one line per item.
    assert "cold-start P99" in prior.fields["problem_statement"]
    assert "cold-start P99 < 500ms on M-tier laptop" in prior.fields["goals"]
    # Citations come from front-matter, not body sections.
    assert prior.fields["north_star_citation"] == "agent-first"
    assert "technical" in prior.fields["constitutional_citations"]


def test_load_prior_plan_recovers_decomposition(tmp_path: Path):
    build_lineage(tmp_path)
    prior = amend_mod.load_prior(tmp_path, "plan", "001-cache-layer")
    assert prior.doc_type == "plan"
    assert "LRU cache" in prior.fields["approach"]
    assert "scaffold cache module" in prior.fields["decomposition"]


def test_load_prior_alias_ns(tmp_path: Path):
    build_lineage(tmp_path)
    prior = amend_mod.load_prior(tmp_path, "ns", "agent-first")
    assert prior.doc_type == "north-star"
    assert prior.slug == "agent-first"


def test_load_prior_missing_raises(tmp_path: Path):
    build_lineage(tmp_path)
    with pytest.raises(FileNotFoundError):
        amend_mod.load_prior(tmp_path, "spec", "no-such-spec")


# ---------------------------------------------------------------------------
# end-to-end amend
# ---------------------------------------------------------------------------


def test_amend_spec_supersedes_and_writes_history(tmp_path: Path):
    build_lineage(tmp_path)

    # Capture the prior block-id so we can assert it ends up as the
    # supersedes edge target.
    prior = amend_mod.load_prior(tmp_path, "spec", "001-cache-layer")
    prior_block_id = prior.block_id
    assert prior_block_id is not None

    overrides = {
        # Tighten the problem statement; the rest stays.
        "problem_statement": (
            "cold-start P99 latency reaches 2400ms on M-tier laptops; "
            "users abandon onboarding before the tool returns 200 -- "
            "amended after recent measurements"
        ),
    }
    result = amend_mod.amend(
        tmp_path, "spec", "001-cache-layer",
        overrides=overrides, max_iter=5,
    )

    # 1. New file is in place + history sidecar exists.
    assert result["dry_run"] is False
    new_path = Path(result["new_path"])
    history_path = Path(result["history_path"])
    assert new_path.exists()
    assert history_path.exists()
    assert "prior block id" in history_path.read_text(encoding="utf-8")

    # 2. New body has an Amendment history section.
    body = new_path.read_text(encoding="utf-8")
    assert "## Amendment history" in body
    # And carries the new problem statement.
    assert "2400ms" in body

    # 3. Pedia got refreshed + the new block-id is computable.
    new_block_id = result["new_block_id"]
    assert new_block_id is not None
    assert new_block_id != prior_block_id

    # 4. The supersedes edge made it into the refs table.
    from pedia import config as pcfg
    from pedia import index as idx
    conn = idx.connect(pcfg.db_path(tmp_path))
    try:
        rows = list(conn.execute(
            "SELECT src_id, dst_id, kind FROM refs WHERE kind = 'supersedes'"
        ))
        assert any(
            r["src_id"] == new_block_id and r["dst_id"] == prior_block_id
            for r in rows
        ), f"missing supersedes edge among {rows}"
    finally:
        conn.close()


def test_amend_dry_run_does_not_mutate(tmp_path: Path):
    build_lineage(tmp_path)
    spec_path = tmp_path / ".pedia" / "specs" / "001-cache-layer" / "spec.md"
    before = spec_path.read_text(encoding="utf-8")
    result = amend_mod.amend(
        tmp_path, "spec", "001-cache-layer",
        overrides={"problem_statement": "different text"},
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert "different text" in result["new_body"]
    assert spec_path.read_text(encoding="utf-8") == before
    assert not (spec_path.with_suffix(".md.amended-history")).exists()


def test_amend_canned_answers_helper_pads_with_accept():
    """The canned-amendment helper queues an `accept` per field so the
    clarity-loop can request follow-up at most once without hanging."""
    from canon.schemas.spec import SPEC_SCHEMA

    prior_fields = {fs.name: f"prior-{fs.name}" for fs in SPEC_SCHEMA.fields}
    overrides = {"problem_statement": "fresh value"}
    answers = amend_mod.canned_amendment_answers(prior_fields, overrides, SPEC_SCHEMA)
    # Two answers per field: the value, then an "accept".
    assert len(answers) == 2 * len(SPEC_SCHEMA.fields)
    assert answers[0] == "fresh value"
    assert answers[1] == "accept"
    # Field 2 (goals) keeps its prior value.
    assert answers[2] == "prior-goals"
    assert answers[3] == "accept"


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def test_amend_task_raises_until_phase_1b_provides(tmp_path: Path):
    build_lineage(tmp_path)
    # TaskFlow IS importable here, so we hit NotImplementedError (not RuntimeError).
    with pytest.raises(NotImplementedError):
        amend_mod.amend(tmp_path, "task", "HW-0001")


def test_amend_unsupported_type_raises(tmp_path: Path):
    build_lineage(tmp_path)
    with pytest.raises(ValueError):
        amend_mod.amend(tmp_path, "unknown-type", "anything")


# ---------------------------------------------------------------------------
# section extraction unit tests (no external deps)
# ---------------------------------------------------------------------------


def test_extract_section_skips_other_headings():
    body = (
        "# Spec: foo\n\n"
        "## Citations\n\nrelated\n\n"
        "## Problem statement\n\nthe meat\n\n"
        "## Goals\n\n- a\n- b\n"
    )
    assert amend_mod._extract_section(body, "Problem statement") == "the meat"
    goals = amend_mod._extract_section(body, "Goals")
    assert "- a" in goals and "- b" in goals


def test_section_to_field_value_strips_bullets():
    text = "- one\n- two\n1. three"
    assert amend_mod._section_to_field_value(text) == "one\ntwo\nthree"
