"""Assemble the context bundle Canon hands to an external agent runner.

Per plan §11: Canon does NOT embed a chat client. When `--agent claude`
(or codex, etc.) is supplied AND a field fails to commit after
MAX_ITER, Canon writes a structured context file and invokes the
agent-runner subprocess (or, if missing, copies a prompt to the
clipboard). The agent session does the clarity pass; Canon accepts the
refined answer back.

Phase 1A wires the file-write half. Actual subprocess dispatch is a
thin wrapper over subprocess.Popen with `--` stop-parsing so we never
interpret agent args. If the agent binary isn't on PATH, we degrade
gracefully to 'write the file, print the path'.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AgentContext:
    session_id: str
    context_dir: Path
    context_path: Path
    schema_type: str
    field_name: str
    attempt_count: int
    answers_so_far: Dict[str, str] = field(default_factory=dict)
    rules_score: float = 0.0
    rules_gaps: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# Canon agent-session context",
            "",
            f"session: `{self.session_id}`",
            f"schema: `{self.schema_type}`",
            f"field: `{self.field_name}`",
            f"attempts: {self.attempt_count}",
            f"rules_score: {self.rules_score:.3f}",
            "",
            "## Gaps the rule engine flagged",
            "",
        ]
        for g in self.rules_gaps:
            lines.append(f"- {g}")
        if not self.rules_gaps:
            lines.append("- (none)")
        lines += [
            "",
            "## Answers so far",
            "",
        ]
        for k, v in self.answers_so_far.items():
            lines.append(f"### {k}")
            lines.append("")
            lines.append(v or "_(empty)_")
            lines.append("")
        lines += [
            "## Your task",
            "",
            "Refine the answer for the field above. Return ONLY the refined",
            "answer text -- no preamble, no markdown headers. Canon will",
            "substitute it verbatim into the block.",
            "",
        ]
        return "\n".join(lines)


def build_context(
    *,
    canon_root: Path,
    context_root_rel: str,
    schema_type: str,
    field_name: str,
    attempt_count: int,
    answers_so_far: Dict[str, str],
    rules_score: float,
    rules_gaps: List[str],
) -> AgentContext:
    session_id = uuid.uuid4().hex[:12]
    ctx_dir = canon_root / context_root_rel / session_id
    ctx_dir.mkdir(parents=True, exist_ok=True)
    ctx_path = ctx_dir / "context.md"
    ctx = AgentContext(
        session_id=session_id,
        context_dir=ctx_dir,
        context_path=ctx_path,
        schema_type=schema_type,
        field_name=field_name,
        attempt_count=attempt_count,
        answers_so_far=dict(answers_so_far),
        rules_score=rules_score,
        rules_gaps=list(rules_gaps),
    )
    ctx_path.write_text(ctx.to_markdown(), encoding="utf-8")
    # Machine-readable sidecar for agents that want JSON.
    sidecar = {
        "session_id": session_id,
        "schema_type": schema_type,
        "field_name": field_name,
        "attempt_count": attempt_count,
        "rules_score": rules_score,
        "rules_gaps": rules_gaps,
        "answers_so_far": answers_so_far,
    }
    (ctx_dir / "context.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8"
    )
    return ctx


def agent_binary_for(choice: str) -> Optional[str]:
    """Map the user's --agent choice to a PATH-lookup binary name."""
    choice = (choice or "").lower()
    if choice in {"", "none", "off"}:
        return None
    if choice == "claude":
        return "claude"
    if choice == "codex":
        return "codex"
    # Unknown: treat the string itself as the binary name; no magic.
    return choice


def agent_available(choice: str) -> bool:
    b = agent_binary_for(choice)
    if b is None:
        return False
    return shutil.which(b) is not None


def invoke_agent(
    choice: str,
    context_path: Path,
    *,
    timeout_sec: int = 120,
) -> Optional[str]:
    """Run the external agent with the context file.

    Returns the agent's stdout (the refined answer) on success, or
    None if the agent isn't available / fails.
    """
    binary = agent_binary_for(choice)
    if binary is None or shutil.which(binary) is None:
        return None
    # We use -- to stop flag parsing. Agent runners that don't accept
    # this silently ignore it.
    cmd = [binary, "--", str(context_path)]
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode != 0:
            return None
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        return out or None
    except Exception:  # pragma: no cover
        return None
