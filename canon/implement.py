"""canon implement -- dispatch a task via the orchestrator (or directly).

Wiring (from canon.cli):
    cmd_implement(args)  -- entry point for `canon implement <task-id>`

Behavior (phase 1B):
1. Loads the Hopewell project + the named task node.
2. Detects whether `@orchestrator` exists in the project's flow network
   (executor id `orchestrator`).
3. Assembles a context bundle:
   - The task itself + its component_data (incl. spec-input citations)
   - The cited spec slices (full markdown of `.pedia/specs/<slug>/spec.md`)
   - The cited plan section
   - All `universal_context: true` Pedia blocks (north-stars + constitution)
   - Mercator data, if a `.mercator/` is present in the repo (best-effort
     -- we just attach the JSON dump without parsing).
4. Pushes the work item via `flow.push(project, node_id, to_executor)`:
   - If `@orchestrator` is present: push to "orchestrator".
   - Else: push to the task's declared `executor-suggestion.role`.
   The bundle is attached as the push `artifact` (the path to a temp
   file written under `.canon/dispatches/<node_id>.md`).

ONE task at a time in 1B. Wave-dispatch is phase 1C.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from canon import config as config_mod
from canon import pedia_bridge as pb


def _load_hopewell():
    """Try the new taskflow package; fall back to legacy hopewell."""
    try:
        try:
            from taskflow import project as hw_project  # type: ignore
            from taskflow import flow as hw_flow        # type: ignore
            from taskflow import network as hw_network  # type: ignore
        except ImportError:
            from hopewell import project as hw_project  # type: ignore  (legacy)
            from hopewell import flow as hw_flow        # type: ignore  (legacy)
            from hopewell import network as hw_network  # type: ignore  (legacy)
        return hw_project, hw_flow, hw_network
    except Exception as e:
        raise RuntimeError(
            f"taskflow / hopewell is not importable ({e}); install with "
            "`pip install taskflow` to use `canon implement`"
        )


# ---------------------------------------------------------------------------
# Orchestrator detection
# ---------------------------------------------------------------------------


ORCHESTRATOR_EXECUTOR_ID = "@orchestrator"
# Hopewell's default template wires `@orchestrator`; older projects may
# spell it without the leading `@` so we accept either as a match.
ORCHESTRATOR_ALIASES = ("@orchestrator", "orchestrator")


def has_orchestrator(project) -> bool:
    """True if the project's flow network declares an orchestrator executor."""
    try:
        _, _, hw_network = _load_hopewell()
        net = hw_network.load_network(project.root)
        return any(a in net.executors for a in ORCHESTRATOR_ALIASES)
    except Exception:
        return False


def _orchestrator_id(project) -> Optional[str]:
    try:
        _, _, hw_network = _load_hopewell()
        net = hw_network.load_network(project.root)
    except Exception:
        return None
    for alias in ORCHESTRATOR_ALIASES:
        if alias in net.executors:
            return alias
    return None


# ---------------------------------------------------------------------------
# Context-bundle assembly
# ---------------------------------------------------------------------------


@dataclass
class Bundle:
    node_id: str
    target_executor: str
    via_orchestrator: bool
    sections: List[Tuple[str, str]] = field(default_factory=list)   # (heading, body)
    bundle_path: Optional[Path] = None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return f"_(could not read {path}: missing)_"


def _universal_blocks(root: Path) -> List[Tuple[str, str]]:
    """Return (path, body) for every Pedia block flagged universal_context.

    We just iterate north-stars/ and constitution/ and dump the whole
    file -- those folders are universal-context by convention.
    """
    out: List[Tuple[str, str]] = []
    for folder in ("north-stars", "constitution"):
        d = root / ".pedia" / folder
        if not d.is_dir():
            continue
        for fp in sorted(d.glob("*.md")):
            out.append((str(fp.relative_to(root)), _read(fp)))
    return out


def _mercator_dump(root: Path) -> Optional[str]:
    """If .mercator/ exists, attach a small index summary."""
    m = root / ".mercator"
    if not m.is_dir():
        return None
    out_lines = []
    for fp in sorted(m.rglob("*.json")):
        try:
            text = fp.read_text(encoding="utf-8")
            # Don't dump the whole thing if huge -- truncate.
            if len(text) > 8_000:
                text = text[:8_000] + "\n_(truncated)_"
            out_lines.append(f"### {fp.relative_to(root)}\n\n```json\n{text}\n```\n")
        except Exception:
            continue
    if not out_lines:
        return None
    return "\n".join(out_lines)


