"""Shared fixture: build a complete spec -> plan project on disk for 1B tests.

We bypass the clarity-loop interview here (1A's territory) and write
deterministic Pedia markdown directly. Tests for tasks/implement/check
only care that the spec + plan are well-formed Pedia blocks with the
front-matter Canon expects.

Lays down:
  - .canon/config.yaml
  - .pedia/  (via pedia init)
  - .pedia/north-stars/agent-first.md
  - .pedia/constitution/technical.md
  - .pedia/specs/001-cache-layer/spec.md
  - .pedia/specs/001-cache-layer/plan.md
  - .hopewell/         (via hopewell init)
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def _has_pedia() -> bool:
    try:
        import pedia  # noqa: F401
        return True
    except Exception:
        return False


def _has_hopewell() -> bool:
    try:
        import hopewell  # noqa: F401
        return True
    except Exception:
        return False


def deps_available() -> bool:
    return _has_pedia() and _has_hopewell()


NORTH_STAR_MD = dedent("""\
    ---
    type: north-star
    slug: agent-first
    title: agent-first
    universal_context: true
    canon_schema_version: 1
    created: 2026-01-01
    ---

    # agent-first

    ## Framing

    agents are first-class participants in our tools.

    ## Horizon (3-5 year)

    every tool surfaces a structured CLI for agent consumption.

    ## Rationale

    humans + agents both benefit when surfaces are typed and queryable.
""")


CONSTITUTION_MD = dedent("""\
    ---
    type: constitution
    slug: technical
    chapter: technical
    universal_context: true
    canon_schema_version: 1
    created: 2026-01-01
    ---

    # Constitution -- technical

    ## Principles

    - no synchronous network above the data layer
    - prefer correctness over velocity

    ## Rationale

    Sync calls + rushed code cost throughput; we have lived this.
""")


SPEC_MD = dedent("""\
    ---
    type: spec
    slug: 001-cache-layer
    canon_schema_version: 1
    created: 2026-01-01
    cites:
      north_star: agent-first
      constitution:
        - technical
    ---

    # Spec: 001-cache-layer

    ## Citations

    - **north-star**: [[north-stars/agent-first.md]]
    - **constitution**: [[constitution/technical.md]]

    ## Problem statement

    cold-start P99 latency is 2200ms on M-tier laptops during onboarding;
    users drop off before the tool returns 200.

    ## Goals

    - cold-start P99 < 500ms on M-tier laptop
    - cache-hit-rate above 90%
    - return exit code 0 on cached run

    ## Non-goals

    - do not rewrite the storage layer
    - not addressing network latency

    ## Success criteria

    - integration test asserts startup under 500ms and returns 200
""")


PLAN_MD = dedent("""\
    ---
    type: plan
    spec_slug: 001-cache-layer
    canon_schema_version: 1
    created: 2026-01-01
    cites:
      spec: 001-cache-layer
    ---

    # Plan: 001-cache-layer

    ## Citations

    - **spec**: [[specs/001-cache-layer/spec.md]]

    ## Approach

    Add an LRU cache in front of the slow boot path; a feature flag gates
    the cache so we can roll back within 5 minutes; metrics confirm
    cache-hit-rate and exit-code 0 on cached paths.

    ## Decomposition

    1. M: scaffold cache module returning 200
    1. S: wire feature flag into entrypoint
    1. M: add metrics emitting cache-hit-rate

    ## Risks + mitigations

    - cache invalidation drift -> checksum-version each cache entry
    - memory pressure -> hard 256MB cap with LRU eviction

    ## Order + parallelism

    2 after 1; 3 after 1

    ## Rollout + rollback

    Ship behind a feature flag; flag-off rolls back within 5 minutes.

    ## Open questions

    - should the cache persist across sessions?
""")


def build_lineage(tmp_path: Path) -> Path:
    """Lay out a full canon-1A project rooted at tmp_path. Returns tmp_path."""
    from canon import config as canon_config
    from canon import pedia_bridge as pb

    ok, msg = pb.pedia_init_here(tmp_path)
    assert ok, msg

    (tmp_path / ".canon").mkdir(exist_ok=True)
    canon_config.save(tmp_path, canon_config.CanonConfig())

    ns_dir = tmp_path / ".pedia" / "north-stars"
    ns_dir.mkdir(parents=True, exist_ok=True)
    (ns_dir / "agent-first.md").write_text(NORTH_STAR_MD, encoding="utf-8")

    con_dir = tmp_path / ".pedia" / "constitution"
    con_dir.mkdir(parents=True, exist_ok=True)
    (con_dir / "technical.md").write_text(CONSTITUTION_MD, encoding="utf-8")

    spec_dir = tmp_path / ".pedia" / "specs" / "001-cache-layer"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text(SPEC_MD, encoding="utf-8")
    (spec_dir / "plan.md").write_text(PLAN_MD, encoding="utf-8")

    from pedia import refresh as refresh_mod
    refresh_mod.refresh(tmp_path, full=True, docs_glob=None,
                        only_changed_in_session=False)

    from hopewell import project as hw_project
    hw_project.Project.init(
        tmp_path, id_prefix="HW", name="canon-1b-test", auto_backfill=False,
    )
    return tmp_path


def build_broken_lineage(tmp_path: Path) -> Path:
    """A project with intentional citation gaps for `canon check` tests.

    - Spec without any citations (north-star or constitution)
    - Plan that cites a non-existent spec
    """
    from canon import config as canon_config
    from canon import pedia_bridge as pb

    ok, msg = pb.pedia_init_here(tmp_path)
    assert ok, msg

    (tmp_path / ".canon").mkdir(exist_ok=True)
    canon_config.save(tmp_path, canon_config.CanonConfig())

    # No north-stars, no constitution -- but a spec with empty citations.
    spec_dir = tmp_path / ".pedia" / "specs" / "002-broken"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text(dedent("""\
        ---
        type: spec
        slug: 002-broken
        canon_schema_version: 1
        created: 2026-01-01
        cites:
          north_star: null
          constitution: null
        ---

        # Spec: 002-broken

        ## Problem statement

        ad-hoc -- no citations.
    """), encoding="utf-8")
    (spec_dir / "plan.md").write_text(dedent("""\
        ---
        type: plan
        spec_slug: 999-does-not-exist
        canon_schema_version: 1
        created: 2026-01-01
        cites:
          spec: 999-does-not-exist
        ---

        # Plan: 999-does-not-exist

        ## Decomposition

        1. M: do something

    """), encoding="utf-8")

    from pedia import refresh as refresh_mod
    refresh_mod.refresh(tmp_path, full=True, docs_glob=None,
                        only_changed_in_session=False)

    from hopewell import project as hw_project
    hw_project.Project.init(
        tmp_path, id_prefix="HW", name="canon-1b-broken", auto_backfill=False,
    )
    return tmp_path
