"""Canon amend -- incremental clarity-loop amendment of an existing block.

Wired into the CLI as:

    canon amend <doc-type> <id> [--dry-run]

Where <doc-type> is one of:
    spec | plan | task | ns | constitution

`ns` is shorthand for `north-star`.

Mechanics
---------
1. Locate the prior block by (doc-type, slug-or-id) on disk under .pedia/.
2. Parse its front-matter to recover existing field values and its
   block-id (Pedia's content-hash short id).
3. Run an INCREMENTAL clarity-loop interview: each field's prompt is
   pre-pended with the existing value as context. The user can `accept`
   to keep the value verbatim, or augment.
4. Render a NEW Pedia block. Front-matter gets:
     supersedes: <prior-block-id>
     amends:    <prior-doc-path>
     amended_at: <YYYY-MM-DD>
   plus an `## Amendment history` section listing prior block ids.
5. Mark the OLD block: the prior on-disk file's front-matter gains
   `superseded_by: <new-block-id>` -- the file stays queryable by Pedia
   but is flagged.
6. After `pedia refresh`, write a `supersedes` edge directly into the
   Pedia refs table (Pedia auto-indexes wiki-link `cites` edges but
   not typed front-matter relations).
7. If task drift may have been introduced (a spec or plan was amended
   and TaskFlow is importable + has spec-input refs), run
   `taskflow spec-ref drift --all` and surface its output -- per HW-0034.
   This is best-effort; a missing TaskFlow is non-fatal.

Tasks
-----
For doc-type `task`, this module wraps TaskFlow's amend semantics: the
canonical "amend" of a task is updating its node + recording an event
note. We delegate to TaskFlow when present and degrade gracefully
otherwise (just stamps a note in the Pedia task block, if the project
mirrors tasks into Pedia).

Phase 1B owns task derivation; phase 1C only consumes it. If 1B isn't
landed yet, `canon amend task <id>` prints a clear "task amend requires
phase 1B" message and exits non-zero.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from canon import pedia_bridge as pb
from canon.interview import (
    InterviewResult,
    canned_ask,
    run_interview,
)
from canon.render import render_block
from canon.schemas import Schema
from canon.schemas.constitution import CONSTITUTION_SCHEMA
from canon.schemas.north_star import NORTH_STAR_SCHEMA
from canon.schemas.plan import PLAN_SCHEMA
from canon.schemas.spec import SPEC_SCHEMA


# Doc-type -> (schema, on-disk filename pattern, folder lookup key)
_SCHEMA_BY_TYPE: Dict[str, Schema] = {
    "spec": SPEC_SCHEMA,
    "plan": PLAN_SCHEMA,
    "ns": NORTH_STAR_SCHEMA,
    "north-star": NORTH_STAR_SCHEMA,
    "constitution": CONSTITUTION_SCHEMA,
}

# Aliases the user can pass on the CLI.
_TYPE_ALIASES = {
    "ns": "north-star",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@dataclass
class PriorBlock:
    """A loaded existing block that's about to be amended."""

    doc_type: str          # canonicalized: spec / plan / north-star / constitution
    slug: str              # spec slug like 001-cache-layer or simply "agent-first-tooling"
    path: Path             # absolute path to the on-disk file
    front_matter: Dict[str, Any]
    fields: Dict[str, str] # extracted answers from front-matter / body sections
    block_id: Optional[str] # Pedia's content-hash short id; may be None pre-refresh


def _canonicalize_type(t: str) -> str:
    return _TYPE_ALIASES.get(t, t)


def _resolve_prior_path(root: Path, doc_type: str, identifier: str) -> Optional[Path]:
    """Find the on-disk file for (doc_type, identifier).

    `identifier` is whatever the user typed: a slug, a numbered slug,
    a bare title-slug (auto-resolved against existing specs).
    """
    pedia_root = root / ".pedia"
    if doc_type == "north-star":
        cand = pedia_root / "north-stars" / f"{identifier}.md"
        if cand.exists():
            return cand
    if doc_type == "constitution":
        cand = pedia_root / "constitution" / f"{identifier}.md"
        if cand.exists():
            return cand
    if doc_type == "spec":
        cand = pedia_root / "specs" / identifier / "spec.md"
        if cand.exists():
            return cand
        # bare title-slug: pick latest numeric prefix
        matches = sorted((pedia_root / "specs").glob(f"*-{identifier}"))
        if matches:
            return matches[-1] / "spec.md"
    if doc_type == "plan":
        cand = pedia_root / "specs" / identifier / "plan.md"
        if cand.exists():
            return cand
        matches = sorted((pedia_root / "specs").glob(f"*-{identifier}"))
        if matches and (matches[-1] / "plan.md").exists():
            return matches[-1] / "plan.md"
    return None


