"""canon decompose -- selectable strategies for breaking a plan into work items.

`canon decompose <spec-id> [--strategy <name>]` is the renamed + expanded
form of the original `canon tasks`. The old command is still wired as a
deprecated alias.

Five strategies ship in 0.5.0:

  - tasks          (default fallback) -- linear ordered task list with deps.
                   Best for solo / small change. This is the original 1B
                   behavior.
  - flow           -- TaskFlow-shaped flow network: parallel waves +
                   `blocks` edges. Falls back to plain JSON when TaskFlow
                   isn't initialized.
  - vertical-slice -- break by demo-able user-visible increment, not by
                   horizontal layer.
  - spike-build    -- emit a "spike" research item first; planned build
                   items depend on its outcome. For high-uncertainty work.
  - story-map      -- epic -> activity -> task. Each row is a backbone
                   activity; cells beneath are increments.

Strategy resolution chain (first match wins) -- see `resolver.py`:

    1. CLI flag:   canon decompose --strategy flow
    2. Front-matter: `strategy: flow` in the plan markdown
    3. Repo config: .canon/config.yaml -> decompose.strategy: flow
    4. Smart fallback: if .taskflow/ (or legacy .hopewell/) AND .pedia/
       exist -> flow; else tasks.

Each strategy returns a list of typed work items + edges (the exact
shape depends on the strategy; see `base.WorkItem`). The dispatch layer
(`run_strategy`) is responsible for materializing the items into
TaskFlow nodes and surfacing strategy-specific metadata.

User-facing terminology: the output is "work items", never "tasks", except
for the `tasks` strategy itself (where the noun is appropriate).
"""
from __future__ import annotations

from canon.decompose.base import (
    DecompStep,
    ParsedPlan,
    StrategyResult,
    WorkItem,
)
from canon.decompose.dispatch import (
    cmd_decompose,
    cmd_tasks_alias,
    parse_plan,
    run_strategy,
)
from canon.decompose.resolver import (
    KNOWN_STRATEGIES,
    resolve_strategy,
)


__all__ = [
    "DecompStep",
    "KNOWN_STRATEGIES",
    "ParsedPlan",
    "StrategyResult",
    "WorkItem",
    "cmd_decompose",
    "cmd_tasks_alias",
    "parse_plan",
    "resolve_strategy",
    "run_strategy",
]
