"""Tests for canon.check -- citation validator."""
from __future__ import annotations

from pathlib import Path

import pytest

from canon.check import run_check
from canon.tasks import parse_plan, derive_tasks
from tests.fixtures.lineage import (
    build_lineage,
    build_broken_lineage,
    deps_available,
)


pytestmark = pytest.mark.skipif(
    not deps_available(), reason="pedia + hopewell required"
)


def test_check_clean_lineage(tmp_path: Path):
    build_lineage(tmp_path)
    from hopewell import project as hw_project
    project = hw_project.Project.load(start=tmp_path)
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")
    derive_tasks(project, plan)

    report = run_check(tmp_path)
    assert report.errors() == []
    # The clean lineage cites both north-star + constitution; expect no
    # warnings either.
    assert report.warnings() == []
    assert report.counts["specs"] == 1
    assert report.counts["plans"] == 1
    assert report.counts["tasks"] == 4   # 3 work + 1 open-question


def test_check_flags_missing_citations_and_orphan_plan(tmp_path: Path):
    build_broken_lineage(tmp_path)
    report = run_check(tmp_path)

    codes = {f.code for f in report.errors()}
    assert "spec-no-citations" in codes
    assert "plan-cites-missing-spec" in codes


def test_check_flags_broken_task_citation(tmp_path: Path):
    build_lineage(tmp_path)
    from hopewell import project as hw_project
    project = hw_project.Project.load(start=tmp_path)
    plan = parse_plan(tmp_path / ".pedia" / "specs" / "001-cache-layer" / "plan.md")
    derive_tasks(project, plan)

    # Now break the spec on disk.
    (tmp_path / ".pedia" / "specs" / "001-cache-layer" / "spec.md").unlink()
    report = run_check(tmp_path)
    codes = {f.code for f in report.errors()}
    # The plan now becomes orphan + tasks reference a missing spec.md.
    assert "plan-orphan" in codes
    assert "task-broken-citation" in codes


def test_check_warns_on_constitution_when_present_but_uncited(tmp_path: Path):
    build_lineage(tmp_path)
    # Strip the spec's constitution citation so only NS remains.
    spec_path = tmp_path / ".pedia" / "specs" / "001-cache-layer" / "spec.md"
    text = spec_path.read_text(encoding="utf-8")
    text = text.replace(
        "  constitution:\n    - technical\n",
        "  constitution: null\n",
    )
    spec_path.write_text(text, encoding="utf-8")

    report = run_check(tmp_path)
    assert report.errors() == []
    warning_codes = {f.code for f in report.warnings()}
    assert "spec-no-constitution-citation" in warning_codes
