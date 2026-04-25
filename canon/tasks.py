"""canon tasks -- generate Hopewell nodes from a plan's decomposition.

Wiring (from canon.cli):
    cmd_tasks(args)  -- entry point bound to `canon tasks <spec-id>`

What this module does (phase 1B):
1. Loads the plan markdown at `.pedia/specs/<slug>/plan.md`.
2. Parses the front-matter + the `## Decomposition` section.
3. For each decomposition step:
   a. Creates a Hopewell node via `project.new_node(...)`.
   b. Sets `component_data["spec-input"]` with citations to the spec
      block + the plan's decomposition step (slice_index N).
   c. Adds a `sizing` component-data entry (XS/S/M/L) when declared.
   d. Suggests an executor component (agent / service / gate) by
      keyword sniffing the step text.
4. Adds blocking-dep edges per the plan's `order_and_parallelism`
   field if it carries a parseable directive.
5. Emits each `## Open questions` line as a separate Hopewell node
   tagged with the `open-question` component.

Idempotency:
   We mark every node we create with
       component_data["canon"] = {
           "spec_slug": "<slug>",
           "plan_step_index": N,        # 1-based within the plan's decomposition
       }
   On re-run we scan the existing node corpus first and skip steps
   that already have a matching marker. So `canon tasks` can run
   repeatedly on the same plan without duplicating nodes.

Public surface:
    cmd_tasks(args) -> int
    parse_plan(plan_path: Path) -> ParsedPlan
    suggest_executor(step_text: str) -> str
    parse_order_directive(text: str) -> List[Tuple[int, int]]   # (blocker, blocked)
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from canon import config as config_mod
from canon import pedia_bridge as pb


# ---------------------------------------------------------------------------
# Hopewell wiring (lazy import so canon-without-hopewell still loads)
# ---------------------------------------------------------------------------


def _load_hopewell():
    try:
        from hopewell import project as hw_project  # type: ignore
        from hopewell.model import EdgeKind, NodeStatus  # type: ignore
        return hw_project, EdgeKind, NodeStatus
    except Exception as e:
        raise RuntimeError(
            f"hopewell is not importable ({e}); install with "
            "`pip install hopewell` to use `canon tasks`"
        )


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


@dataclass
class DecompStep:
    index: int               # 1-based
    text: str                # step prose, sizing prefix stripped
    sizing: Optional[str]    # XS/S/M/L if declared, else None


@dataclass
class ParsedPlan:
    spec_slug: str
    plan_path: Path
    front_matter: Dict[str, Any]
    decomposition: List[DecompStep] = field(default_factory=list)
    order_directive: str = ""
    open_questions: List[str] = field(default_factory=list)


_SIZING_RE = re.compile(r"^\s*(XS|S|M|L)\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)


def _split_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """Best-effort YAML front-matter split. Returns (fm, body).

    We only need a few scalars (spec_slug, type) -- so we hand-parse the
    same subset that canon.config does. Lists + nested dicts are
    flattened to their literal text, which is fine for our use.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head = text[3:end].strip("\n")
    body = text[end + 4 :]
    fm: Dict[str, Any] = {}
    current: Optional[str] = None
    for raw in head.splitlines():
        ln = raw.rstrip()
        if not ln or ln.lstrip().startswith("#"):
            continue
        stripped = ln.lstrip()
        indent = len(ln) - len(stripped)
        if ":" not in stripped:
            continue
        k, _, v = stripped.partition(":")
        k = k.strip()
        v = v.strip()
        if indent == 0:
            if v == "":
                current = k
                fm[k] = {}
            else:
                fm[k] = v
                current = None
        else:
            if current is None:
                fm[k] = v
            else:
                fm.setdefault(current, {})
                if isinstance(fm[current], dict):
                    fm[current][k] = v
    return fm, body


