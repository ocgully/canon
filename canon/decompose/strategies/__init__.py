"""Decompose strategies registry.

Each strategy module exposes one function:

    run(plan: ParsedPlan, **opts) -> StrategyResult

The dispatch layer (`canon.decompose.dispatch`) is responsible for
materializing the result into TaskFlow nodes / JSON / etc. Strategies
themselves do NOT touch TaskFlow -- they're pure plan -> structure
transformations.
"""
from __future__ import annotations

from canon.decompose.strategies import (  # noqa: F401
    flow,
    spike_build,
    story_map,
    tasks,
    vertical_slice,
)


# name -> module
REGISTRY = {
    "tasks": tasks,
    "flow": flow,
    "vertical-slice": vertical_slice,
    "spike-build": spike_build,
    "story-map": story_map,
}
