"""canon check -- validate citation completeness across spec/plan/task chain.

Wiring (from canon.cli):
    cmd_check(args)  -- entry point for `canon check [--strict]`

Validations (phase 1B):

  ERROR
  =====
  - spec block has neither north-star nor constitution citation
  - plan present but its `cites.spec` (or `spec_slug`) is missing/empty
    or points to a spec that doesn't exist
  - TaskFlow task with `component_data.canon.spec_slug` references a
    spec that doesn't exist (orphan task)
  - TaskFlow task with `component_data.spec-input` references a path
    that doesn't exist on disk
  - plan present without a corresponding spec.md sibling (orphan plan)

  WARNING
  =======
  - spec missing constitutional citation (when constitution/ has files)
  - plan missing decomposition steps (no tasks possible)
  - TaskFlow tasks exist for a spec but no plan was found
  - tasks claiming a plan_step_index >= len(decomposition)

Exit codes:
  0 = clean
  1 = errors (always)
  2 = warnings only AND --strict was passed

`--format=json` emits a structured JSON report; default is human text.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from canon import config as config_mod
from canon import pedia_bridge as pb


@dataclass
class Finding:
    severity: str          # "error" | "warning"
    code: str              # short machine code, e.g. "spec-no-citations"
    where: str             # file path or node id
    message: str


@dataclass
class CheckReport:
    findings: List[Finding] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)

    def add(self, severity: str, code: str, where: str, message: str) -> None:
        self.findings.append(Finding(severity, code, where, message))

    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


# ---------------------------------------------------------------------------
# Front-matter parsing (mirrors tasks._split_front_matter)
# ---------------------------------------------------------------------------


def _split_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse a front-matter subset:

      key: value                # top-level scalar
      section:                  # nested block opens
        sub_key: value          # nested scalar  (indent >= 2)
        list_key:               # nested list opens
          - item                # list item     (indent >= 4)
        sub_key2: value
      list_at_top:              # top-level list opens
        - item

    Stops when a blank `---` end marker is hit.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head = text[3:end].strip("\n")
    body = text[end + 4 :]
    fm: Dict[str, Any] = {}

    # Stack-of-(container, indent). The active container collects the
    # next entries at indent > its level.
    section: Optional[str] = None      # current section key (under root)
    sub_section: Optional[str] = None  # nested key inside section
    pending_list_target: Optional[Tuple[Any, str]] = None  # (parent_dict, list_key)

    for raw in head.splitlines():
        ln = raw.rstrip()
        if not ln or ln.lstrip().startswith("#"):
            continue
        stripped = ln.lstrip()
        indent = len(ln) - len(stripped)

        # Reset state when we move back to a shallower indent.
        if indent == 0:
            section = None
            sub_section = None
            pending_list_target = None

        # List item.
        if stripped.startswith("-"):
            val = stripped[1:].strip()
            target = pending_list_target
            if target is None:
                # No active list -- ignore.
                continue
            parent, key = target
            parent.setdefault(key, [])
            if isinstance(parent[key], list):
                parent[key].append(val)
            continue

        if ":" not in stripped:
            continue

        k, _, v = stripped.partition(":")
        k = k.strip()
        v = v.strip()

        if indent == 0:
            if v == "":
                section = k
                fm[k] = {}
                sub_section = None
                pending_list_target = (fm, k)   # top-level list candidate
            else:
                fm[k] = v
                section = None
                pending_list_target = None
            continue

        # nested -- under `section` (or, if section is dict-shaped, deeper).
        if section is None:
            fm[k] = v
            continue

        parent = fm.setdefault(section, {})
        if not isinstance(parent, dict):
            # Was filled as scalar -- can't nest. Reset to dict.
            parent = {}
            fm[section] = parent

        if v == "":
            # nested key opens its own list/dict
            parent[k] = []     # tentative; coerce to dict on first scalar child
            sub_section = k
            pending_list_target = (parent, k)
        else:
            parent[k] = v
            sub_section = None
            pending_list_target = (fm, section) if section else None

    # Clean up empty dict values left as `{}` placeholders for sections
    # whose children were all lists -- nothing to do here; tests use
    # `.get(...)` and tolerate either.
    return fm, body


# ---------------------------------------------------------------------------
# Pedia walk
# ---------------------------------------------------------------------------


def _list_specs(root: Path) -> List[Path]:
    d = root / ".pedia" / "specs"
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_dir())


def _has_constitution_chapters(root: Path) -> bool:
    d = root / ".pedia" / "constitution"
    if not d.is_dir():
        return False
    return any(d.glob("*.md"))


def _check_spec(spec_dir: Path, root: Path, report: CheckReport) -> None:
    spec_md = spec_dir / "spec.md"
    rel = str(spec_md.relative_to(root))
    if not spec_md.exists():
        # Standalone plan? (plan-orphan handled separately)
        return
    text = spec_md.read_text(encoding="utf-8")
    fm, _ = _split_front_matter(text)

    cites = fm.get("cites") if isinstance(fm.get("cites"), dict) else {}
    ns = (cites or {}).get("north_star")
    con = (cites or {}).get("constitution")

    def _is_present(v: Any) -> bool:
        if v is None:
            return False
        if isinstance(v, str):
            return v.strip() not in {"", "null", "None"}
        if isinstance(v, (list, tuple)):
            return any(_is_present(x) for x in v)
        return True

    has_ns = _is_present(ns)
    has_con = _is_present(con)

    if not has_ns and not has_con:
        report.add(
            "error", "spec-no-citations", rel,
            "spec must cite at least one north-star or constitution chapter",
        )
    elif not has_con and _has_constitution_chapters(root):
        report.add(
            "warning", "spec-no-constitution-citation", rel,
            "spec cites a north-star but no constitution chapter (a "
            "constitution exists in this project)",
        )


def _check_plan(spec_dir: Path, root: Path, report: CheckReport) -> Tuple[bool, int]:
    """Returns (plan_exists, decomposition_step_count)."""
    plan_md = spec_dir / "plan.md"
    spec_md = spec_dir / "spec.md"
    if not plan_md.exists():
        return (False, 0)

    rel_plan = str(plan_md.relative_to(root))
    if not spec_md.exists():
        report.add(
            "error", "plan-orphan", rel_plan,
            "plan present without a sibling spec.md",
        )

    text = plan_md.read_text(encoding="utf-8")
    fm, body = _split_front_matter(text)

    cites = fm.get("cites") if isinstance(fm.get("cites"), dict) else {}
    cited_spec = (cites or {}).get("spec") or fm.get("spec_slug")
    if not cited_spec:
        report.add(
            "error", "plan-no-spec-citation", rel_plan,
            "plan must cite its spec via cites.spec or spec_slug front-matter",
        )
    else:
        # Cited spec slug should match this directory (or exist).
        candidate = root / ".pedia" / "specs" / str(cited_spec) / "spec.md"
        if not candidate.exists() and cited_spec != spec_dir.name:
            report.add(
                "error", "plan-cites-missing-spec", rel_plan,
                f"plan cites spec '{cited_spec}' which does not exist",
            )

    # Count decomposition steps for the warning-tier check.
    n_steps = 0
    in_decomp = False
    for raw in body.splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            in_decomp = (m.group(1).strip().lower() == "decomposition")
            continue
        if in_decomp:
            s = line.strip()
            if not s:
                continue
            s2 = re.sub(r"^(\d+[\.\)]\s+|[-*]\s+)", "", s)
            if s2:
                n_steps += 1
    if n_steps == 0:
        report.add(
            "warning", "plan-empty-decomposition", rel_plan,
            "plan has no decomposition steps; `canon tasks` will not "
            "produce any nodes",
        )
    return (True, n_steps)


# ---------------------------------------------------------------------------
# TaskFlow side
# ---------------------------------------------------------------------------


def _check_tasks(root: Path, report: CheckReport, *,
                 valid_spec_slugs: set, plan_steps: Dict[str, int]) -> Dict[str, int]:
    """Walk TaskFlow / Hopewell nodes; return {spec_slug: task_count}."""
    counts: Dict[str, int] = {}
    try:
        try:
            from taskflow import project as hw_project  # type: ignore
        except ImportError:
            from hopewell import project as hw_project  # type: ignore  (legacy)
    except Exception:
        # Neither installed -> no tasks to validate; not an error here.
        return counts
    try:
        project = hw_project.Project.load(start=root)
    except Exception:
        return counts

    for node in project.all_nodes():
        cd = getattr(node, "component_data", {}) or {}
        canon_meta = cd.get("canon")
        if not isinstance(canon_meta, dict):
            continue
        slug = canon_meta.get("spec_slug")
        idx = canon_meta.get("plan_step_index")
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
            if slug not in valid_spec_slugs:
                report.add(
                    "error", "task-orphan-spec", node.id,
                    f"task references spec_slug '{slug}' which does not "
                    f"exist as `.pedia/specs/{slug}/spec.md`",
                )
            if isinstance(idx, int) and slug in plan_steps:
                if idx > plan_steps[slug] or idx < 1:
                    report.add(
                        "warning", "task-step-out-of-range", node.id,
                        f"plan_step_index={idx} outside the plan's "
                        f"{plan_steps[slug]} steps for spec '{slug}'",
                    )

        # spec-input: each cited path should exist.
        spec_input = cd.get("spec-input") or {}
        for entry in (spec_input.get("specs") or []):
            path = entry.get("path", "")
            if not path:
                continue
            full = root / ".pedia" / path
            if not full.exists():
                report.add(
                    "error", "task-broken-citation", node.id,
                    f"spec-input cites '{path}' which is not on disk",
                )
        # No spec-input at all on a canon-marked task -> error.
        if isinstance(canon_meta, dict) and canon_meta.get("plan_step_index") is not None:
            if not spec_input.get("specs"):
                report.add(
                    "error", "task-missing-spec-input", node.id,
                    "canon-derived task has no spec-input citations",
                )
    return counts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_check(root: Path) -> CheckReport:
    report = CheckReport()
    spec_dirs = _list_specs(root)
    valid_spec_slugs = {d.name for d in spec_dirs if (d / "spec.md").exists()}
    plan_steps: Dict[str, int] = {}

    for spec_dir in spec_dirs:
        _check_spec(spec_dir, root, report)
        present, n_steps = _check_plan(spec_dir, root, report)
        if present:
            plan_steps[spec_dir.name] = n_steps

    task_counts = _check_tasks(
        root, report, valid_spec_slugs=valid_spec_slugs, plan_steps=plan_steps,
    )

    # Tasks-without-plan check.
    for slug, count in task_counts.items():
        if slug in valid_spec_slugs and slug not in plan_steps:
            report.add(
                "warning", "tasks-without-plan",
                f"specs/{slug}",
                f"{count} task(s) reference spec '{slug}' but no plan.md was found",
            )

    report.counts = {
        "specs": len(spec_dirs),
        "valid_specs": len(valid_spec_slugs),
        "plans": len(plan_steps),
        "tasks": sum(task_counts.values()),
        "errors": len(report.errors()),
        "warnings": len(report.warnings()),
    }
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_check(args) -> int:
    root = config_mod.find_root(Path.cwd()) or Path.cwd()
    if not (root / ".canon").is_dir():
        sys.stderr.write("not a canon project (no .canon/ here or above)\n")
        return 2
    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        sys.stderr.write(msg + "\n")
        return 2

    report = run_check(root)

    if getattr(args, "format", "text") == "json":
        out = {
            "counts": report.counts,
            "findings": [asdict(f) for f in report.findings],
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
    else:
        c = report.counts
        sys.stdout.write(
            f"canon check: {c.get('specs',0)} specs, "
            f"{c.get('plans',0)} plans, {c.get('tasks',0)} tasks\n"
        )
        sys.stdout.write(
            f"  errors: {c.get('errors',0)}  warnings: {c.get('warnings',0)}\n"
        )
        if not report.findings:
            sys.stdout.write("  clean.\n")
        else:
            for f in report.findings:
                tag = "ERROR" if f.severity == "error" else "warn"
                sys.stdout.write(f"  [{tag}] {f.code}: {f.where}\n")
                sys.stdout.write(f"         {f.message}\n")

    if report.errors():
        return 1
    if report.warnings() and getattr(args, "strict", False):
        return 2
    return 0
