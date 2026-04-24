"""Compose a Pedia block from an interview result.

The output is a markdown file with YAML front-matter. Canon embeds:
  - `type:` -- the Pedia doctype
  - `canon_schema_version` -- so amend() can detect schema drift later
  - `canon_field_quality:` -- per-field final score + iteration count
  - `universal_context:` for north-stars + constitution chapters
  - Wiki-link citations to the north-star + constitution chapters
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, Iterable, List, Optional

from canon.interview import InterviewResult


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def _emit_front_matter(fm: Dict[str, Any]) -> str:
    lines: List[str] = ["---"]
    for k, v in fm.items():
        if isinstance(v, dict):
            lines.append(f"{k}:")
            for kk, vv in v.items():
                if isinstance(vv, dict):
                    lines.append(f"  {kk}:")
                    for kkk, vvv in vv.items():
                        lines.append(f"    {kkk}: {_fm_scalar(vvv)}")
                elif isinstance(vv, list):
                    lines.append(f"  {kk}:")
                    for item in vv:
                        lines.append(f"    - {_fm_scalar(item)}")
                else:
                    lines.append(f"  {kk}: {_fm_scalar(vv)}")
        elif isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {_fm_scalar(item)}")
        else:
            lines.append(f"{k}: {_fm_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def _fm_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    needs_quotes = any(c in s for c in ":#[]{}&*!|>'%@`,") or s.strip() != s
    if needs_quotes:
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return s


def _bullets(text: str) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # Strip common bullet prefixes the user may have typed.
        ln = re.sub(r"^(-|\*|\d+[\.\)])\s+", "", ln)
        out.append(ln)
    return out


def _wiki_link(target: str) -> str:
    t = target.strip()
    if not t:
        return ""
    # If the user already typed [[...]] leave it; else wrap.
    if t.startswith("[[") and t.endswith("]]"):
        return t
    return f"[[{t}]]"


# ---------------------------------------------------------------------------
# North-star
# ---------------------------------------------------------------------------


def render_north_star(result: InterviewResult, *, slug: str) -> str:
    f = result.fields
    fm = {
        "type": "north-star",
        "slug": slug,
        "title": f.get("title", slug),
        "universal_context": True,
        "canon_schema_version": 1,
        "canon_field_quality": result.as_front_matter_quality(),
        "created": dt.date.today().isoformat(),
    }
    body = [
        _emit_front_matter(fm),
        "",
        f"# {f.get('title', slug)}",
        "",
        "## Framing",
        "",
        f.get("framing", "").strip(),
        "",
        "## Horizon (3-5 year)",
        "",
        f.get("horizon", "").strip(),
        "",
        "## Rationale",
        "",
        f.get("rationale", "").strip(),
        "",
    ]
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Constitution chapter
# ---------------------------------------------------------------------------


def render_constitution(result: InterviewResult, *, slug: str) -> str:
    f = result.fields
    chapter = f.get("chapter", slug).strip() or slug
    fm = {
        "type": "constitution",
        "slug": slug,
        "chapter": chapter,
        "universal_context": True,
        "canon_schema_version": 1,
        "canon_field_quality": result.as_front_matter_quality(),
        "created": dt.date.today().isoformat(),
    }
    body = [
        _emit_front_matter(fm),
        "",
        f"# Constitution -- {chapter}",
        "",
        "## Principles",
        "",
    ]
    for p in _bullets(f.get("principles", "")):
        body.append(f"- {p}")
    body += [
        "",
        "## Rationale",
        "",
        f.get("rationale", "").strip(),
        "",
    ]
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def render_spec(result: InterviewResult, *, slug: str) -> str:
    f = result.fields
    ns_cite = f.get("north_star_citation", "").strip()
    con_cites = _bullets(f.get("constitutional_citations", ""))
    related = _bullets(f.get("related_work", ""))

    fm: Dict[str, Any] = {
        "type": "spec",
        "slug": slug,
        "canon_schema_version": 1,
        "canon_field_quality": result.as_front_matter_quality(),
        "created": dt.date.today().isoformat(),
        "cites": {
            "north_star": ns_cite or None,
            "constitution": con_cites or None,
            "related": related or None,
        },
    }
    body: List[str] = [
        _emit_front_matter(fm),
        "",
        f"# Spec: {slug}",
        "",
        "## Citations",
        "",
    ]
    if ns_cite:
        body.append(f"- **north-star**: {_wiki_link('north-stars/' + ns_cite + '.md')}")
    for c in con_cites:
        body.append(f"- **constitution**: {_wiki_link('constitution/' + c + '.md')}")
    for r in related:
        body.append(f"- **related**: {_wiki_link(r)}")
    if not ns_cite and not con_cites and not related:
        body.append("- _(none recorded)_")
    body += [
        "",
        "## Problem statement",
        "",
        f.get("problem_statement", "").strip(),
        "",
        "## Goals",
        "",
    ]
    for g in _bullets(f.get("goals", "")):
        body.append(f"- {g}")
    body += [
        "",
        "## Non-goals",
        "",
    ]
    for ng in _bullets(f.get("non_goals", "")):
        body.append(f"- {ng}")
    body += [
        "",
        "## Success criteria",
        "",
    ]
    for sc in _bullets(f.get("success_criteria", "")):
        body.append(f"- {sc}")
    constraints = _bullets(f.get("constraints", ""))
    if constraints:
        body += ["", "## Constraints", ""]
        for c in constraints:
            body.append(f"- {c}")
    body.append("")
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def render_plan(result: InterviewResult, *, spec_slug: str) -> str:
    f = result.fields
    fm: Dict[str, Any] = {
        "type": "plan",
        "spec_slug": spec_slug,
        "canon_schema_version": 1,
        "canon_field_quality": result.as_front_matter_quality(),
        "created": dt.date.today().isoformat(),
        "cites": {
            "spec": spec_slug,
        },
    }
    body: List[str] = [
        _emit_front_matter(fm),
        "",
        f"# Plan: {spec_slug}",
        "",
        "## Citations",
        "",
        f"- **spec**: {_wiki_link('specs/' + spec_slug + '/spec.md')}",
        "",
        "## Approach",
        "",
        f.get("approach", "").strip(),
        "",
        "## Decomposition",
        "",
    ]
    for step in _bullets(f.get("decomposition", "")):
        body.append(f"1. {step}")
    deps = _bullets(f.get("dependencies", ""))
    if deps:
        body += ["", "## Dependencies", ""]
        for d in deps:
            body.append(f"- {d}")
    body += ["", "## Risks + mitigations", ""]
    for r in _bullets(f.get("risks", "")):
        body.append(f"- {r}")
    order = f.get("order_and_parallelism", "").strip()
    if order:
        body += ["", "## Order + parallelism", "", order]
    rollout = f.get("rollout_and_rollback", "").strip()
    if rollout:
        body += ["", "## Rollout + rollback", "", rollout]
    qs = _bullets(f.get("open_questions", ""))
    if qs:
        body += ["", "## Open questions", ""]
        for q in qs:
            body.append(f"- {q}")
    body.append("")
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def render_block(doc_type: str, result: InterviewResult, *, slug: str) -> str:
    if doc_type == "north-star":
        return render_north_star(result, slug=slug)
    if doc_type == "constitution":
        return render_constitution(result, slug=slug)
    if doc_type == "spec":
        return render_spec(result, slug=slug)
    if doc_type == "plan":
        return render_plan(result, spec_slug=slug)
    raise ValueError(f"unknown doc_type for render: {doc_type}")
