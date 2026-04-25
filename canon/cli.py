"""Canon CLI -- phase 1A + 1B + 1C + 1E surface.

Subcommands:
  init                          scaffold .canon/config.yaml; verify Pedia
  new --north-star <slug>       interview + write .pedia/north-stars/<slug>.md
  new --constitution <slug>     interview + write .pedia/constitution/<slug>.md
  specify <slug>                interview + write .pedia/specs/<num>-<slug>/spec.md
  plan <spec-id>                interview + write .pedia/specs/<spec-id>/plan.md
  decompose <spec-id>           break a plan into work items via a selectable strategy (0.5)
  tasks <spec-id>               [DEPRECATED] alias for `decompose --strategy tasks`
  implement <task-id>           dispatch the task via @orchestrator (1B)
  check [--strict]              validate citation completeness (1B)
  amend <type> <id>             incremental clarity-loop amend; supersedes prior block (1C)
  trace <id> --up | --down      walk the citation graph (1C)
  graph [--for <id>]            emit a Mermaid diagram of the citation graph (1C)
  config {get|set|list}         read/write .canon/config.yaml

Phase 1B was originally `canon tasks`; HW-0065 (0.5.0) renamed it to
`canon decompose` and expanded the single-strategy behavior into five
selectable strategies (tasks / flow / vertical-slice / spike-build /
story-map) -- see `canon.decompose`. The old `canon tasks` survives as
a deprecation shim.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

from canon import __version__
from canon import config as config_mod
from canon import pedia_bridge as pb
from canon.interview import run_interview, MAX_ITER_DEFAULT
from canon.render import render_block
from canon.schemas.constitution import CONSTITUTION_SCHEMA
from canon.schemas.north_star import NORTH_STAR_SCHEMA
from canon.schemas.plan import PLAN_SCHEMA
from canon.schemas.spec import SPEC_SCHEMA


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _root(args) -> Path:
    """Resolve the project root for a command invocation.

    Default: walk up from CWD looking for .canon/. If none found, use
    CWD (useful for `canon init`).
    """
    r = config_mod.find_root(Path.cwd())
    return r or Path.cwd()


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def _write(msg: str) -> None:
    sys.stdout.write(msg)
    if not msg.endswith("\n"):
        sys.stdout.write("\n")


def _err(msg: str) -> int:
    sys.stderr.write(msg)
    if not msg.endswith("\n"):
        sys.stderr.write("\n")
    return 2


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def cmd_init(args) -> int:
    root = Path.cwd()
    canon_dir = root / ".canon"
    if canon_dir.exists() and not args.force:
        _write(f"Canon already initialized at {canon_dir}")
    else:
        canon_dir.mkdir(exist_ok=True)
        cfg = config_mod.CanonConfig()
        config_mod.save(root, cfg)
        _write(f"Initialized Canon at {canon_dir}")

    # Pedia check / bootstrap
    ok, msg = pb.ensure_pedia_init(root)
    if not ok and args.link_pedia:
        _write(f"Pedia not present: {msg}")
        _write("Bootstrapping .pedia/ ...")
        ok_boot, boot_msg = pb.pedia_init_here(root)
        if not ok_boot:
            return _err(f"pedia bootstrap failed: {boot_msg}")
        ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        _write(
            f"warning: {msg}\n"
            "Canon will refuse to write blocks until Pedia is initialized.\n"
            "Run `pedia init` in this directory (or re-run `canon init --link-pedia`)."
        )
    else:
        _write(msg)

    # Hopewell is optional in 1A.
    if args.link_hopewell:
        try:
            import hopewell  # noqa: F401
            _write(f"hopewell importable: {getattr(__import__('hopewell'), '__version__', 'unknown')}")
        except Exception as e:
            _write(f"warning: hopewell not importable ({e}); phase 1B needs it for task derivation.")

    _write("")
    _write("Next:")
    _write("  canon new --north-star <slug>   # (optional) author a north-star")
    _write("  canon specify <slug>            # author a spec (clarity-loop)")
    return 0


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------


def _interview_and_write(
    *, root: Path, doc_type: str, slug: str, schema, filename: str,
    agent_choice: str, dry_run: bool, max_iter: int,
) -> int:
    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        return _err(msg)

    result = run_interview(schema, max_iter=max_iter)
    body = render_block(doc_type, result, slug=slug)

    if dry_run:
        _write("--- DRY RUN: block would be written as: ---")
        _write(body)
        return 0

    folder = pb.folder_for(doc_type, slug)
    dst = pb.write_block(root, doc_type, folder, filename, body)
    _write(f"\nWrote {dst.relative_to(root)}")

    added, unchanged, removed = pb.refresh(root)
    _write(f"pedia refresh: {added} added/updated, {unchanged} unchanged, {removed} removed")
    return 0


def cmd_new(args) -> int:
    root = _root(args)
    cfg = config_mod.load(root)
    max_iter = cfg.clarity_max_iter
    agent = args.agent or cfg.agent_default

    if args.north_star:
        slug = _slugify(args.north_star)
        return _interview_and_write(
            root=root, doc_type="north-star", slug=slug,
            schema=NORTH_STAR_SCHEMA, filename=f"{slug}.md",
            agent_choice=agent, dry_run=args.dry_run, max_iter=max_iter,
        )
    if args.constitution:
        slug = _slugify(args.constitution)
        return _interview_and_write(
            root=root, doc_type="constitution", slug=slug,
            schema=CONSTITUTION_SCHEMA, filename=f"{slug}.md",
            agent_choice=agent, dry_run=args.dry_run, max_iter=max_iter,
        )
    return _err("specify one of --north-star <slug> or --constitution <slug>")


# ---------------------------------------------------------------------------
# specify
# ---------------------------------------------------------------------------


def cmd_specify(args) -> int:
    root = _root(args)
    cfg = config_mod.load(root)
    max_iter = cfg.clarity_max_iter
    agent = args.agent or cfg.agent_default

    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        return _err(msg)

    title_slug = _slugify(args.slug)
    numbered = pb.next_spec_slug(root, title_slug)

    # Seed north_star_citation from --from-north-star if provided.
    context = {}
    if args.from_north_star:
        context["north_star_citation"] = args.from_north_star

    _write(f"Canon: authoring spec `{numbered}`")
    if args.from_north_star:
        _write(f"seeding north-star citation: {args.from_north_star}")

    # Patch schema answer default via a small wrapper -- we inject the
    # pre-seeded value into the interview history before the prompts
    # reach the user.
    # Simplest: run the interview; if the user blanks north_star_citation
    # and we have a seed, substitute post-hoc.
    result = run_interview(SPEC_SCHEMA, max_iter=max_iter)
    if args.from_north_star and not result.fields.get("north_star_citation", "").strip():
        result.fields["north_star_citation"] = args.from_north_star
        # The outcome stays -- not tampered with quality.

    body = render_block("spec", result, slug=numbered)

    if args.dry_run:
        _write("--- DRY RUN: spec block would be written as: ---")
        _write(body)
        return 0

    folder = pb.folder_for("spec", numbered)
    dst = pb.write_block(root, "spec", folder, "spec.md", body)
    _write(f"\nWrote {dst.relative_to(root)}")

    added, unchanged, removed = pb.refresh(root)
    _write(f"pedia refresh: {added} added/updated, {unchanged} unchanged, {removed} removed")
    _write(f"\nNext: canon plan {numbered}")
    return 0


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def cmd_plan(args) -> int:
    root = _root(args)
    cfg = config_mod.load(root)
    max_iter = cfg.clarity_max_iter

    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        return _err(msg)

    spec_slug = args.spec_id
    spec_path = root / ".pedia" / "specs" / spec_slug / "spec.md"
    if not spec_path.exists():
        # Allow user to pass a bare title-slug too.
        candidates = sorted((root / ".pedia" / "specs").glob(f"*-{spec_slug}"))
        if candidates:
            spec_slug = candidates[-1].name
            spec_path = root / ".pedia" / "specs" / spec_slug / "spec.md"
    if not spec_path.exists():
        return _err(f"no spec found at .pedia/specs/{args.spec_id}/spec.md")

    _write(f"Canon: planning spec `{spec_slug}`")
    _write(f"spec: {spec_path.relative_to(root)}")

    result = run_interview(PLAN_SCHEMA, max_iter=max_iter)
    body = render_block("plan", result, slug=spec_slug)

    if args.dry_run:
        _write("--- DRY RUN: plan block would be written as: ---")
        _write(body)
        return 0

    folder = pb.folder_for("plan", spec_slug)
    dst = pb.write_block(root, "plan", folder, "plan.md", body)
    _write(f"\nWrote {dst.relative_to(root)}")

    added, unchanged, removed = pb.refresh(root)
    _write(f"pedia refresh: {added} added/updated, {unchanged} unchanged, {removed} removed")
    return 0


# ---------------------------------------------------------------------------
# amend / trace / graph (phase 1C)
# ---------------------------------------------------------------------------


def cmd_amend(args) -> int:
    from canon import amend as amend_mod

    root = _root(args)
    cfg = config_mod.load(root)
    max_iter = cfg.clarity_max_iter

    ok, msg = pb.ensure_pedia_init(root)
    if not ok:
        return _err(msg)

    regenerate = bool(getattr(args, "regenerate", False))
    strategy = getattr(args, "strategy", None)
    if strategy and not regenerate:
        return _err(
            "--strategy requires --regenerate (plain `canon amend` does not "
            "regenerate work items; use `canon amend plan <id> --regenerate "
            "--strategy <name>`)"
        )

    try:
        result = amend_mod.amend(
            root,
            args.doc_type,
            args.id,
            max_iter=max_iter,
            dry_run=args.dry_run,
            regenerate=regenerate,
            strategy=strategy,
        )
    except FileNotFoundError as e:
        return _err(str(e))
    except (ValueError, NotImplementedError, RuntimeError) as e:
        return _err(str(e))

    # --regenerate result has a different shape.
    if result.get("regenerated"):
        dec = result["result"]
        _write(
            f"\nRegenerated plan `{result['slug']}` "
            f"under strategy={result['strategy']} [from {result['strategy_source']}]"
        )
        _write(f"  created work items : {len(dec.created)}")
        for nid in dec.created:
            _write(f"    + {nid}")
        if dec.skipped:
            _write(f"  skipped (existed)  : {len(dec.skipped)}")
            for nid in dec.skipped:
                _write(f"    = {nid}")
        if dec.edges:
            _write(f"  ordering edges     : {len(dec.edges)}")
            for (a, b) in dec.edges:
                _write(f"    {a} blocks {b}")
        if dec.open_questions:
            _write(f"  open-question items: {len(dec.open_questions)}")
            for nid in dec.open_questions:
                _write(f"    ? {nid}")
        return 0

    if result.get("dry_run"):
        _write("--- DRY RUN: amended block would be written as: ---")
        _write(result["new_body"])
        return 0

    _write(f"\nAmended {result['doc_type']} `{result['slug']}`")
    _write(f"  prior block id: {result.get('prior_block_id') or '(unknown)'}")
    _write(f"  new   block id: {result.get('new_block_id') or '(unknown)'}")
    _write(f"  written:        {result['new_path']}")
    _write(f"  history file:   {result['history_path']}")
    if result.get("edge_written"):
        _write("  pedia refs: supersedes edge written")
    if result.get("drift"):
        _write("")
        _write("hopewell drift surfaced:")
        for ln in result["drift"].splitlines():
            _write(f"  {ln}")
    return 0


def cmd_trace(args) -> int:
    from canon import trace as trace_mod

    root = _root(args)
    if not args.up and not args.down:
        return _err("specify --up or --down")
    if args.up and args.down:
        return _err("use --up OR --down, not both")
    direction = "up" if args.up else "down"

    tr = trace_mod.run_trace(root, args.id, direction=direction, depth=args.depth)
    out = trace_mod.format_result(tr, args.format)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        _write(f"wrote {args.out}")
        return 0
    _write(out)
    return 0


def cmd_graph(args) -> int:
    from canon import graph as graph_mod

    root = _root(args)
    out = graph_mod.render_graph(root, focus=args.for_id, depth=args.depth)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        _write(f"wrote {args.out}")
        return 0
    _write(out)
    return 0


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def cmd_config(args) -> int:
    root = _root(args)
    if not (root / ".canon").is_dir():
        return _err("not a canon project (no .canon/ here or above). run `canon init`.")
    if args.action == "get":
        if not args.key:
            return _err("canon config get <key>")
        v = config_mod.get_key(root, args.key)
        if v is None:
            return _err(f"unknown key: {args.key}")
        _write(str(v))
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            return _err("canon config set <key> <value>")
        config_mod.set_key(root, args.key, args.value)
        _write(f"{args.key} = {args.value}")
        return 0
    if args.action == "list":
        for line in config_mod.list_keys(root):
            _write(line)
        return 0
    return _err(f"unknown config action: {args.action}")


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="canon",
        description="Canon -- SDD discipline tool. Buries SpecKit.",
    )
    p.add_argument("--version", action="version", version=f"canon {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="Scaffold .canon/ in this directory")
    pi.add_argument("--link-pedia", action="store_true",
                    help="Also run `pedia init` if .pedia/ is missing")
    pi.add_argument("--link-hopewell", action="store_true",
                    help="Verify hopewell is importable (1B dep; optional in 1A)")
    pi.add_argument("--force", action="store_true", help="Overwrite existing config")
    pi.set_defaults(func=cmd_init)

    pn = sub.add_parser("new", help="Author a north-star or constitution chapter")
    group = pn.add_mutually_exclusive_group(required=True)
    group.add_argument("--north-star", metavar="SLUG",
                       help="Author a new north-star block")
    group.add_argument("--constitution", metavar="CHAPTER_SLUG",
                       help="Author a constitution chapter")
    pn.add_argument("--agent", metavar="{claude|codex|none}", default=None,
                    help="External agent runner (phase 1A: ignored unless PATH-available)")
    pn.add_argument("--dry-run", action="store_true", help="Print the block; don't write")
    pn.set_defaults(func=cmd_new)

    ps = sub.add_parser("specify", help="Author a spec (clarity-loop interview)")
    ps.add_argument("slug", help="Human-friendly title slug")
    ps.add_argument("--from-north-star", metavar="NS_SLUG",
                    help="Pre-seed the north-star citation")
    ps.add_argument("--agent", metavar="{claude|codex|none}", default=None)
    ps.add_argument("--dry-run", action="store_true")
    ps.set_defaults(func=cmd_specify)

    pp = sub.add_parser("plan", help="Author a plan for a spec")
    pp.add_argument("spec_id", help="Spec slug (e.g. 001-cache-layer) or title-slug")
    pp.add_argument("--agent", metavar="{claude|codex|none}", default=None)
    pp.add_argument("--dry-run", action="store_true")
    pp.set_defaults(func=cmd_plan)

    # ----- 1B: decompose (renamed from `tasks` in 0.5.0) / implement / check -----
    from canon.decompose import cmd_decompose, cmd_tasks_alias
    from canon.decompose.resolver import KNOWN_STRATEGIES
    from canon.implement import cmd_implement
    from canon.check import cmd_check

    pd = sub.add_parser(
        "decompose",
        help="Decompose a plan into work items via a selectable strategy",
    )
    pd.add_argument("spec_id", help="Spec slug (e.g. 001-cache-layer)")
    pd.add_argument(
        "--strategy",
        choices=list(KNOWN_STRATEGIES),
        default=None,
        help=(
            "Decomposition strategy (default: front-matter -> .canon/config.yaml "
            "-> smart-default). Strategies: tasks (linear), flow (Hopewell waves), "
            "vertical-slice (demo-able increments), spike-build (research first), "
            "story-map (epic/activity/story)."
        ),
    )
    pd.add_argument(
        "--dry-run", action="store_true",
        help="Parse + run strategy; show what would be created; write nothing.",
    )
    pd.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit a structured JSON summary instead of human-readable text.",
    )
    pd.set_defaults(func=cmd_decompose)

    # Deprecated alias: `canon tasks` -> `canon decompose --strategy tasks`.
    pt = sub.add_parser(
        "tasks",
        help="[DEPRECATED] alias for `canon decompose --strategy tasks`",
    )
    pt.add_argument("spec_id", help="Spec slug (e.g. 001-cache-layer)")
    pt.add_argument("--dry-run", action="store_true",
                    help="Parse the plan + show what would be created; write nothing")
    pt.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit a structured JSON summary instead of human-readable text.",
    )
    pt.set_defaults(func=cmd_tasks_alias)

    pim = sub.add_parser("implement", help="Dispatch a task via @orchestrator (or directly)")
    pim.add_argument("task_id", help="Hopewell node id (e.g. HW-0001)")
    pim.add_argument("--dry-run", action="store_true",
                     help="Build the bundle + show the target; do not push")
    pim.set_defaults(func=cmd_implement)

    pck = sub.add_parser("check", help="Validate citation completeness across spec/plan/task")
    pck.add_argument("--strict", action="store_true",
                     help="Exit 2 on warnings (default: warnings are advisory)")
    pck.add_argument("--format", choices=["text", "json"], default="text")
    pck.set_defaults(func=cmd_check)

    # ----- 1C: amend / trace / graph -----
    pa = sub.add_parser(
        "amend",
        help="Incremental clarity-loop amend; supersedes prior block",
    )
    pa.add_argument(
        "doc_type",
        choices=["spec", "plan", "ns", "north-star", "constitution", "task"],
        help="Type of block to amend",
    )
    pa.add_argument("id", help="Slug or block-id of the prior block")
    pa.add_argument("--dry-run", action="store_true",
                    help="Show what would be written; mutate nothing")
    pa.add_argument(
        "--regenerate", action="store_true",
        help=(
            "Re-run the decompose strategy in place (only valid for "
            "doc-type `plan`). Without this flag, `amend` only patches text "
            "and preserves the existing strategy."
        ),
    )
    pa.add_argument(
        "--strategy",
        choices=list(KNOWN_STRATEGIES),
        default=None,
        help=(
            "When --regenerate is set, override the strategy resolution "
            "chain and use this strategy explicitly."
        ),
    )
    pa.set_defaults(func=cmd_amend)

    ptr = sub.add_parser(
        "trace",
        help="Walk the citation graph upstream or downstream from a block / task",
    )
    ptr.add_argument("id", help="Pedia block-id, spec slug, or Hopewell task id")
    dir_grp = ptr.add_mutually_exclusive_group()
    dir_grp.add_argument("--up", action="store_true",
                         help="Walk upstream citations (this -> what it cites)")
    dir_grp.add_argument("--down", action="store_true",
                         help="Walk downstream consumers (what cites this)")
    ptr.add_argument("--depth", type=int, default=5,
                     help="Maximum recursion depth (default 5)")
    ptr.add_argument("--format", choices=["text", "json", "mermaid"],
                     default="text",
                     help="Output format (default text)")
    ptr.add_argument("--out", metavar="PATH",
                     help="Write output to a file instead of stdout")
    ptr.set_defaults(func=cmd_trace)

    pg = sub.add_parser(
        "graph",
        help="Emit a Mermaid diagram of the citation graph",
    )
    pg.add_argument("--for", dest="for_id", metavar="ID",
                    help="Scope to the depth-N neighborhood of this block / slug")
    pg.add_argument("--depth", type=int, default=3,
                    help="Neighborhood depth when --for is given (default 3)")
    pg.add_argument("--out", metavar="PATH",
                    help="Write diagram to a file instead of stdout")
    pg.set_defaults(func=cmd_graph)

    pc = sub.add_parser("config", help="Read/write .canon/config.yaml")
    pc.add_argument("action", choices=["get", "set", "list"])
    pc.add_argument("key", nargs="?", default=None)
    pc.add_argument("value", nargs="?", default=None)
    pc.set_defaults(func=cmd_config)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