def assemble_bundle(project, node, *, root: Path, via_orchestrator: bool,
                    target_executor: str) -> Bundle:
    """Build the dispatch bundle for `node` and write it under .canon/dispatches/."""
    bundle = Bundle(
        node_id=node.id,
        target_executor=target_executor,
        via_orchestrator=via_orchestrator,
    )

    # Header.
    bundle.sections.append(
        ("Task",
         f"- **id**: {node.id}\n"
         f"- **title**: {node.title}\n"
         f"- **status**: {node.status.value if hasattr(node.status, 'value') else node.status}\n"
         f"- **priority**: {node.priority}\n"
         f"- **components**: {', '.join(node.components) or '_(none)_'}\n"))

    # spec-input citations + their resolved bodies.
    spec_input = (node.component_data or {}).get("spec-input") or {}
    cited_specs = spec_input.get("specs", []) or []
    cite_lines = []
    cited_bodies: List[Tuple[str, str]] = []
    for entry in cited_specs:
        path = entry.get("path", "")
        slices = entry.get("slices", []) or []
        cite_lines.append(f"- {path}  slices: {slices or '<whole>'}")
        full = root / ".pedia" / path
        cited_bodies.append((str(full.relative_to(root)), _read(full)))
    if cite_lines:
        bundle.sections.append(("Citations (spec-input)", "\n".join(cite_lines)))
    for (lbl, body) in cited_bodies:
        bundle.sections.append((f"Cited block: {lbl}", body))

    # Universal context (north-stars + constitution).
    for (lbl, body) in _universal_blocks(root):
        bundle.sections.append((f"Universal context: {lbl}", body))

    # Mercator (optional).
    merc = _mercator_dump(root)
    if merc:
        bundle.sections.append(("Mercator data", merc))

    # Component-data summary (for the executor's reference).
    cd_pretty = json.dumps(node.component_data or {}, indent=2, default=str)
    bundle.sections.append(("Node component_data", f"```json\n{cd_pretty}\n```"))

    # Write to disk.
    dispatch_dir = root / ".canon" / "dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    dst = dispatch_dir / f"{node.id}.md"
    parts = [
        f"# Canon dispatch -- {node.id}",
        f"_target: {target_executor}  via_orchestrator: {via_orchestrator}_",
        f"_generated: {dt.datetime.now(dt.timezone.utc).isoformat()}_",
        "",
    ]
    for (h, body) in bundle.sections:
        parts.append(f"## {h}")
        parts.append("")
        parts.append(body.rstrip())
        parts.append("")
    dst.write_text("\n".join(parts), encoding="utf-8")
    bundle.bundle_path = dst
    return bundle


# ---------------------------------------------------------------------------
# Direct dispatch fallback
# ---------------------------------------------------------------------------


def _direct_target(project, node) -> Optional[str]:
    """Pick a fallback executor when @orchestrator is absent.

    Strategy:
      1. node.component_data["executor-suggestion"]["role"] -- if it
         names an executor in the network, use it.
      2. Else first executor in the network (deterministic -- sorted).
      3. Else None (caller errors out).
    """
    try:
        _, _, hw_network = _load_hopewell()
        net = hw_network.load_network(project.root)
    except Exception:
        return None

    suggestion = ((node.component_data or {}).get("executor-suggestion") or {}).get("role")
    if suggestion and suggestion in net.executors:
        return suggestion

    if net.executors:
        return sorted(net.executors.keys())[0]
    return None


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def cmd_implement(args) -> int:
    root = config_mod.find_root(Path.cwd()) or Path.cwd()
    if not (root / ".canon").is_dir():
        sys.stderr.write("not a canon project (no .canon/ here or above)\n")
        return 2
    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        sys.stderr.write(msg + "\n")
        return 2

    hw_project, hw_flow, _ = _load_hopewell()
    try:
        project = hw_project.Project.load(start=root)
    except Exception as e:
        sys.stderr.write(f"hopewell project not initialized: {e}\n")
        return 2

    if not project.has_node(args.task_id):
        sys.stderr.write(f"unknown task id: {args.task_id}\n")
        return 2

    node = project.node(args.task_id)
    via_orch = has_orchestrator(project)
    if via_orch:
        target = _orchestrator_id(project) or ORCHESTRATOR_EXECUTOR_ID
    else:
        target = _direct_target(project, node)
        if not target:
            sys.stderr.write(
                "no orchestrator and no executors registered in the flow network; "
                "run `hopewell network defaults bootstrap` and retry.\n"
            )
            return 2

    bundle = assemble_bundle(
        project, node, root=root, via_orchestrator=via_orch, target_executor=target,
    )

    if args.dry_run:
        sys.stdout.write(
            f"canon implement (dry-run): would push {node.id} -> {target} "
            f"(via_orchestrator={via_orch})\n"
        )
        sys.stdout.write(f"  bundle: {bundle.bundle_path}\n")
        return 0

    try:
        rec = hw_flow.push(
            project, node.id, target,
            artifact=str(bundle.bundle_path) if bundle.bundle_path else None,
            reason=f"canon implement: dispatched via {'orchestrator' if via_orch else 'direct'}",
            actor="canon",
        )
    except Exception as e:
        sys.stderr.write(f"flow.push failed: {e}\n")
        return 1

    sys.stdout.write(
        f"canon implement: pushed {node.id} -> {target} "
        f"(via_orchestrator={via_orch})\n"
    )
    sys.stdout.write(f"  bundle: {bundle.bundle_path}\n")
    sys.stdout.write(f"  push  : {json.dumps(rec, default=str)}\n")
    return 0
