"""Thin wrapper over Pedia: locate its root, write blocks, trigger refresh.

Canon integrates with Pedia at the filesystem level -- it writes
markdown into .pedia/<subdir>/ and calls pedia.refresh.refresh(). We
never shell out.

Phase 1A uses these Pedia internals:
  - pedia.refresh.refresh(root)     -> incremental reindex
  - pedia.cli.TYPE_SUBDIR           -> doc-type -> folder mapping
These are considered semi-public (the CLI uses them); if Pedia
promotes a proper public API later we switch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Tuple

try:  # runtime dep; import is mandatory
    from pedia import refresh as pedia_refresh_mod  # type: ignore
    from pedia import cli as pedia_cli              # type: ignore
    from pedia import config as pedia_config        # type: ignore
    PEDIA_AVAILABLE = True
    PEDIA_IMPORT_ERROR: Optional[str] = None
except Exception as e:  # pragma: no cover
    PEDIA_AVAILABLE = False
    PEDIA_IMPORT_ERROR = str(e)


TYPE_FOLDERS = {
    "north-star": "north-stars",
    "constitution": "constitution",
    "spec": "specs",
    "plan": "specs",            # plans live alongside their spec: specs/<slug>/plan.md
    "decision": "decisions",
}


def pedia_available() -> bool:
    return PEDIA_AVAILABLE


def find_pedia_root(start: Path) -> Optional[Path]:
    """Walk up from start looking for .pedia/."""
    cur = start.resolve()
    for p in [cur] + list(cur.parents):
        if (p / ".pedia").is_dir():
            return p
    return None


def ensure_pedia_init(root: Path) -> Tuple[bool, str]:
    """Verify .pedia/ exists; return (ok, message)."""
    if not PEDIA_AVAILABLE:
        return False, f"pedia module not importable: {PEDIA_IMPORT_ERROR}"
    p = root / ".pedia"
    if not p.is_dir():
        return False, (
            f".pedia/ not found under {root}. Run `pedia init` first, "
            "or pass --link-pedia to canon init to bootstrap."
        )
    return True, f"pedia root OK at {root}"


def pedia_init_here(root: Path) -> Tuple[bool, str]:
    """Best-effort `pedia init` for auto-bootstrapping.

    Pedia's cmd_init uses Path.cwd() internally (it doesn't honor a
    --root flag), so we chdir() into the target for the duration of
    the call, then restore. This is the same trick pedia's own tests
    use.
    """
    if not PEDIA_AVAILABLE:
        return False, f"pedia module not importable: {PEDIA_IMPORT_ERROR}"
    from argparse import Namespace
    import os as _os
    args = Namespace(
        root=str(root),
        with_examples=False,
        backfill=False,
        no_backfill=True,
    )
    prev = _os.getcwd()
    try:
        _os.chdir(str(root))
        rc = pedia_cli.cmd_init(args)
        return (rc == 0), f"pedia init rc={rc}"
    except Exception as e:  # pragma: no cover
        return False, f"pedia init failed: {e}"
    finally:
        _os.chdir(prev)


def refresh(root: Path) -> Tuple[int, int, int]:
    """Incremental Pedia reindex. Returns (added, unchanged, removed)."""
    added, unchanged, removed = pedia_refresh_mod.refresh(
        root, full=False, docs_glob=None, only_changed_in_session=False,
    )
    return added, unchanged, removed


def write_block(
    root: Path, doc_type: str, rel_folder: str, filename: str, body: str,
) -> Path:
    """Write a markdown block into .pedia/<rel_folder>/<filename>.

    For specs + plans, caller supplies a full relative folder like
    "specs/001-cache-layer" so both spec.md and plan.md land together.
    """
    target_dir = root / ".pedia" / rel_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / filename
    dst.write_text(body, encoding="utf-8")
    return dst


def folder_for(doc_type: str, slug: str) -> str:
    """Destination folder (relative to .pedia/) for a (type, slug) pair."""
    if doc_type == "spec" or doc_type == "plan":
        return f"specs/{slug}"
    folder = TYPE_FOLDERS.get(doc_type)
    if folder is None:
        raise ValueError(f"unknown doc_type: {doc_type}")
    return folder


def next_spec_slug(root: Path, title_slug: str) -> str:
    """Produce a numeric-prefixed spec slug like '001-cache-layer'.

    Looks at existing .pedia/specs/ entries and increments the highest
    numeric prefix by 1. Stable + zero-padded.
    """
    specs_dir = root / ".pedia" / "specs"
    existing_nums: list[int] = []
    if specs_dir.is_dir():
        for child in specs_dir.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            head, _, _ = name.partition("-")
            if head.isdigit():
                existing_nums.append(int(head))
    nxt = (max(existing_nums) + 1) if existing_nums else 1
    return f"{nxt:03d}-{title_slug}"


def pedia_query_related(root: Path, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Best-effort: ask Pedia for related blocks for 'related_work'.

    Returns [] on any failure; this is a suggestion, not a dependency.
    """
    try:
        from pedia import query as qmod  # type: ignore
        res = qmod.run_query(root, query, doc_type=None, scope=None,
                             token_budget=None, exclude=[], limit=limit)
        out = []
        # The Query result exposes blocks via .blocks or similar; tolerate.
        items = getattr(res, "blocks", None) or getattr(res, "results", []) or []
        for b in items:
            path = getattr(b, "path", None) or getattr(b, "doc_path", None)
            title = getattr(b, "heading", None) or getattr(b, "title", None)
            out.append({"path": path, "title": title})
        return out
    except Exception:
        return []
