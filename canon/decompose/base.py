"""Shared types + plan parsing for decompose strategies.

This module is strategy-agnostic. Strategies in `canon.decompose.strategies.*`
all consume a `ParsedPlan` and emit a `StrategyResult`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


@dataclass
class DecompStep:
    """A single bullet from the plan's `## Decomposition` section."""

    index: int               # 1-based
    text: str                # step prose, sizing prefix stripped
    sizing: Optional[str]    # XS/S/M/L if declared, else None


@dataclass
class ParsedPlan:
    """The parsed contents of a plan markdown file.

    All strategies start from one of these. Strategy-specific metadata
    lives in `front_matter` (e.g. user-journey rows for story-map).
    """

    spec_slug: str
    plan_path: Path
    front_matter: Dict[str, Any]
    decomposition: List[DecompStep] = field(default_factory=list)
    order_directive: str = ""
    open_questions: List[str] = field(default_factory=list)


_SIZING_RE = re.compile(r"^\s*(XS|S|M|L)\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)


def _split_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """Best-effort YAML front-matter split. Returns (fm, body).

    Same hand-rolled subset as `canon.config`; we do not pull in PyYAML.
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
        spec_slug = plan_path.parent.name

    plan = ParsedPlan(
        spec_slug=spec_slug, plan_path=plan_path, front_matter=fm or {},
    )

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

    decomp_lines = section_lines.get("decomposition", [])
    idx = 0
    for ln in decomp_lines:
        s = ln.strip()
        if not s:
            continue
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

    order_lines = section_lines.get("order + parallelism") or section_lines.get(
        "order and parallelism"
    ) or []
    plan.order_directive = "\n".join(ln for ln in order_lines).strip()

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
# Heuristics (shared by multiple strategies)
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
    """Return one of {'agent','service','gate'} based on step prose."""
    if _GATE_HINT.search(step_text):
        return "gate"
    if _SERVICE_HINT.search(step_text):
        return "service"
    return "agent"


_AFTER_RE = re.compile(
    r"(?P<a>\d+(?:\s*,\s*\d+)*)\s+after\s+(?P<b>\d+(?:\s*,\s*\d+)*)",
    re.IGNORECASE,
)
_SERIAL_RE = re.compile(
    r"(?P<seq>\d+(?:\s*(?:->|,|\s+then\s+)\s*\d+)+)",
    re.IGNORECASE,
)


def parse_order_directive(text: str) -> List[Tuple[int, int]]:
    """Extract (blocker_index, blocked_index) pairs from a free-form line."""
    edges: List[Tuple[int, int]] = []
    if not text:
        return edges
    text_l = text.lower()

    for m in _AFTER_RE.finditer(text_l):
        afters = [int(s.strip()) for s in m.group("a").split(",")]
        befores = [int(s.strip()) for s in m.group("b").split(",")]
        for b in befores:
            for a in afters:
                if a != b:
                    edges.append((b, a))

    if "serial" in text_l or "->" in text_l or " then " in text_l:
        for m in _SERIAL_RE.finditer(text_l):
            seq = re.split(r"\s*(?:->|,|\s+then\s+)\s*", m.group("seq"))
            nums = [int(x) for x in seq if x.strip().isdigit()]
            for i in range(len(nums) - 1):
                edges.append((nums[i], nums[i + 1]))

    seen = set()
    out: List[Tuple[int, int]] = []
    for e in edges:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


SIZING_HOURS = {"XS": 1, "S": 4, "M": 16, "L": 40}


def sizing_estimate(sizing: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sizing:
        return None
    s = sizing.upper()
    if s not in SIZING_HOURS:
        return None
    return {"size": s, "estimate_hours": SIZING_HOURS[s]}


# ---------------------------------------------------------------------------
# Strategy output shape
# ---------------------------------------------------------------------------


@dataclass
class WorkItem:
    """A strategy-emitted work item, pre-materialization.

    Strategies return these; the dispatch layer turns them into Hopewell
    nodes (when a Hopewell project is loaded) or returns them as plain
    JSON (when --dry-run or when Hopewell is absent).

    `kind` is a strategy-specific tag used downstream for display +
    flow-network shaping (e.g. `spike` vs `build`, `slice`, `activity`).

    `wave` is an integer for the `flow` strategy (parallel-wave plan);
    other strategies leave it None.

    `parallel_with` is the set of sibling indexes a flow-strategy item
    can run in parallel with; same wave -> parallel.

    `metadata` is opaque per-strategy data, copied verbatim into the
    materialized Hopewell node's `component_data["canon"]["strategy_meta"]`.
    """

    index: int                          # 1-based, unique within the result
    kind: str                           # "task" | "spike" | "build" | "slice" | "activity" | "story"
    title: str
    sizing: Optional[str] = None        # XS/S/M/L
    spec_slices: List[str] = field(default_factory=list)
    plan_slices: List[str] = field(default_factory=list)
    blockers: List[int] = field(default_factory=list)   # indexes that must finish first
    wave: Optional[int] = None
    parallel_with: List[int] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: str = "P2"
    executor_role: Optional[str] = None  # agent | service | gate (advisory)


@dataclass
class StrategyResult:
    """The full output of a strategy run.

    `items`: ordered list of work items.
    `open_questions`: prose lines pulled from the plan's `## Open questions`.
    `extras`: strategy-specific top-level data (e.g. story-map backbone
              activities, flow-strategy waves dictionary).
    """

    strategy: str
    items: List[WorkItem] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)
