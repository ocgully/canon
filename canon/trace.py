"""Canon trace -- walk the citation graph up or down from a block / task.

CLI:
    canon trace <id> --up | --down [--depth N] [--format text|json|mermaid]

The `<id>` may be:
    * a Pedia block id (16-hex content-hash)            e.g.  ab12cd34ef567890
    * a spec slug                                        e.g.  001-cache-layer
    * a north-star slug                                  e.g.  agent-first-tooling
    * a Hopewell task id                                 e.g.  HW-0042

The traversal:

  --up   walks edges this id CITES (spec -> north-star, plan -> spec,
         task -> plan block).
  --down walks edges that CITE this id (downstream consumers).

Pedia walks use `pedia.trace.walk(direction='up'|'down', depth=N)`.
Hopewell-task walks compose Hopewell node-edge traversal with a Pedia
walk anchored at the task's cited plan-block (via the spec-input
ref). If Hopewell is missing we degrade to Pedia-only.

Leaf nodes (no further edges in the requested direction) are emitted
with a `[leaf]` marker so the user can spot uncited (orphan) entities.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# id resolution
# ---------------------------------------------------------------------------


@dataclass
class ResolvedId:
    kind: str       # "pedia-block" | "hopewell-task"
    pedia_id: Optional[str] = None
    task_id: Optional[str] = None
    label: str = ""
    doc_path: Optional[str] = None


def _looks_like_block_id(s: str) -> bool:
    return len(s) == 16 and all(c in "0123456789abcdef" for c in s.lower())


def _looks_like_hopewell_id(s: str) -> bool:
    return s.upper().startswith("HW-")


def _resolve_pedia_id(root: Path, identifier: str) -> Optional[Tuple[str, str]]:
    """Try every reasonable resolution of `identifier` to a Pedia
    block-id. Returns (block_id, doc_path) or None.
    """
    try:
        from pedia import config as pcfg
        from pedia import index as idx
    except Exception:
        return None
    db = pcfg.db_path(root)
    if not db.exists():
        return None
    conn = idx.connect(db)
    try:
        # 1. literal block-id
        if _looks_like_block_id(identifier):
            row = conn.execute(
                "SELECT id, doc_path FROM blocks WHERE id = ?",
                (identifier,),
            ).fetchone()
            if row:
                return row["id"], row["doc_path"]
        # 2. doc-path (spec slug + plan/spec convention)
        candidates = [
            f"specs/{identifier}/spec.md",
            f"specs/{identifier}/plan.md",
            f"north-stars/{identifier}.md",
            f"constitution/{identifier}.md",
            identifier,
        ]
        for cp in candidates:
            row = conn.execute(
                "SELECT id, doc_path FROM blocks WHERE doc_path = ? "
                "ORDER BY line_start LIMIT 1",
                (cp.replace("\\", "/"),),
            ).fetchone()
            if row:
                return row["id"], row["doc_path"]
        # 3. wildcard spec lookup: bare title-slug
        row = conn.execute(
            "SELECT id, doc_path FROM blocks WHERE doc_path LIKE ? "
            "ORDER BY line_start LIMIT 1",
            (f"specs/%-{identifier}/spec.md",),
        ).fetchone()
        if row:
            return row["id"], row["doc_path"]
        return None
    finally:
        conn.close()


def resolve(root: Path, identifier: str) -> ResolvedId:
    if _looks_like_hopewell_id(identifier):
        return ResolvedId(
            kind="hopewell-task",
            task_id=identifier.upper(),
            label=identifier.upper(),
        )
    pid = _resolve_pedia_id(root, identifier)
    if pid is None:
        return ResolvedId(kind="pedia-block", pedia_id=None, label=identifier)
    block_id, doc_path = pid
    return ResolvedId(
        kind="pedia-block",
        pedia_id=block_id,
        label=block_id,
        doc_path=doc_path,
    )


# ---------------------------------------------------------------------------
# Pedia walk wrapper
# ---------------------------------------------------------------------------


def walk_pedia(root: Path, block_id: str, direction: str,
               depth: int) -> List[Dict[str, Any]]:
    """Thin wrapper around `pedia.trace.walk`. Adds a `leaf` flag."""
    try:
        from pedia import trace as ptrace
    except Exception:
        return []
    rows = ptrace.walk(root, block_id, direction, depth=depth)

    # Annotate each row with whether it had any edges in the requested direction.
    leaf_ids = _compute_leaves(root, [r["id"] for r in rows], direction)
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r["id"],
            "depth": r["depth"],
            "via": r.get("via"),
            "doc_path": r.get("doc_path"),
            "heading_slug": r.get("heading_slug"),
            "leaf": r["id"] in leaf_ids,
        })
    return out


def _compute_leaves(root: Path, ids: List[str], direction: str) -> Set[str]:
    if not ids:
        return set()
    try:
        from pedia import config as pcfg
        from pedia import index as idx
    except Exception:
        return set()
    conn = idx.connect(pcfg.db_path(root))
    try:
        col = "src_id" if direction == "up" else "dst_id"
        other = "dst_id" if direction == "up" else "src_id"
        leaves: Set[str] = set()
        for bid in ids:
            row = conn.execute(
                f"SELECT 1 FROM refs WHERE {col} = ? AND {other} IS NOT NULL LIMIT 1",
                (bid,),
            ).fetchone()
            if row is None:
                leaves.add(bid)
        return leaves
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hopewell walk (best-effort)
# ---------------------------------------------------------------------------


def walk_hopewell(root: Path, task_id: str, direction: str,
                  depth: int) -> List[Dict[str, Any]]:
    """Walk Hopewell's node-edge graph for a task id.

    --up  : transitive blockers / requires (what this task depends on)
    --down: transitive blocks (what depends on this task)

    Falls back gracefully -- if neither taskflow nor hopewell is
    importable, returns [].
    """
    try:
        try:
            import taskflow  # noqa: F401
        except ImportError:
            import hopewell  # noqa: F401  (legacy)
    except Exception:
        return []
    # Try a public-ish API: taskflow.query.deps_transitive(...).
    try:
        try:
            from taskflow import query as hquery  # type: ignore
        except ImportError:
            from hopewell import query as hquery  # type: ignore  (legacy)
    except Exception:
        return []
    fn = getattr(hquery, "deps_transitive", None) or getattr(hquery, "deps", None)
    if fn is None:
        return []
    try:
        rows = fn(root, task_id, direction=direction, depth=depth)
    except TypeError:
        # signature variant: (root, id) only
        try:
            rows = fn(root, task_id)
        except Exception:
            return []
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append({
                "id": r.get("id") or r.get("node_id"),
                "depth": r.get("depth", 0),
                "via": r.get("via", ""),
                "title": r.get("title"),
                "status": r.get("status"),
            })
    return out


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


@dataclass
class TraceResult:
    direction: str
    root_id: str
    pedia_walk: List[Dict[str, Any]] = field(default_factory=list)
    hopewell_walk: List[Dict[str, Any]] = field(default_factory=list)
    resolved: Optional[ResolvedId] = None


def run_trace(root: Path, identifier: str, *, direction: str,
              depth: int = 5) -> TraceResult:
    if direction not in {"up", "down"}:
        raise ValueError("direction must be 'up' or 'down'")
    resolved = resolve(root, identifier)
    pedia_rows: List[Dict[str, Any]] = []
    hopewell_rows: List[Dict[str, Any]] = []
    if resolved.kind == "hopewell-task":
        hopewell_rows = walk_hopewell(root, resolved.task_id or identifier,
                                      direction, depth)
        # Try also to walk Pedia from the task's cited plan-block, if we
        # can find a Hopewell node-file that points to one. Best-effort.
        plan_block_id = _hopewell_task_to_plan_block(root, resolved.task_id or identifier)
        if plan_block_id:
            pedia_rows = walk_pedia(root, plan_block_id, direction, depth)
    else:
        if resolved.pedia_id:
            pedia_rows = walk_pedia(root, resolved.pedia_id, direction, depth)
    return TraceResult(
        direction=direction,
        root_id=identifier,
        pedia_walk=pedia_rows,
        hopewell_walk=hopewell_rows,
        resolved=resolved,
    )


def _hopewell_task_to_plan_block(root: Path, task_id: str) -> Optional[str]:
    """Best-effort: ask Hopewell what plan-block this task cites.

    Phase 1B is expected to record this as a `spec-input` ref on the
    Hopewell node. We just call out and parse; failure is non-fatal.
    """
    try:
        import subprocess
        proc = subprocess.run(
            ["hopewell", "show", task_id, "--format", "json"],
            cwd=str(root), capture_output=True, text=True, check=False, timeout=10,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        # Hopewell may store this under different key names; try a few.
        for k in ("spec_input_block_id", "plan_block_id", "cited_block_id"):
            v = data.get(k)
            if v:
                return str(v)
        refs = data.get("refs") or data.get("spec_inputs") or []
        for r in refs if isinstance(refs, list) else []:
            if isinstance(r, dict):
                bid = r.get("block_id") or r.get("dst_id")
                if bid:
                    return str(bid)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# formatters
# ---------------------------------------------------------------------------


def format_text(tr: TraceResult) -> str:
    lines: List[str] = []
    arrow = "->" if tr.direction == "up" else "<-"
    lines.append(f"=== canon trace --{tr.direction} {tr.root_id} ===")
    if tr.resolved and tr.resolved.kind == "hopewell-task":
        lines.append(f"resolved: hopewell task {tr.resolved.task_id}")
    elif tr.resolved and tr.resolved.pedia_id:
        lines.append(f"resolved: pedia block {tr.resolved.pedia_id}"
                     + (f" ({tr.resolved.doc_path})" if tr.resolved.doc_path else ""))
    else:
        lines.append(f"resolved: nothing (id '{tr.root_id}' not found)")
    if tr.pedia_walk:
        lines.append("")
        lines.append(f"pedia walk (direction {arrow}):")
        for r in tr.pedia_walk:
            indent = "  " * r["depth"]
            via = r.get("via")
            via_s = "" if not via or via == "self" else f"  [via {via}]"
            heading = r.get("heading_slug") or "(body)"
            doc = r.get("doc_path") or ""
            leaf = "  [leaf]" if r.get("leaf") else ""
            lines.append(f'{indent}[block:{r["id"]}] {doc} @ "{heading}"{via_s}{leaf}')
    if tr.hopewell_walk:
        lines.append("")
        lines.append(f"hopewell walk (direction {arrow}):")
        for r in tr.hopewell_walk:
            indent = "  " * (r.get("depth") or 0)
            via = r.get("via") or ""
            via_s = f"  [via {via}]" if via else ""
            title = r.get("title") or ""
            status = r.get("status") or ""
            lines.append(f'{indent}{r["id"]} {title} ({status}){via_s}')
    if not tr.pedia_walk and not tr.hopewell_walk:
        lines.append("")
        lines.append("(no edges found in this direction)")
    return "\n".join(lines) + "\n"


def format_json(tr: TraceResult) -> str:
    return json.dumps(
        {
            "direction": tr.direction,
            "root_id": tr.root_id,
            "resolved": _resolved_to_dict(tr.resolved),
            "pedia_walk": tr.pedia_walk,
            "hopewell_walk": tr.hopewell_walk,
        },
        indent=2,
    )


def _resolved_to_dict(r: Optional[ResolvedId]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {
        "kind": r.kind,
        "pedia_id": r.pedia_id,
        "task_id": r.task_id,
        "label": r.label,
        "doc_path": r.doc_path,
    }


def format_mermaid(tr: TraceResult) -> str:
    """Render the trace as a small, focused Mermaid diagram."""
    lines: List[str] = ["```mermaid", "graph TD"]
    arrow = "-->"  # citation direction
    seen: Set[str] = set()

    def node(nid: str, label: str) -> None:
        if nid in seen:
            return
        seen.add(nid)
        # Mermaid IDs can't have hyphens at the start; prefix all with `n_`.
        safe_label = label.replace('"', "'")
        lines.append(f'  n_{nid}["{safe_label}"]')

    if tr.resolved and tr.resolved.pedia_id:
        node(tr.resolved.pedia_id, f"{tr.resolved.pedia_id}\\n{tr.resolved.doc_path or ''}")
    elif tr.resolved and tr.resolved.task_id:
        node(tr.resolved.task_id, tr.resolved.task_id)

    # Pedia: re-derive parent from `via` ordering: each row knows its
    # immediate predecessor only via depth+via. We rebuild a parent
    # pointer using the BFS frontier shape (depth-1 -> depth).
    parent_by_depth: Dict[int, str] = {}
    if tr.pedia_walk:
        for r in tr.pedia_walk:
            d = r["depth"]
            nid = r["id"]
            label = f"{nid}\\n{r.get('doc_path') or ''}"
            node(nid, label)
            if d > 0:
                pid = parent_by_depth.get(d - 1)
                if pid:
                    if tr.direction == "up":
                        lines.append(f'  n_{pid} {arrow}|{r.get("via","cites")}| n_{nid}')
                    else:
                        lines.append(f'  n_{nid} {arrow}|{r.get("via","cites")}| n_{pid}')
            parent_by_depth[d] = nid
    if tr.hopewell_walk:
        for r in tr.hopewell_walk:
            nid = r["id"] or "?"
            node(nid, f"{nid}\\n{r.get('title','')}")

    lines.append("```")
    return "\n".join(lines) + "\n"


def format_result(tr: TraceResult, fmt: str) -> str:
    if fmt == "text":
        return format_text(tr)
    if fmt == "json":
        return format_json(tr)
    if fmt == "mermaid":
        return format_mermaid(tr)
    raise ValueError(f"unknown format: {fmt}")
