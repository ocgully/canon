"""Canon graph -- emit a Mermaid diagram of the project's citation graph.

CLI:
    canon graph                                # full project graph
    canon graph --for <id> --depth N           # neighborhood-of N around <id>
    canon graph --out <path>                   # write to file instead of stdout

Node colors track doc-type:

    north-star    -> classDef ns
    constitution  -> classDef constitution
    spec          -> classDef spec
    plan          -> classDef plan
    decision      -> classDef decision
    task          -> classDef task   (Hopewell, when present)

Edge labels track ref `kind`: cites | supersedes | requires | blocks.
The Pedia `refs` table only carries cites + supersedes today; the
`requires` / `blocks` labels appear only when Hopewell-task overlay
is active. Phase 1C ships the Pedia overlay; the Hopewell overlay is
best-effort (no-ops if Hopewell isn't installed).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# data shape
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    nid: str            # mermaid-safe id (we'll prefix with n_)
    label: str
    doc_type: str       # north-star / constitution / spec / plan / decision / task / unknown
    raw_path: Optional[str] = None


@dataclass
class GraphEdge:
    src: str
    dst: str
    kind: str   # cites | supersedes | requires | blocks


@dataclass
class CitationGraph:
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def _doc_type_for(row: sqlite3.Row) -> str:
    dt = (row["doc_type"] or "").strip()
    if dt in {"north-star", "constitution", "spec", "plan", "decision"}:
        return dt
    return "unknown"


def _short_label(row: sqlite3.Row) -> str:
    head = row["heading_slug"] or "(body)"
    path = row["doc_path"] or ""
    # Keep labels compact -- mermaid renders them in a small box.
    short_path = path.split("/")[-1] if path else ""
    return f"{row['id'][:8]}\\n{short_path}\\n#{head}"


def _connect(root: Path) -> Optional[sqlite3.Connection]:
    try:
        from pedia import config as pcfg
        from pedia import index as idx
    except Exception:
        return None
    db = pcfg.db_path(root)
    if not db.exists():
        return None
    return idx.connect(db)


def build_full(root: Path) -> CitationGraph:
    """All blocks + all ref edges in the project."""
    g = CitationGraph()
    conn = _connect(root)
    if conn is None:
        return g
    try:
        for r in conn.execute(
            "SELECT id, doc_path, doc_type, heading_slug FROM blocks ORDER BY doc_path, line_start"
        ):
            g.nodes[r["id"]] = GraphNode(
                nid=r["id"],
                label=_short_label(r),
                doc_type=_doc_type_for(r),
                raw_path=r["doc_path"],
            )
        for r in conn.execute(
            "SELECT src_id, dst_id, kind FROM refs WHERE dst_id IS NOT NULL"
        ):
            if r["src_id"] not in g.nodes:
                continue  # source vanished -- skip
            if r["dst_id"] not in g.nodes:
                # Target block has been superseded / deleted but the
                # ref still records the relationship. Emit a ghost
                # node so the supersedes / amends edge stays visible.
                if r["kind"] in {"supersedes", "amends"}:
                    g.nodes[r["dst_id"]] = GraphNode(
                        nid=r["dst_id"],
                        label=f"{r['dst_id'][:8]}\\n(superseded)",
                        doc_type="unknown",
                        raw_path=None,
                    )
                else:
                    continue
            g.edges.append(GraphEdge(
                src=r["src_id"], dst=r["dst_id"], kind=r["kind"]
            ))
    finally:
        conn.close()
    _maybe_overlay_hopewell(root, g)
    return g


def build_neighborhood(root: Path, focus_id: str, depth: int) -> CitationGraph:
    """BFS depth-N neighborhood (both directions) around `focus_id`."""
    g = CitationGraph()
    conn = _connect(root)
    if conn is None:
        return g
    try:
        # Resolve identifier to a block-id if not already one.
        from canon.trace import _resolve_pedia_id  # type: ignore
        pid = _resolve_pedia_id(root, focus_id)
        if pid is None:
            return g
        block_id, _ = pid
        visited: Set[str] = set()
        frontier: List[Tuple[str, int]] = [(block_id, 0)]
        # Collect node rows + edges along the way.
        while frontier:
            cur, d = frontier.pop(0)
            if cur in visited:
                continue
            visited.add(cur)
            row = conn.execute(
                "SELECT id, doc_path, doc_type, heading_slug FROM blocks WHERE id = ?",
                (cur,),
            ).fetchone()
            if row is None:
                continue
            g.nodes[cur] = GraphNode(
                nid=cur, label=_short_label(row),
                doc_type=_doc_type_for(row),
                raw_path=row["doc_path"],
            )
            if d >= depth:
                continue
            # outbound
            for r in conn.execute(
                "SELECT dst_id, kind FROM refs WHERE src_id = ? AND dst_id IS NOT NULL",
                (cur,),
            ):
                g.edges.append(GraphEdge(src=cur, dst=r["dst_id"], kind=r["kind"]))
                if r["dst_id"] not in visited:
                    frontier.append((r["dst_id"], d + 1))
            # inbound
            for r in conn.execute(
                "SELECT src_id, kind FROM refs WHERE dst_id = ?",
                (cur,),
            ):
                g.edges.append(GraphEdge(src=r["src_id"], dst=cur, kind=r["kind"]))
                if r["src_id"] not in visited:
                    frontier.append((r["src_id"], d + 1))
    finally:
        conn.close()
    return g


def _maybe_overlay_hopewell(root: Path, g: CitationGraph) -> None:
    """Add Hopewell task nodes + edges to the graph, if Hopewell is present."""
    try:
        proc = subprocess.run(
            ["hopewell", "query", "graph"],
            cwd=str(root), capture_output=True, text=True,
            check=False, timeout=30,
        )
    except Exception:
        return
    if proc.returncode != 0 or not proc.stdout.strip():
        return
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return
    nodes = data.get("nodes") if isinstance(data, dict) else None
    edges = data.get("edges") if isinstance(data, dict) else None
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = n.get("id") or n.get("node_id")
        if not nid:
            continue
        label = f"{nid}\\n{(n.get('title') or '')[:30]}"
        g.nodes[nid] = GraphNode(
            nid=nid, label=label, doc_type="task", raw_path=None,
        )
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = e.get("src") or e.get("from")
        dst = e.get("dst") or e.get("to")
        kind = (e.get("kind") or e.get("type") or "blocks").lower()
        if src and dst and src in g.nodes and dst in g.nodes:
            g.edges.append(GraphEdge(src=src, dst=dst, kind=kind))


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


_CLASS_DEFS = """\
  classDef ns fill:#fde68a,stroke:#92400e,color:#1f2937;
  classDef constitution fill:#fecaca,stroke:#7f1d1d,color:#1f2937;
  classDef spec fill:#bfdbfe,stroke:#1e3a8a,color:#1f2937;
  classDef plan fill:#bbf7d0,stroke:#14532d,color:#1f2937;
  classDef decision fill:#e9d5ff,stroke:#581c87,color:#1f2937;
  classDef task fill:#fbcfe8,stroke:#831843,color:#1f2937;
  classDef unknown fill:#e5e7eb,stroke:#374151,color:#1f2937;