def parse_plan(plan_path: Path) -> ParsedPlan:
    """Read + parse a Canon plan markdown into a ParsedPlan."""
    text = plan_path.read_text(encoding="utf-8")
    fm, body = _split_front_matter(text)
    spec_slug = ""
    if isinstance(fm, dict):
        spec_slug = str(fm.get("spec_slug") or fm.get("slug") or "")
    if not spec_slug:
        # Derive from path if missing: .pedia/specs/<slug>/plan.md
        spec_slug = plan_path.parent.name

    plan = ParsedPlan(
        spec_slug=spec_slug, plan_path=plan_path, front_matter=fm or {},
    )

    # Walk the body section-by-section.
    section: Optional[str] = None
    section_lines: Dict[str, List[str]] = {}
    for raw in body.splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            section = m.group(1).strip().lower()
            section_lines.setdefault(section, [])
            continue
        if section is not None:
            section_lines.setdefault(section, []).append(line)

    # Decomposition: each non-empty bullet = one step.
    decomp_lines = section_lines.get("decomposition", [])
    idx = 0
    for ln in decomp_lines:
        s = ln.strip()
        if not s:
            continue
        # Strip markdown bullet prefixes ("1. ", "- ", "* ").
        s = re.sub(r"^(\d+[\.\)]\s+|[-*]\s+)", "", s)
        if not s:
            continue
        idx += 1
        m = _SIZING_RE.match(s)
        if m:
            sizing = m.group(1).upper()
            text_part = m.group(2).strip()
        else:
            sizing = None
            text_part = s
        plan.decomposition.append(
            DecompStep(index=idx, text=text_part, sizing=sizing)
        )

    # Order + parallelism: keep raw text; we'll parse lazily.
    order_lines = section_lines.get("order + parallelism") or section_lines.get(
        "order and parallelism"
    ) or []
    plan.order_directive = "\n".join(ln for ln in order_lines).strip()

    # Open questions.
    oq = section_lines.get("open questions", [])
    for ln in oq:
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^(\d+[\.\)]\s+|[-*]\s+)", "", s)
        if s:
            plan.open_questions.append(s)

    return plan


# ---------------------------------------------------------------------------
# Heuristics: executor + ordering
# ---------------------------------------------------------------------------


_AGENT_HINT = re.compile(
    r"\b(impl|implement|write|build|scaffold|module|refactor|migrate|"
    r"author|design|wire|integrate|hook|render|generate)\b",
    re.IGNORECASE,
)
_SERVICE_HINT = re.compile(
    r"\b(deploy|service|database|infra|provision|terraform|"
    r"helm|ci|pipeline|publish|release)\b",
    re.IGNORECASE,
)
_GATE_HINT = re.compile(
    r"\b(review|approve|gate|sign[- ]off|qa|verify|audit|"
    r"acceptance|uat)\b",
    re.IGNORECASE,
)


def suggest_executor(step_text: str) -> str:
    """Return one of {'agent','service','gate'} based on the step prose."""
    if _GATE_HINT.search(step_text):
        return "gate"
    if _SERVICE_HINT.search(step_text):
        return "service"
    return "agent"   # default -- most decomposition steps are agent work


# Parse simple ordering directives like:
#   "steps 1,2 serial; 3,4 parallel after 2"
#   "1 -> 2 -> 3"
#   "2 after 1; 3 after 1"
_AFTER_RE = re.compile(
    r"(?P<a>\d+(?:\s*,\s*\d+)*)\s+after\s+(?P<b>\d+(?:\s*,\s*\d+)*)",
    re.IGNORECASE,
)
_SERIAL_RE = re.compile(
    r"(?P<seq>\d+(?:\s*(?:->|,|\s+then\s+)\s*\d+)+)",
    re.IGNORECASE,
)


def parse_order_directive(text: str) -> List[Tuple[int, int]]:
    """Extract (blocker_index, blocked_index) pairs.

    Best-effort: unparseable text yields zero edges (no false drama).
    """
    edges: List[Tuple[int, int]] = []
    if not text:
        return edges
    text_l = text.lower()

    # X after Y -- Y blocks X.
    for m in _AFTER_RE.finditer(text_l):
        afters = [int(s.strip()) for s in m.group("a").split(",")]
        befores = [int(s.strip()) for s in m.group("b").split(",")]
        for b in befores:
            for a in afters:
                if a != b:
                    edges.append((b, a))

    # Serial: 1 -> 2 -> 3  or  1, 2, 3 (when prefixed by "serial")
    if "serial" in text_l or "->" in text_l or " then " in text_l:
        for m in _SERIAL_RE.finditer(text_l):
            seq = re.split(r"\s*(?:->|,|\s+then\s+)\s*", m.group("seq"))
            nums = [int(x) for x in seq if x.strip().isdigit()]
            for i in range(len(nums) - 1):
                edges.append((nums[i], nums[i + 1]))

    # De-dup
    seen = set()
    out: List[Tuple[int, int]] = []
    for e in edges:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


