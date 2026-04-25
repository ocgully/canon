"""Dispatch layer: turn a strategy's `StrategyResult` into reality.

`run_strategy()` is the single entry point used by both:

  - the `canon decompose` CLI command, and
  - `canon amend --regenerate --strategy <name>` (which re-runs a
    strategy in place; existing canon-marked work items are
    preserved on a (slug, kind, strategy_index) match for idempotency).

When `.hopewell/` is initialized in the project, work items become
Hopewell nodes carrying:

  component_data["spec-input"]            -> citations into the spec + plan
  component_data["executor-suggestion"]   -> {"role": "agent|service|gate"}
  component_data["sizing"]                -> {"size": "...", "estimate_hours": N}
  component_data["canon"]                 -> {"spec_slug": ..., "strategy": ...,
                                              "strategy_index": N, ...}
  component_data["canon"]["strategy_meta"] -> per-strategy metadata blob

When Hopewell isn't initialized -- or `--dry-run` is set -- we emit the
same shape as plain JSON to stdout and create no nodes. This keeps the
strategies usable in environments that haven't adopted Hopewell yet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from canon import config as config_mod
from canon import pedia_bridge as pb
from canon.decompose.base import (
    ParsedPlan,
    StrategyResult,
    WorkItem,
    parse_plan,
    sizing_estimate,
)
from canon.decompose.resolver import KNOWN_STRATEGIES, resolve_strategy
from canon.decompose.strategies import REGISTRY


# ---------------------------------------------------------------------------
# Hopewell loader (lazy)
# ---------------------------------------------------------------------------


def _load_hopewell():
    try:
        from hopewell import project as hw_project  # type: ignore
        from hopewell.model import EdgeKind, NodeStatus  # type: ignore
        return hw_project, EdgeKind, NodeStatus
    except Exception as e:
        raise RuntimeError(
            f"hopewell is not importable ({e}); install with "
            "`pip install hopewell` to use `canon decompose` against a Hopewell project"
        )


def _hopewell_present(root: Path) -> bool:
    return (root / ".hopewell").is_dir()


# ---------------------------------------------------------------------------
# Materialization result (kept name-compatible with the old TasksResult)
# ---------------------------------------------------------------------------


@dataclass
class DecomposeResult:
    """Outcome of a strategy run + materialization."""

    strategy: str
    created: List[str] = field(default_factory=list)       # new node ids
    skipped: List[str] = field(default_factory=list)       # already-existed node ids
    open_questions: List[str] = field(default_factory=list)
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (blocker_id, blocked_id)
    extras: Dict[str, Any] = field(default_factory=dict)


# Back-compat alias for the old name; tests or external callers using
# the 1B name still work.
TasksResult = DecomposeResult


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------


def _existing_canon_index(project) -> Dict[Tuple[str, str, int], str]:
    """Return {(spec_slug, strategy, strategy_index): node_id} for existing work."""
    out: Dict[Tuple[str, str, int], str] = {}
    for node in project.all_nodes():
        cd = getattr(node, "component_data", {}) or {}
        canon_meta = cd.get("canon")
        if not isinstance(canon_meta, dict):
            continue
        slug = canon_meta.get("spec_slug")
        strategy = canon_meta.get("strategy", "tasks")
        idx = canon_meta.get(
            "strategy_index",
            canon_meta.get("plan_step_index"),  # back-compat with 0.4.0 markers
        )
        if isinstance(slug, str) and isinstance(idx, int):
            out[(slug, str(strategy), idx)] = node.id
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
# Materialize a StrategyResult into Hopewell nodes
# ---------------------------------------------------------------------------


def _materialize_into_hopewell(
    project,
    plan: ParsedPlan,
    sresult: StrategyResult,
    *,
    dry_run: bool,
) -> DecomposeResult:
    _, EdgeKind, _ = _load_hopewell()
    out = DecomposeResult(strategy=sresult.strategy, extras=dict(sresult.extras))
    existing = _existing_canon_index(project)
    existing_oq = _existing_open_question_index(project)

    spec_path = f"specs/{plan.spec_slug}/spec.md"
    plan_path = f"specs/{plan.spec_slug}/plan.md"

    item_to_node: Dict[int, str] = {}

    for item in sresult.items:
        key = (plan.spec_slug, sresult.strategy, item.index)
        if key in existing:
            out.skipped.append(existing[key])
            item_to_node[item.index] = existing[key]
            continue
        if dry_run:
            out.created.append(
                f"<dry-run {sresult.strategy} item {item.index}: {item.title}>"
            )
            continue

        node = project.new_node(
            components=["work-item"],
            title=item.title,
            priority=item.priority,
        )
        node.component_data["spec-input"] = {
            "specs": [
                {"path": spec_path, "slices": list(item.spec_slices)},
                {"path": plan_path, "slices": list(item.plan_slices)},
            ],
        }
        if item.executor_role:
            node.component_data["executor-suggestion"] = {"role": item.executor_role}
        est = sizing_estimate(item.sizing)
        if est:
            node.component_data["sizing"] = est

        canon_meta: Dict[str, Any] = {
            "spec_slug": plan.spec_slug,
            "strategy": sresult.strategy,
            "strategy_index": item.index,
            "kind": item.kind,
        }
        # Back-compat: tasks-strategy work items also carry the legacy
        # `plan_step_index` marker so 0.4.0 idempotency scans still find them.
        if sresult.strategy == "tasks":
            canon_meta["plan_step_index"] = item.index
        if item.metadata:
            canon_meta["strategy_meta"] = dict(item.metadata)
        if item.wave is not None:
            canon_meta["wave"] = item.wave
        if item.parallel_with:
            canon_meta["parallel_with"] = list(item.parallel_with)
        node.component_data["canon"] = canon_meta

        project.save_node(node)
        out.created.append(node.id)
        item_to_node[item.index] = node.id

    # Edges from blockers.
    if not dry_run:
        for item in sresult.items:
            tgt_id = item_to_node.get(item.index)
            if not tgt_id:
                continue
            for b in item.blockers:
                src_id = item_to_node.get(b)
                if not src_id:
                    continue
                try:
                    project.link(
                        src_id, EdgeKind.blocks, tgt_id,
                        reason=f"canon decompose: strategy={sresult.strategy}",
                    )
                    out.edges.append((src_id, tgt_id))
                except Exception:
                    # link() is idempotent in many implementations; tolerate.
                    pass

    # Open questions become their own nodes.
    for q in sresult.open_questions:
        key = (plan.spec_slug, q)
        if key in existing_oq:
            out.skipped.append(existing_oq[key])
            continue
        if dry_run:
            out.open_questions.append(f"<dry-run open-question: {q[:80]}>")
            continue
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
            "strategy": sresult.strategy,
            "open_question": q,
        }
        project.save_node(oq_node)
        out.open_questions.append(oq_node.id)

    return out


def _items_to_json(plan: ParsedPlan, sresult: StrategyResult) -> Dict[str, Any]:
    """Plain-JSON shape for environments without Hopewell (or --dry-run)."""
    return {
        "spec_slug": plan.spec_slug,
        "strategy": sresult.strategy,
        "items": [
            {
                "index": it.index,
                "kind": it.kind,
                "title": it.title,
                "sizing": it.sizing,
                "spec_slices": it.spec_slices,
                "plan_slices": it.plan_slices,
                "blockers": it.blockers,
                "wave": it.wave,
                "parallel_with": it.parallel_with,
                "priority": it.priority,
                "executor_role": it.executor_role,
                "metadata": it.metadata,
            }
            for it in sresult.items
        ],
        "open_questions": list(sresult.open_questions),
        "extras": dict(sresult.extras),
    }


# ---------------------------------------------------------------------------
# High-level entry point used by both `canon decompose` and `canon amend`
# ---------------------------------------------------------------------------


def run_strategy(
    *,
    root: Path,
    plan: ParsedPlan,
    cli_strategy: Optional[str] = None,
    dry_run: bool = False,
    project: Any = None,
    cwd: Optional[Path] = None,
) -> Tuple[DecomposeResult, str, str]:
    """Resolve, run, and materialize a strategy.

    Returns (result, strategy_name, source). `source` is whatever the
    resolver returned (cli / front-matter / config / smart-default) so
    the CLI can print provenance.

    If `project` is None, we attempt to load Hopewell. If Hopewell is
    not present in the project we fall through to the JSON-only path
    and the caller is responsible for printing.
    """
    strategy_name, source = resolve_strategy(cli_strategy, plan, root, cwd=cwd)
    if strategy_name not in REGISTRY:
        raise ValueError(
            f"unknown strategy {strategy_name!r}; "
            f"expected one of: {', '.join(KNOWN_STRATEGIES)}"
        )
    sresult: StrategyResult = REGISTRY[strategy_name].run(plan)

    # Hopewell path -- attempt to load if a project is present, even on
    # dry-run (so the operator sees the same idempotency-aware preview
    # they'll get on the real run).
    if project is None and _hopewell_present(root):
        try:
            hw_project, _, _ = _load_hopewell()
            project = hw_project.Project.load(start=root)
        except Exception:
            project = None

    if project is not None:
        result = _materialize_into_hopewell(
            project, plan, sresult, dry_run=dry_run
        )
        return result, strategy_name, source

    # JSON-only path (no Hopewell, or dry_run with no project): we still
    # populate a DecomposeResult that mirrors the planned items so callers
    # (and tests) can inspect it. `created` carries dry-run stubs.
    result = DecomposeResult(
        strategy=strategy_name,
        extras=dict(sresult.extras),
        open_questions=[f"<no-hw open-question: {q[:80]}>" for q in sresult.open_questions],
    )
    for it in sresult.items:
        result.created.append(
            f"<no-hw {strategy_name} item {it.index}: {it.title}>"
        )
    result.extras["json"] = _items_to_json(plan, sresult)
    return result, strategy_name, source


# ---------------------------------------------------------------------------
# CLI command implementations
# ---------------------------------------------------------------------------


def _resolve_plan_path(root: Path, spec_id: str) -> Tuple[Optional[Path], str]:
    """Resolve a user-provided spec id to a plan.md path. Returns (path, slug)."""
    plan_path = root / ".pedia" / "specs" / spec_id / "plan.md"
    if plan_path.exists():
        return plan_path, spec_id
    candidates = sorted((root / ".pedia" / "specs").glob(f"*-{spec_id}"))
    if candidates:
        slug = candidates[-1].name
        cand = root / ".pedia" / "specs" / slug / "plan.md"
        if cand.exists():
            return cand, slug
    return None, spec_id


def _print_summary(
    result: DecomposeResult,
    plan: ParsedPlan,
    strategy: str,
    source: str,
    *,
    json_output: bool,
) -> None:
    if json_output:
        sys.stdout.write(json.dumps({
            "strategy": strategy,
            "source": source,
            "spec_slug": plan.spec_slug,
            "created": result.created,
            "skipped": result.skipped,
            "open_questions": result.open_questions,
            "edges": [list(e) for e in result.edges],
            "extras": result.extras,
        }, indent=2) + "\n")
        return

    sys.stdout.write(
        f"canon decompose: strategy={strategy} [from {source}]\n"
    )
    sys.stdout.write(f"  spec_slug          : {plan.spec_slug}\n")
    sys.stdout.write(f"  decomposition steps: {len(plan.decomposition)}\n")
    sys.stdout.write(f"  open questions     : {len(plan.open_questions)}\n")
    sys.stdout.write(f"  created work items : {len(result.created)}\n")
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
        sys.stdout.write(f"  open-question items: {len(result.open_questions)}\n")
        for nid in result.open_questions:
            sys.stdout.write(f"    ? {nid}\n")
    if "waves" in result.extras:
        sys.stdout.write("  parallel waves     :\n")
        for wave, idxs in result.extras["waves"].items():
            sys.stdout.write(f"    wave {wave}: {idxs}\n")
    if "json" in result.extras:
        # No Hopewell -- print the JSON payload so callers can pipe it.
        sys.stdout.write("\n--- JSON output (no Hopewell project detected) ---\n")
        sys.stdout.write(json.dumps(result.extras["json"], indent=2) + "\n")


def cmd_decompose(args) -> int:
    """`canon decompose <spec-id> [--strategy <name>] [--dry-run] [--json]`."""
    root = config_mod.find_root(Path.cwd()) or Path.cwd()
    if not (root / ".canon").is_dir():
        sys.stderr.write("not a canon project (no .canon/ here or above)\n")
        return 2
    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        sys.stderr.write(msg + "\n")
        return 2

    plan_path, spec_slug = _resolve_plan_path(root, args.spec_id)
    if plan_path is None:
        sys.stderr.write(
            f"no plan found at .pedia/specs/{args.spec_id}/plan.md\n"
        )
        return 2

    plan = parse_plan(plan_path)
    if not plan.decomposition:
        sys.stderr.write(
            f"plan {plan_path.relative_to(root)} has no decomposition steps; "
            "nothing to decompose.\n"
        )
        return 1

    cli_strategy = getattr(args, "strategy", None)
    json_output = bool(getattr(args, "json_output", False))
    dry_run = bool(getattr(args, "dry_run", False))

    try:
        result, strategy, source = run_strategy(
            root=root, plan=plan, cli_strategy=cli_strategy,
            dry_run=dry_run,
        )
    except (ValueError, RuntimeError) as e:
        sys.stderr.write(str(e) + "\n")
        return 2

    _print_summary(result, plan, strategy, source, json_output=json_output)
    return 0


def cmd_tasks_alias(args) -> int:
    """Deprecated alias: `canon tasks <spec-id>` -> `canon decompose <spec-id>`.

    Prints a one-line stderr warning, then forwards to `cmd_decompose`
    with `--strategy tasks` (preserves prior behavior verbatim).
    """
    sys.stderr.write(
        "warning: `canon tasks` is deprecated; use `canon decompose` "
        "(forwarding with --strategy tasks)\n"
    )
    # Force the strategy to `tasks` to preserve prior behavior even if
    # config / front-matter would resolve elsewhere.
    args.strategy = "tasks"
    if not hasattr(args, "json_output"):
        args.json_output = False
    return cmd_decompose(args)