# ---- minimal front-matter parser (we already emit a small YAML subset) -----


def _parse_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split ``--- ... ---`` front-matter from the body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip("\n")
    body_start = end + len("\n---")
    if text[body_start: body_start + 1] == "\n":
        body_start += 1
    body = text[body_start:]
    fm: Dict[str, Any] = {}
    cur_section: Optional[str] = None
    cur_list: Optional[List[Any]] = None
    cur_indent: int = 0
    for raw in fm_text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("- "):
            value = _coerce(stripped[2:].strip())
            if cur_list is not None:
                cur_list.append(value)
            continue
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        if indent == 0:
            cur_section = None
            cur_list = None
            if val == "":
                fm[key] = {}
                cur_section = key
                cur_indent = indent
            else:
                fm[key] = _coerce(val)
        else:
            if cur_section is None:
                fm[key] = _coerce(val)
                continue
            if val == "":
                fm[cur_section].setdefault(key, [])
                cur_list = fm[cur_section][key] = []
            else:
                if isinstance(fm.get(cur_section), dict):
                    fm[cur_section][key] = _coerce(val)
                else:
                    fm[key] = _coerce(val)
    return fm, body


def _coerce(v: str) -> Any:
    if v == "null":
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


# ---- body section extraction -----------------------------------------------

# Map (doc_type, schema-field-name) -> markdown heading title used by render.
_BODY_SECTION_HEADINGS = {
    ("spec", "problem_statement"): "Problem statement",
    ("spec", "goals"): "Goals",
    ("spec", "non_goals"): "Non-goals",
    ("spec", "success_criteria"): "Success criteria",
    ("spec", "constraints"): "Constraints",
    ("plan", "approach"): "Approach",
    ("plan", "decomposition"): "Decomposition",
    ("plan", "dependencies"): "Dependencies",
    ("plan", "risks"): "Risks + mitigations",
    ("plan", "order_and_parallelism"): "Order + parallelism",
    ("plan", "rollout_and_rollback"): "Rollout + rollback",
    ("plan", "open_questions"): "Open questions",
    ("north-star", "framing"): "Framing",
    ("north-star", "horizon"): "Horizon (3-5 year)",
    ("north-star", "rationale"): "Rationale",
    ("constitution", "principles"): "Principles",
    ("constitution", "rationale"): "Rationale",
}


def _extract_section(body: str, heading_title: str) -> str:
    """Return the markdown body of ``## <heading_title>`` until the next ``## `` heading."""
    lines = body.splitlines()
    out: List[str] = []
    in_section = False
    for ln in lines:
        if ln.startswith("## "):
            if in_section:
                break
            if ln[3:].strip() == heading_title:
                in_section = True
                continue
        if in_section:
            out.append(ln)
    # strip trailing blanks
    while out and not out[-1].strip():
        out.pop()
    while out and not out[0].strip():
        out.pop(0)
    return "\n".join(out)


def _strip_bullet_prefix(s: str) -> str:
    return re.sub(r"^(?:-|\*|\d+[\.\)])\s+", "", s.strip())