# ---------------------------------------------------------------------------
# Sizing -> estimate-hours metadata
# ---------------------------------------------------------------------------


SIZING_HOURS = {"XS": 1, "S": 4, "M": 16, "L": 40}


def sizing_estimate(sizing: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sizing:
        return None
    s = sizing.upper()
    if s not in SIZING_HOURS:
        return None
    return {"size": s, "estimate_hours": SIZING_HOURS[s]}


# ---------------------------------------------------------------------------
# Idempotency: scan existing nodes for canon markers
# ---------------------------------------------------------------------------


def _existing_canon_index(project) -> Dict[Tuple[str, int], str]:
    """Return {(spec_slug, plan_step_index): node_id} for already-created tasks."""
    out: Dict[Tuple[str, int], str] = {}
    for node in project.all_nodes():
        cd = getattr(node, "component_data", {}) or {}
        canon_meta = cd.get("canon")
        if not isinstance(canon_meta, dict):
            continue
        slug = canon_meta.get("spec_slug")
        idx = canon_meta.get("plan_step_index")
        if isinstance(slug, str) and isinstance(idx, int):
            out[(slug, idx)] = node.id
    return out


def _existing_open_question_index(project) -> Dict[Tuple[str, str], str]:
    out: Dict[Tuple[str, str], str] = {}
    for node in project.all_nodes():
        cd = getattr(node, "component_data", {}) or {}
        canon_meta = cd.get("canon")
        if not isinstance(canon_meta, dict):
            continue
        slug = canon_meta.get("spec_slug")
        oq = canon_meta.get("open_question")
        if isinstance(slug, str) and isinstance(oq, str):
            out[(slug, oq)] = node.id
    return out


# ---------------------------------------------------------------------------
# Core: derive tasks from a parsed plan
# ---------------------------------------------------------------------------


@dataclass
class TasksResult:
    created: List[str] = field(default_factory=list)       # new node ids
    skipped: List[str] = field(default_factory=list)       # already-existed node ids
    open_questions: List[str] = field(default_factory=list)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (blocker_id, blocked_id)


def derive_tasks(project, plan: ParsedPlan, *, dry_run: bool = False) -> TasksResult:
    """Create Hopewell nodes for each decomposition step + open question."""
    _, EdgeKind, NodeStatus = _load_hopewell()
    result = TasksResult()
    existing = _existing_canon_index(project)
    existing_oq = _existing_open_question_index(project)

    # Citation paths into Pedia.
    spec_path = f"specs/{plan.spec_slug}/spec.md"
    plan_path = f"specs/{plan.spec_slug}/plan.md"

    # Map step_index -> node_id (for ordering edges).
    step_to_id: Dict[int, str] = {}

    for step in plan.decomposition:
        key = (plan.spec_slug, step.index)
        if key in existing:
            result.skipped.append(existing[key])
            step_to_id[step.index] = existing[key]
            continue

        executor = suggest_executor(step.text)
        title = step.text[:120]
        components = ["work-item"]

        if dry_run:
            result.created.append(f"<dry-run step {step.index}: {title}>")
            continue

        node = project.new_node(
            components=components,
            title=title,
            priority="P2",
        )

        # spec-input citations: spec + plan, with the plan step index as the slice.
        spec_input = {
            "specs": [
                {
                    "path": spec_path,
                    "slices": ["## Goals", "## Non-goals", "## Success criteria"],
                },
                {
                    "path": plan_path,
                    "slices": [f"## Decomposition (step {step.index})"],
                },
            ],
        }
        node.component_data["spec-input"] = spec_input

        # Suggested executor -- record as advisory data, not a hard component.
        node.component_data["executor-suggestion"] = {"role": executor}

        # Sizing -> estimate metadata.
        est = sizing_estimate(step.sizing)
        if est:
            node.component_data["sizing"] = est

        # Canon idempotency marker.
        node.component_data["canon"] = {
            "spec_slug": plan.spec_slug,
            "plan_step_index": step.index,
        }

        project.save_node(node)
        result.created.append(node.id)
        step_to_id[step.index] = node.id

    # Ordering edges from the plan directive.
    if not dry_run and plan.order_directive:
        for (a, b) in parse_order_directive(plan.order_directive):
            from_id = step_to_id.get(a)
            to_id = step_to_id.get(b)
            if not from_id or not to_id:
                continue
            try:
                project.link(
                    from_id, EdgeKind.blocks, to_id,
                    reason=f"canon tasks: plan order_and_parallelism directive",
                )
                result.edges.append((from_id, to_id))
            except Exception:
                # link() is idempotent in many implementations; tolerate failures.
                pass

    # Open questions become their own nodes.
    for q in plan.open_questions:
        key = (plan.spec_slug, q)
        if key in existing_oq:
            result.skipped.append(existing_oq[key])
            continue
        if dry_run:
            result.open_questions.append(f"<dry-run open-question: {q[:80]}>")
            continue
        # `open-question` isn't a registered Hopewell component; we
        # encode the tag in component_data.canon.open_question so the
        # CLI can filter for them later without expanding the registry.
        oq_node = project.new_node(
            components=["work-item"],
            title=q[:120],
            priority="P3",
        )
        oq_node.component_data["spec-input"] = {
            "specs": [
                {"path": spec_path, "slices": []},
                {"path": plan_path, "slices": ["## Open questions"]},
            ],
        }
        oq_node.component_data["canon"] = {
            "spec_slug": plan.spec_slug,
            "open_question": q,
        }
        project.save_node(oq_node)
        result.open_questions.append(oq_node.id)

    return result


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def cmd_tasks(args) -> int:
    """`canon tasks <spec-id>`."""
    root = config_mod.find_root(Path.cwd()) or Path.cwd()
    if not (root / ".canon").is_dir():
        sys.stderr.write("not a canon project (no .canon/ here or above)\n")
        return 2
    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        sys.stderr.write(msg + "\n")
        return 2

    spec_slug = args.spec_id
    plan_path = root / ".pedia" / "specs" / spec_slug / "plan.md"
    if not plan_path.exists():
        # Try title-slug match.
        candidates = sorted((root / ".pedia" / "specs").glob(f"*-{spec_slug}"))
        if candidates:
            spec_slug = candidates[-1].name
            plan_path = root / ".pedia" / "specs" / spec_slug / "plan.md"
    if not plan_path.exists():
        sys.stderr.write(f"no plan found at .pedia/specs/{args.spec_id}/plan.md\n")
        return 2

    hw_project, _, _ = _load_hopewell()
    try:
        project = hw_project.Project.load(start=root)
    except Exception as e:
        sys.stderr.write(f"hopewell project not initialized: {e}\n")
        sys.stderr.write("run `hopewell init` in this directory first.\n")
        return 2

    plan = parse_plan(plan_path)
    if not plan.decomposition:
        sys.stderr.write(
            f"plan {plan_path.relative_to(root)} has no decomposition steps; "
            "nothing to derive.\n"
        )
        return 1

    result = derive_tasks(project, plan, dry_run=args.dry_run)

    sys.stdout.write(f"canon tasks: spec_slug={plan.spec_slug}\n")
    sys.stdout.write(f"  decomposition steps: {len(plan.decomposition)}\n")
    sys.stdout.write(f"  open questions     : {len(plan.open_questions)}\n")
    sys.stdout.write(f"  created tasks      : {len(result.created)}\n")
    for nid in result.created:
        sys.stdout.write(f"    + {nid}\n")
    if result.skipped:
        sys.stdout.write(f"  skipped (existed)  : {len(result.skipped)}\n")
        for nid in result.skipped:
            sys.stdout.write(f"    = {nid}\n")
    if result.edges:
        sys.stdout.write(f"  ordering edges     : {len(result.edges)}\n")
        for (a, b) in result.edges:
            sys.stdout.write(f"    {a} blocks {b}\n")
    if result.open_questions:
        sys.stdout.write(f"  open-question nodes: {len(result.open_questions)}\n")
        for nid in result.open_questions:
            sys.stdout.write(f"    ? {nid}\n")
    return 0
