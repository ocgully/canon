"""Render tests -- make sure block composition is well-formed."""
from __future__ import annotations

from canon.interview import FieldOutcome, InterviewResult
from canon.render.block import render_block


def _fake_result(fields: dict) -> InterviewResult:
    outcomes = {
        name: FieldOutcome(
            name=name, answer=val, final_score=0.85, iterations=0,
            accepted_as_is=False,
        )
        for name, val in fields.items()
    }
    return InterviewResult(fields=dict(fields), outcomes=outcomes)


def test_render_spec_has_front_matter_and_citations():
    r = _fake_result({
        "problem_statement": "cold-start P99 > 2000ms on laptop hardware",
        "goals": "cold-start P99 < 500ms\ndocument-load P99 < 200ms",
        "non_goals": "do not rewrite the storage layer",
        "success_criteria": "CI test returns 200 and completes under 500ms",
        "constraints": "",
        "related_work": "",
        "north_star_citation": "agent-first-tooling",
        "constitutional_citations": "technical",
    })
    block = render_block("spec", r, slug="001-cache-layer")
    assert block.startswith("---\n"), block[:50]
    assert "type: spec" in block
    assert "canon_schema_version: 1" in block
    assert "canon_field_quality:" in block
    assert "[[north-stars/agent-first-tooling.md]]" in block
    assert "[[constitution/technical.md]]" in block
    assert "## Problem statement" in block
    assert "cold-start P99 > 2000ms" in block
    assert "## Goals" in block
    assert "## Non-goals" in block
    assert "## Success criteria" in block


def test_render_plan_cites_spec():
    r = _fake_result({
        "approach": "add an LRU cache layer behind a feature flag to lower latency",
        "decomposition": "M: scaffold cache module\nS: wire feature flag\nM: add metrics",
        "dependencies": "",
        "risks": "cache-invalidation drift -> checksum versioning\nmemory pressure -> hard-cap + eviction",
        "order_and_parallelism": "",
        "rollout_and_rollback": "",
        "open_questions": "",
    })
    block = render_block("plan", r, slug="001-cache-layer")
    assert "type: plan" in block
    assert "[[specs/001-cache-layer/spec.md]]" in block
    assert "## Approach" in block
    assert "## Decomposition" in block
    assert "## Risks + mitigations" in block


def test_render_north_star_flags_universal():
    r = _fake_result({
        "title": "Agent-first tooling",
        "framing": "every tool we build assumes an agent operates it",
        "horizon": "in 3-5 years every workflow here is agent-operable",
        "rationale": "humans cost more attention per task than agents",
    })
    block = render_block("north-star", r, slug="agent-first-tooling")
    assert "type: north-star" in block
    assert "universal_context: true" in block
    assert "# Agent-first tooling" in block


def test_render_constitution_flags_universal():
    r = _fake_result({
        "chapter": "technical",
        "principles": "we WILL cite every spec\nwe will NEVER ship without a rollback plan",
        "rationale": "drift kills agent reasoning; hard-won discipline",
    })
    block = render_block("constitution", r, slug="technical")
    assert "type: constitution" in block
    assert "universal_context: true" in block
    assert "# Constitution -- technical" in block
    assert "cite every spec" in block