"""


# Map Pedia doc_type values to mermaid-safe classDef names.
_CSS_CLASS = {
    "north-star": "ns",
    "constitution": "constitution",
    "spec": "spec",
    "plan": "plan",
    "decision": "decision",
    "task": "task",
    "unknown": "unknown",
}


def to_mermaid(g: CitationGraph) -> str:
    lines: List[str] = ["```mermaid", "graph TD"]
    # Nodes
    for nid, n in g.nodes.items():
        safe_label = n.label.replace('"', "'")
        css = _CSS_CLASS.get(n.doc_type or "unknown", "unknown")
        lines.append(f'  n_{nid}["{safe_label}"]:::{css}')
    # Edges
    seen_edges: Set[Tuple[str, str, str]] = set()
    for e in g.edges:
        key = (e.src, e.dst, e.kind)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        # Different kinds get different arrow styles.
        if e.kind == "supersedes":
            lines.append(f'  n_{e.src} -. supersedes .-> n_{e.dst}')
        elif e.kind == "blocks":
            lines.append(f'  n_{e.src} ==>|blocks| n_{e.dst}')
        elif e.kind == "requires":
            lines.append(f'  n_{e.src} -->|requires| n_{e.dst}')
        else:
            lines.append(f'  n_{e.src} -->|{e.kind}| n_{e.dst}')
    lines.append(_CLASS_DEFS.rstrip())
    lines.append("```")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# top-level entry
# ---------------------------------------------------------------------------


def render_graph(root: Path, *, focus: Optional[str] = None,
                 depth: int = 3) -> str:
    if focus:
        g = build_neighborhood(root, focus, depth)
    else:
        g = build_full(root)
    if not g.nodes:
        return "```mermaid\ngraph TD\n  empty[\"(no blocks indexed)\"]\n```\n"
    return to_mermaid(g)
