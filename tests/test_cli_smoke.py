"""End-to-end smoke test: run `canon init`, then script stdin through
the specify + plan flow via canned_ask."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from canon.interview import canned_ask, run_interview, silent_say
from canon.render import render_block
from canon.schemas.plan import PLAN_SCHEMA
from canon.schemas.spec import SPEC_SCHEMA


def _has_pedia() -> bool:
    try:
        import pedia  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_pedia(), reason="pedia not installed")
def test_end_to_end_spec_and_plan(tmp_path: Path):
    # 1. pedia init -- via our bridge, which chdirs for us.
    from canon import pedia_bridge as pb
    ok, msg = pb.pedia_init_here(tmp_path)
    assert ok, msg

    # 2. canon init -- stamp .canon/
    from canon import config as cfg
    (tmp_path / ".canon").mkdir()
    cfg.save(tmp_path, cfg.CanonConfig())

    # 3. Run a spec interview via canned answers.
    spec_answers = [
        # problem_statement
        "cold-start P99 latency is 2000ms on laptop hardware during onboarding; users drop off before the tool returns 200",
        # goals (3 lines, each with numbers)
        "cold-start P99 < 500ms on M-tier laptop\ncache-hit-rate above 90%\nreturn exit code 0 on cached run",
        # non_goals
        "do not rewrite the storage layer\nnot addressing network latency",
        # success_criteria
        "integration test asserts startup under 500ms and returns 200",
        # constraints (optional, skip)
        "",
        # related_work (optional, skip)
        "",
        # north_star_citation
        "agent-first-tooling",
        # constitutional_citations (optional)
        "technical",
    ]
    ask = canned_ask(spec_answers)
    spec_result = run_interview(SPEC_SCHEMA, ask=ask, say=silent_say())
    body = render_block("spec", spec_result, slug="001-cache-layer")

    spec_dir = tmp_path / ".pedia" / "specs" / "001-cache-layer"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(body, encoding="utf-8")

    # 4. Plan interview.
    plan_answers = [
        # approach (must address cold-start + cache-hit + exit code)
        "add an LRU cache in front of the slow boot path; a feature flag gates the cache so we can roll back within 5 minutes; measures latency cache-hit-rate and exit-code 0 on cached paths",
        # decomposition (>=2)
        "M: scaffold cache module returning 200\nS: wire feature flag into entrypoint\nM: add metrics emitting cache-hit-rate",
        # dependencies (optional)
        "",
        # risks (>=1)
        "cache-invalidation drift -> checksum-version each cache entry so stale reads are rejected\nmemory pressure -> hard 256MB cap with LRU eviction",
        # order
        "",
        # rollout_and_rollback (optional unless user-facing)
        "",
        # open_questions (optional)
        "",
    ]
    ask2 = canned_ask(plan_answers)
    plan_result = run_interview(PLAN_SCHEMA, ask=ask2, say=silent_say())
    plan_body = render_block("plan", plan_result, slug="001-cache-layer")
    (spec_dir / "plan.md").write_text(plan_body, encoding="utf-8")

    # 5. Pedia refresh + check.
    from pedia import refresh as refresh_mod
    refresh_mod.refresh(tmp_path, full=True, docs_glob=None,
                        only_changed_in_session=False)

    # 6. Assertions on the written artifacts.
    assert (spec_dir / "spec.md").exists()
    assert (spec_dir / "plan.md").exists()
    spec_text = (spec_dir / "spec.md").read_text(encoding="utf-8")
    plan_text = (spec_dir / "plan.md").read_text(encoding="utf-8")

    assert "type: spec" in spec_text
    assert "[[north-stars/agent-first-tooling.md]]" in spec_text
    assert "cold-start P99" in spec_text

    assert "type: plan" in plan_text
    assert "[[specs/001-cache-layer/spec.md]]" in plan_text
    assert "LRU cache" in plan_text
