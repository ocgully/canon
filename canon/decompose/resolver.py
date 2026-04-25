"""Strategy resolution chain for `canon decompose`.

Resolution order (first match wins):

  1. Explicit CLI flag (`--strategy <name>`)
  2. Plan front-matter key `strategy:`
  3. Repo config `.canon/config.yaml` -> `decompose.strategy:`
  4. Smart fallback:
       - if `.hopewell/` AND `.pedia/` exist anywhere up the tree from `cwd`
         -> `flow`
       - else -> `tasks`

Public surface:

    resolve_strategy(cli_flag, plan, root, *, cwd=None) -> (strategy, source)
    KNOWN_STRATEGIES: tuple[str, ...]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from canon import config as config_mod
from canon.decompose.base import ParsedPlan


# Authoritative list of strategy names. Used by the CLI parser, the
# resolver, and the dispatch layer.
KNOWN_STRATEGIES: Tuple[str, ...] = (
    "tasks",
    "flow",
    "vertical-slice",
    "spike-build",
    "story-map",
)


# Front-matter key that overrides the config / smart fallback.
_FM_KEYS = ("strategy", "decompose_strategy")


def _normalize(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = str(name).strip().lower().replace("_", "-")
    if n in KNOWN_STRATEGIES:
        return n
    return None


def _from_front_matter(plan: Optional[ParsedPlan]) -> Optional[str]:
    if plan is None:
        return None
    fm = plan.front_matter or {}
    for k in _FM_KEYS:
        v = fm.get(k)
        if isinstance(v, str):
            n = _normalize(v)
            if n:
                return n
    # Nested under `decompose:`?
    nested = fm.get("decompose")
    if isinstance(nested, dict):
        n = _normalize(nested.get("strategy"))
        if n:
            return n
    return None


def _from_config(root: Optional[Path]) -> Optional[str]:
    if root is None:
        return None
    if not (root / ".canon").is_dir():
        return None
    try:
        # Config is a flat dict; we use a dotted-path getter.
        v = config_mod.get_key(root, "decompose.strategy")
        return _normalize(v if isinstance(v, str) else None)
    except Exception:
        return None


def _smart_fallback(cwd: Path) -> str:
    """Walk up from `cwd` looking for a TaskFlow / Hopewell store
    AND `.pedia/`.

    Both must be present (and at the same root) for the `flow` smart
    default. We're conservative: if either is missing, we drop to
    `tasks`. The work-graph store may be `.taskflow/` (post-rebrand)
    or the legacy `.hopewell/` — either counts.
    """
    cur = cwd.resolve()
    for p in [cur] + list(cur.parents):
        has_workgraph = (p / ".taskflow").is_dir() or (p / ".hopewell").is_dir()
        has_pedia = (p / ".pedia").is_dir()
        if has_workgraph and has_pedia:
            return "flow"
    return "tasks"


def resolve_strategy(
    cli_flag: Optional[str],
    plan: Optional[ParsedPlan],
    root: Optional[Path],
    *,
    cwd: Optional[Path] = None,
) -> Tuple[str, str]:
    """Resolve the strategy + return (strategy, source).

    `source` is one of: "cli" | "front-matter" | "config" | "smart-default".
    Useful for the CLI to print "using strategy `flow` [from front-matter]".

    Unknown explicit names are rejected with ValueError -- typos in
    flags or config should be loud, not silently fall through.
    """
    if cli_flag:
        n = _normalize(cli_flag)
        if not n:
            raise ValueError(
                f"unknown --strategy {cli_flag!r}; "
                f"expected one of: {', '.join(KNOWN_STRATEGIES)}"
            )
        return n, "cli"

    fm_pick = _from_front_matter(plan)
    if fm_pick:
        return fm_pick, "front-matter"

    cfg_pick = _from_config(root)
    if cfg_pick:
        return cfg_pick, "config"

    return _smart_fallback(cwd or Path.cwd()), "smart-default"