def _section_to_field_value(text: str) -> str:
    """Convert a rendered markdown section back to a clarity-loop value.

    Rendered specs use ``- bullet`` lines; plans use ``1. step`` lines.
    Both flatten back to newline-separated entries.
    """
    if not text:
        return ""
    lines = [_strip_bullet_prefix(ln) for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _extract_fields(doc_type: str, fm: Dict[str, Any], body: str,
                    schema: Schema) -> Dict[str, str]:
    """Recover the original interview answers from the rendered block."""
    out: Dict[str, str] = {}
    for fs in schema.fields:
        heading = _BODY_SECTION_HEADINGS.get((doc_type, fs.name))
        if heading:
            section = _extract_section(body, heading)
            out[fs.name] = _section_to_field_value(section)
            continue
        # citations live in front-matter for specs/plans
        if doc_type == "spec":
            cites = fm.get("cites") or {}
            if fs.name == "north_star_citation":
                out[fs.name] = cites.get("north_star") or ""
                continue
            if fs.name == "constitutional_citations":
                lst = cites.get("constitution") or []
                out[fs.name] = "\n".join(lst) if isinstance(lst, list) else str(lst or "")
                continue
            if fs.name == "related_work":
                lst = cites.get("related") or []
                out[fs.name] = "\n".join(lst) if isinstance(lst, list) else str(lst or "")
                continue
        if doc_type == "north-star" and fs.name == "title":
            out[fs.name] = fm.get("title") or ""
            continue
        if doc_type == "constitution" and fs.name == "chapter":
            out[fs.name] = fm.get("chapter") or ""
            continue
        out[fs.name] = ""
    return out


def load_prior(root: Path, doc_type: str, identifier: str) -> PriorBlock:
    """Locate + parse an existing block. Raises FileNotFoundError on miss."""
    canonical = _canonicalize_type(doc_type)
    if canonical not in _SCHEMA_BY_TYPE and canonical != "task":
        raise ValueError(f"unsupported doc-type for amend: {doc_type}")
    path = _resolve_prior_path(root, canonical, identifier)
    if path is None:
        raise FileNotFoundError(
            f"no {canonical} block found for identifier '{identifier}' under {root / '.pedia'}"
        )
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_front_matter(text)
    schema = _SCHEMA_BY_TYPE.get(canonical)
    fields: Dict[str, str] = {}
    if schema is not None:
        fields = _extract_fields(canonical, fm, body, schema)
    block_id = _block_id_for_path(root, path)
    # Recover the slug from front-matter where possible; else fall back to dirname.
    slug = (fm.get("slug") or fm.get("spec_slug")
            or path.parent.name if canonical in {"spec", "plan"}
            else (fm.get("slug") or path.stem))
    return PriorBlock(
        doc_type=canonical,
        slug=str(slug),
        path=path,
        front_matter=fm,
        fields=fields,
        block_id=block_id,
    )


def _block_id_for_path(root: Path, path: Path) -> Optional[str]:
    """Look up the FIRST block-id Pedia has indexed for this doc.

    For specs / plans the first block is the doc itself (heading
    ``# Spec: <slug>`` etc.). Returns None if Pedia hasn't indexed it
    yet -- caller should refresh first.
    """
    try:
        from pedia import index as idx
        from pedia import config as pcfg
        rel = str(path.relative_to(root / ".pedia")).replace("\\", "/")
        conn = idx.connect(pcfg.db_path(root))
        try:
            row = conn.execute(
                "SELECT id FROM blocks WHERE doc_path = ? "
                "ORDER BY line_start LIMIT 1",
                (rel,),
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# amendment-history section + superseded_by mark
# ---------------------------------------------------------------------------


def _append_amendment_history(body: str, prior_block_id: Optional[str],
                              prior_path: Path) -> str:
    """Append (or extend) an `## Amendment history` section in the new block."""
    today = dt.date.today().isoformat()
    entry_lines = [f"- **{today}**: amended -- supersedes prior block"]
    if prior_block_id:
        entry_lines.append(f"  - prior block id: `{prior_block_id}`")
    entry_lines.append(f"  - prior path: `{prior_path}`")

    # Re-emit the section header even if absent so it always shows.
    if "## Amendment history" in body:
        # Insert new entries directly under the existing header.
        out_lines: List[str] = []
        injected = False
        for ln in body.splitlines():
            out_lines.append(ln)
            if not injected and ln.strip() == "## Amendment history":
                out_lines.append("")
                out_lines.extend(entry_lines)
                injected = True
        return "\n".join(out_lines)
    addition = ["", "## Amendment history", ""] + entry_lines + [""]
    if not body.endswith("\n"):
        body += "\n"
    return body + "\n".join(addition) + "\n"


def _mark_superseded(prior_path: Path, new_block_id: Optional[str],
                     new_path: Path) -> None:
    """Re-write the prior file with `superseded_by:` front-matter."""
    text = prior_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return  # we only touch blocks with front-matter we recognize
    end = text.find("\n---", 3)
    if end == -1:
        return
    fm_block = text[3:end]
    rest = text[end:]  # starts at "\n---"

    new_lines: List[str] = []
    seen_keys = set()
    for raw in fm_block.splitlines():
        ln = raw
        # drop a prior superseded_by line so we don't accumulate stale entries
        if ln.lstrip().startswith("superseded_by:"):
            seen_keys.add("superseded_by")
            continue
        new_lines.append(ln)
    today = dt.date.today().isoformat()
    new_lines.append(f"superseded_by: {new_block_id or 'unknown'}")
    new_lines.append(f"superseded_at: {today}")
    new_lines.append(f"superseded_by_path: {new_path}")

    new_fm = "---" + "\n".join([""] + new_lines) + "\n"
    prior_path.write_text(new_fm + rest.lstrip("\n").lstrip("-") if False else new_fm + rest,
                          encoding="utf-8")


# ---------------------------------------------------------------------------
# pre-seeding the interview from prior values
# ---------------------------------------------------------------------------


def _seeded_ask_for(prior_fields: Dict[str, str], schema: Schema, say) -> Any:
    """Wrap stdin so the user sees the prior value before each prompt and
    can either ``accept`` (keep), ``replace`` (start fresh), or type a delta.

    For automated tests, we expose `canned_amendment_answers` below.
    """
    from canon.interview import _default_ask  # type: ignore

    field_iter = iter(schema.fields)
    state: Dict[str, Any] = {"current": None}

    def ask(prompt: str) -> str:
        # First call per field arrives via interview_field's main prompt.
        # Track which field we're on by inspecting the prompt text -- we
        # also peek the field iterator so we know its name.
        if state["current"] is None:
            try:
                state["current"] = next(field_iter)
            except StopIteration:
                state["current"] = None
        fs = state["current"]
        # Show prior value for the FIRST prompt of the field only.
        if fs is not None and prior_fields.get(fs.name):
            say(f"  prior value for [{fs.name}]:")
            for ln in prior_fields[fs.name].splitlines() or [""]:
                say(f"    | {ln}")
            say("  press <enter> to keep as-is, or type to add detail / replace")
        ans = _default_ask(prompt)
        # If user just hits enter and we have a prior value, treat as "keep".
        if (not ans.strip()) and fs is not None and prior_fields.get(fs.name):
            ans = prior_fields[fs.name]
        # When the loop moves on to follow-ups for THIS field, prompt text
        # contains "follow-up" -- we don't want to advance state. We
        # reset state["current"] on each top-level field change instead.
        # Detect end of field by checking the prompt header marker.
        if "[" in prompt and "]" in prompt and "follow-up" not in prompt:
            # We already advanced; nothing else to do.
            pass
        return ans

    return ask


def canned_amendment_answers(
    prior_fields: Dict[str, str],
    overrides: Dict[str, str],
    schema: Schema,
) -> List[str]:
    """Build a flat answer list for ``canned_ask`` simulating an amend.

    For each field in `schema`, if `overrides[field.name]` exists, that
    string is used; else the prior value is used (=> the "accept as-is"
    path). One follow-up answer of "accept" is queued per field for the
    case where clarity asks for more.
    """
    out: List[str] = []
    for fs in schema.fields:
        out.append(overrides.get(fs.name, prior_fields.get(fs.name, "")))
        # one safety "accept" in case the clarity-loop asks once
        out.append("accept")
    return out


# ---------------------------------------------------------------------------
# write the supersedes ref into Pedia's index
# ---------------------------------------------------------------------------


def write_supersedes_edge(root: Path, src_block_id: str,
                          dst_block_id: str) -> bool:
    """Insert a typed `supersedes` ref into Pedia's refs table."""
    try:
        from pedia import index as idx
        from pedia import config as pcfg
        conn = idx.connect(pcfg.db_path(root))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO refs(src_id, dst_id, kind) VALUES (?,?,?)",
                (src_block_id, dst_block_id, "supersedes"),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# TaskFlow drift surfacing (best-effort)
# ---------------------------------------------------------------------------


def maybe_surface_drift(root: Path, doc_type: str, slug: str) -> Optional[str]:
    """If the amended doc-type may have downstream tasks with spec-input
    refs, attempt `taskflow spec-ref drift --all` and return its output.

    Returns None if TaskFlow is absent or the call fails -- callers
    treat that as "no drift surfaced". The legacy `hopewell` CLI is
    tried as a fallback.
    """
    if doc_type not in {"spec", "plan"}:
        return None
    try:
        # Try the new CLI name first; fall back to the deprecation alias.
        try:
            proc = subprocess.run(
                ["taskflow", "spec-ref", "drift", "--all"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError:
            proc = subprocess.run(
                ["hopewell", "spec-ref", "drift", "--all"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
    except Exception:
        return None
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if not out and not err:
        return None
    return f"spec-ref drift --all (exit={proc.returncode}):\n{out}\n{err}".rstrip()


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def amend(
    root: Path,
    doc_type: str,
    identifier: str,
    *,
    max_iter: int = 5,
    dry_run: bool = False,
    overrides: Optional[Dict[str, str]] = None,
    say=None,
    regenerate: bool = False,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Amend an existing block.

    Returns a result dict with the new path, the prior path, the prior
    + new block ids (when known), and any drift output.

    `overrides` lets tests inject answers without touching stdin: each
    listed field is treated as the new value; absent fields keep their
    prior value.

    `regenerate=True` (only valid with doc_type in {plan}) re-runs the
    decompose strategy in place, swapping out work items for the new
    strategy. Plain `amend` (regenerate=False) preserves the existing
    strategy and only patches text. Pass `strategy="..."` to choose the
    new strategy explicitly; otherwise the resolver's chain runs.
    """
    if regenerate:
        return amend_regenerate(
            root, doc_type, identifier,
            strategy=strategy, dry_run=dry_run,
        )

    canonical = _canonicalize_type(doc_type)
    if canonical == "task":
        # Phase 1B owns task derivation; we hand off when present.
        # The canonical package name is `taskflow`; the legacy `hopewell`
        # name is still accepted as a fallback.
        try:
            try:
                import taskflow  # noqa: F401
            except ImportError:
                import hopewell  # noqa: F401
        except Exception:
            raise RuntimeError(
                "canon amend task requires `taskflow` (phase 1B). Install "
                "canon[taskflow] or run `canon amend spec|plan|ns|constitution` "
                "instead."
            )
        # TaskFlow exists; we still don't own task amend authoring in 1C.
        raise NotImplementedError(
            "canon amend task is provided by phase 1B (canon/tasks.py). "
            "1C only wires the CLI subcommand -- the implementation lives in 1B."
        )

    if canonical not in _SCHEMA_BY_TYPE:
        raise ValueError(f"unsupported doc-type for amend: {doc_type}")
    schema = _SCHEMA_BY_TYPE[canonical]
    prior = load_prior(root, canonical, identifier)

    # If pedia hasn't indexed yet, do an incremental refresh so we can
    # capture the prior block-id before mutating the file on disk.
    if prior.block_id is None:
        try:
            pb.refresh(root)
            prior.block_id = _block_id_for_path(root, prior.path)
        except Exception:
            pass

    # Build the answer feed.
    if overrides is not None:
        answers = canned_amendment_answers(prior.fields, overrides, schema)
        ask = canned_ask(answers)
        from canon.interview import silent_say
        result = run_interview(schema, ask=ask, say=silent_say(),
                               max_iter=max_iter)
    else:
        from canon.interview import _default_say
        ask = _seeded_ask_for(prior.fields, schema, say or _default_say)
        result = run_interview(schema, ask=ask, max_iter=max_iter,
                               say=say or _default_say)

    # Render the new block body using the same renderer as `canon specify`.
    new_body = render_block(canonical, result, slug=prior.slug)
    new_body = _append_amendment_history(new_body, prior.block_id, prior.path)

    # Write the new block to the SAME on-disk path -- Pedia's
    # content-hash IDs change, the doc_path is stable. The old block
    # remains queryable only via the wiki-link / supersedes edge we
    # write below pointing at the prior block-id (still in the index
    # until next refresh; we re-insert that edge after refresh).
    new_path = prior.path
    if dry_run:
        return {
            "dry_run": True,
            "doc_type": canonical,
            "slug": prior.slug,
            "prior_block_id": prior.block_id,
            "prior_path": str(prior.path),
            "new_body": new_body,
        }

    # Stash the old content into an .amended-history file BEFORE overwriting,
    # so the canonical text of every prior amendment stays on disk for
    # forensic review (Pedia indexes only the latest version on disk).
    history_path = prior.path.with_suffix(prior.path.suffix + ".amended-history")
    today = dt.date.today().isoformat()
    history_entry = (
        f"\n\n<!-- ===== amended {today} -- prior block id: "
        f"{prior.block_id or 'unknown'} ===== -->\n\n"
    )
    history_path.write_text(
        (history_path.read_text(encoding="utf-8") if history_path.exists() else "")
        + history_entry
        + prior.path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    new_path.write_text(new_body, encoding="utf-8")

    # Refresh Pedia so the new block-id is computable.
    pb.refresh(root)
    new_block_id = _block_id_for_path(root, new_path)

    # Write the supersedes edge (new -> prior) into the refs table.
    edge_written = False
    if new_block_id and prior.block_id and new_block_id != prior.block_id:
        edge_written = write_supersedes_edge(root, new_block_id, prior.block_id)

    # Drift surfacing.
    drift = maybe_surface_drift(root, canonical, prior.slug)

    return {
        "dry_run": False,
        "doc_type": canonical,
        "slug": prior.slug,
        "prior_block_id": prior.block_id,
        "new_block_id": new_block_id,
        "prior_path": str(prior.path),
        "new_path": str(new_path),
        "history_path": str(history_path),
        "edge_written": edge_written,
        "drift": drift,
    }


# ---------------------------------------------------------------------------
# `--regenerate --strategy <name>` -- swap a plan's work items in place
# ---------------------------------------------------------------------------


def amend_regenerate(
    root: Path,
    doc_type: str,
    identifier: str,
    *,
    strategy: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Re-run the decompose strategy for an existing plan.

    Only `doc_type == "plan"` is supported (regenerating a spec or
    constitution doesn't have well-defined semantics yet -- those are
    text-only artifacts). The plan markdown is NOT rewritten; we just
    re-derive the work items under the new strategy. Existing
    canon-marked work items for OTHER strategies are left in place
    (their (slug, strategy, index) keys differ); items for THIS
    strategy that already exist are skipped via the dispatch layer's
    idempotency.

    Returns a dict suitable for the CLI to print (the
    `DecomposeResult` is included under `result`).
    """
    canonical = _canonicalize_type(doc_type)
    if canonical != "plan":
        raise ValueError(
            f"--regenerate is only supported for `plan` (got {doc_type!r}); "
            "specs / north-stars / constitution chapters are text-only artifacts. "
            "Use plain `canon amend` for those."
        )
    # Locate the plan.
    plan_path = _resolve_prior_path(root, "plan", identifier)
    if plan_path is None:
        raise FileNotFoundError(
            f"no plan found for identifier {identifier!r} under {root / '.pedia'}"
        )

    # Late imports keep amend.py loadable without taskflow installed.
    from canon.decompose.base import parse_plan
    from canon.decompose.dispatch import run_strategy

    plan = parse_plan(plan_path)
    if not plan.decomposition:
        raise ValueError(
            f"plan {plan_path} has no decomposition steps; nothing to regenerate."
        )

    result, resolved_strategy, source = run_strategy(
        root=root, plan=plan, cli_strategy=strategy, dry_run=dry_run,
    )
    return {
        "dry_run": dry_run,
        "doc_type": "plan",
        "slug": plan.spec_slug,
        "regenerated": True,
        "strategy": resolved_strategy,
        "strategy_source": source,
        "result": result,
    }
