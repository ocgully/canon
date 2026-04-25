"""Phase 1D plugin sanity tests.

These tests don't exercise the plugins end-to-end (that requires a live
Claude Code or VS Code host). They just verify the on-disk artifacts
parse correctly so a malformed file can't sneak past CI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "canon" / "plugin"
COMMANDS_DIR = PLUGIN_ROOT / "commands"
SKILLS_DIR = PLUGIN_ROOT / "skills"
VSCODE_DIR = PLUGIN_ROOT / "vscode"


# ---------------------------------------------------------------------------
# Claude Code commands
# ---------------------------------------------------------------------------

EXPECTED_COMMANDS = {
    "canon-specify",
    "canon-plan",
    "canon-tasks",
    "canon-trace",
    "canon-graph",
}


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML-ish frontmatter parser. We only care about top-level
    key: value pairs in the first --- block."""
    if not text.startswith("---"):
        raise ValueError("missing leading frontmatter delimiter")
    # find closing ---
    closing = re.search(r"^---\s*$", text, flags=re.MULTILINE | re.DOTALL)
    # use a more careful split: split on lines
    lines = text.splitlines()
    if lines[0].strip() != "---":
        raise ValueError("missing leading frontmatter delimiter")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("missing closing frontmatter delimiter")
    out: dict[str, str] = {}
    for raw in lines[1:end_idx]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            raise ValueError(f"non-key-value frontmatter line: {raw!r}")
        key, _, value = raw.partition(":")
        out[key.strip()] = value.strip()
    return out


def test_commands_directory_exists():
    assert COMMANDS_DIR.is_dir(), f"missing {COMMANDS_DIR}"


def test_all_expected_commands_present():
    found = {p.stem for p in COMMANDS_DIR.glob("*.md")}
    missing = EXPECTED_COMMANDS - found
    assert not missing, f"missing commands: {missing}"


@pytest.mark.parametrize("name", sorted(EXPECTED_COMMANDS))
def test_command_frontmatter(name: str):
    path = COMMANDS_DIR / f"{name}.md"
    assert path.is_file(), f"{path} missing"
    text = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert "description" in fm and fm["description"], f"{name}: empty description"
    # Body must reference the canon CLI -- otherwise the command is decorative.
    body = text.split("---", 2)[-1]
    assert "canon " in body, f"{name}: command body never invokes the canon CLI"


# ---------------------------------------------------------------------------
# Phase-2 skill placeholder
# ---------------------------------------------------------------------------


def test_canon_review_skill_placeholder():
    skill = SKILLS_DIR / "canon-review" / "SKILL.md"
    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert fm.get("name") == "canon-review"
    assert "phase 2" in fm.get("description", "").lower(), (
        "phase-2 marker missing from canon-review description"
    )


# ---------------------------------------------------------------------------
# VS Code extension manifest
# ---------------------------------------------------------------------------


def test_vscode_package_json_valid():
    pkg_path = VSCODE_DIR / "package.json"
    assert pkg_path.is_file()
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))

    assert pkg["name"] == "canon-vscode"
    assert pkg["version"] == "0.1.0"
    assert "main" in pkg
    assert (VSCODE_DIR / pkg["main"]).is_file(), (
        f"main entry {pkg['main']} missing on disk"
    )

    # Engines must declare a vscode floor.
    assert "vscode" in pkg.get("engines", {}), "engines.vscode missing"

    # Every contributed command must have a matching activationEvent and
    # a registerCommand call in extension.js.
    contributed = pkg.get("contributes", {}).get("commands", [])
    contributed_ids = {c["command"] for c in contributed}
    expected = {"canon.specify", "canon.plan", "canon.tasks", "canon.check", "canon.trace"}
    assert contributed_ids == expected, (
        f"contributed command set drift: {contributed_ids ^ expected}"
    )

    activation = set(pkg.get("activationEvents", []))
    for cmd in expected:
        assert f"onCommand:{cmd}" in activation, (
            f"activation event missing for {cmd}"
        )


def test_vscode_extension_js_registers_all_commands():
    ext = (VSCODE_DIR / "extension.js").read_text(encoding="utf-8")
    for cmd in ("canon.specify", "canon.plan", "canon.tasks", "canon.check", "canon.trace"):
        assert f"'{cmd}'" in ext, f"extension.js does not register {cmd}"


def test_vscode_readme_present():
    assert (VSCODE_DIR / "README.md").is_file()
    assert (VSCODE_DIR / ".vscodeignore").is_file()
