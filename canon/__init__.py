"""canon -- SDD discipline tool.

Phase 1A surface:
  canon init
  canon new --north-star <slug> | --constitution <chapter-slug>
  canon specify <slug>
  canon plan <spec-id>
  canon config {get|set|list}

Phase 1B surface (additive):
  canon decompose <spec-id> [--strategy <name>]    # 0.5.0+
  canon tasks <spec-id>                            # deprecated alias
  canon implement <task-id>
  canon check [--strict] [--format=json]

Clarity-loop interviewed. Writes citation-anchored blocks to Pedia.
Work items land as Hopewell nodes with auto-populated `spec-input`.
Stores nothing of its own except .canon/config.yaml + dispatch
bundles under .canon/dispatches/.

Buries SpecKit.
"""

__version__ = "0.5.0"
