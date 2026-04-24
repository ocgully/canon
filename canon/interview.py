"""Interview orchestration.

Walks a schema in declared order, runs the clarity-loop on each field,
and returns a dict of field-name -> committed answer. Also records
per-field quality metadata (final score + iterations) that's embedded
into the output block's front-matter so downstream tools can see how
crisp each field actually was.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from canon.clarity import ClarityResult, compose_follow_up, evaluate
from canon.schemas import FieldSchema, Schema


MAX_ITER_DEFAULT = 5


@dataclass
class FieldOutcome:
    name: str
    answer: str
    final_score: float
    iterations: int
    accepted_as_is: bool
    gaps_at_commit: List[str] = field(default_factory=list)


@dataclass
class InterviewResult:
    fields: Dict[str, str]                     # name -> committed answer
    outcomes: Dict[str, FieldOutcome]          # per-field metadata
    aborted: bool = False

    def as_front_matter_quality(self) -> Dict[str, Dict[str, Any]]:
        """Per-field quality payload for the output block."""
        out: Dict[str, Dict[str, Any]] = {}
        for n, o in self.outcomes.items():
            out[n] = {
                "score": o.final_score,
                "iterations": o.iterations,
                "accepted_as_is": o.accepted_as_is,
                "gaps_at_commit": list(o.gaps_at_commit),
            }
        return out


# ----- I/O adapters ---------------------------------------------------------

# We keep I/O injectable so tests can drive scripted answers without
# fiddling with stdin. Default uses input() / print().


# Sentinel: stdin-closed. Interview loop treats it as "accept-as-is".
_EOF_SENTINEL = "\x00CANON_EOF\x00"


def _default_ask(prompt: str) -> str:
    sys.stdout.write(prompt)
    if not prompt.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.write("> ")
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:  # pragma: no cover
        raise
    if not line:
        # Real EOF -- not just an empty line. Signal to the outer
        # loop that the user / driver has no more input; we accept
        # whatever we've got so a heredoc-driven smoke test doesn't
        # hang waiting for follow-up text.
        return _EOF_SENTINEL
    # Multi-line mode: if the user ends with '\\' we keep reading
    # until a blank line.
    if line.rstrip("\n").endswith("\\"):
        parts = [line.rstrip("\n")[:-1]]
        while True:
            more = sys.stdin.readline()
            if not more or more.strip() == "":
                break
            parts.append(more.rstrip("\n"))
        return "\n".join(parts)
    # Heredoc convenience: the literal escape sequence `\n` inside a
    # single stdin line decodes to a real newline so scripted smoke
    # tests can supply list-shaped answers on one line.
    cooked = line.rstrip("\n")
    if r"\n" in cooked:
        cooked = cooked.replace(r"\n", "\n")
    return cooked


def _default_say(msg: str) -> None:
    sys.stdout.write(msg)
    if not msg.endswith("\n"):
        sys.stdout.write("\n")


# ----- main loop ------------------------------------------------------------


def interview_field(
    field_schema: FieldSchema,
    history: Dict[str, str],
    *,
    ask: Callable[[str], str] = _default_ask,
    say: Callable[[str], None] = _default_say,
    agent_runner: Optional[Any] = None,
    max_iter: int = MAX_ITER_DEFAULT,
    required_context: Optional[Dict[str, Any]] = None,
) -> FieldOutcome:
    """Interview a single field per plan §4."""
    required_context = required_context or {}

    # Skip optional fields if user just wants to opt out.
    is_required = field_schema.is_required(required_context)
    prompt_extra = "" if is_required else " (optional -- blank to skip)"
    header = f"\n[{field_schema.name}]{prompt_extra}"
    say(header)
    if field_schema.help_text:
        say(f"  hint: {field_schema.help_text}")

    answer = ask(field_schema.prompt)

    # EOF on the very first prompt -> accept-as-is empty / skip.
    if answer == _EOF_SENTINEL:
        return FieldOutcome(
            name=field_schema.name,
            answer="",
            final_score=0.0,
            iterations=0,
            accepted_as_is=True,
            gaps_at_commit=["no input (stdin EOF)"],
        )

    # Optional + empty -> immediate commit.
    if not is_required and not answer.strip():
        return FieldOutcome(
            name=field_schema.name,
            answer="",
            final_score=1.0,
            iterations=0,
            accepted_as_is=False,
            gaps_at_commit=[],
        )

    clarity: ClarityResult = evaluate(answer, field_schema, history, agent_runner)
    iterations = 0
    while not clarity.ready_to_commit and iterations < max_iter:
        iterations += 1
        follow_up = compose_follow_up(clarity.gaps, field_schema)
        say(f"  clarity: {clarity.summary()}")
        say(f"  follow-up #{iterations}: {follow_up}")
        add = ask("  add detail (or 'accept' to keep as-is)")
        # EOF mid-loop -> accept-as-is with whatever we have.
        if add == _EOF_SENTINEL or add.strip().lower() in {
            "accept", "accept-as-is", "keep",
        }:
            return FieldOutcome(
                name=field_schema.name,
                answer=answer,
                final_score=clarity.score,
                iterations=iterations,
                accepted_as_is=True,
                gaps_at_commit=list(clarity.gaps),
            )
        # Augment, don't replace.
        if add.strip():
            answer = _augment(answer, add)
        clarity = evaluate(answer, field_schema, history, agent_runner)

    return FieldOutcome(
        name=field_schema.name,
        answer=answer,
        final_score=clarity.score,
        iterations=iterations,
        accepted_as_is=(iterations >= max_iter and not clarity.ready_to_commit),
        gaps_at_commit=list(clarity.gaps) if not clarity.ready_to_commit else [],
    )


def _augment(original: str, addition: str) -> str:
    """Merge a follow-up answer into the original. Newline-joined.

    Preserves the original text so detail accumulates across passes.
    If the original was a single short phrase and the addition is a
    full sentence, the addition goes FIRST so the composite reads
    naturally.
    """
    orig = (original or "").strip()
    add = (addition or "").strip()
    if not orig:
        return add
    if not add:
        return orig
    # If the original is a list (>=2 lines), append.
    if "\n" in orig:
        return f"{orig}\n{add}"
    # Short original: prepend the richer detail.
    if len(orig.split()) < 8 and len(add.split()) > len(orig.split()):
        return f"{add} (originally: {orig})"
    return f"{orig} {add}"


def run_interview(
    schema: Schema,
    *,
    ask: Callable[[str], str] = _default_ask,
    say: Callable[[str], None] = _default_say,
    agent_runner: Optional[Any] = None,
    max_iter: int = MAX_ITER_DEFAULT,
    context: Optional[Dict[str, Any]] = None,
) -> InterviewResult:
    """Walk the schema and interview each field in order."""
    context = context or {}
    history: Dict[str, str] = {}
    outcomes: Dict[str, FieldOutcome] = {}

    say(f"\n=== Canon interview: {schema.type} ===")
    if schema.description:
        say(schema.description)

    for fs in schema.fields:
        o = interview_field(
            fs, history,
            ask=ask, say=say,
            agent_runner=agent_runner,
            max_iter=max_iter,
            required_context={**context, **history},
        )
        outcomes[fs.name] = o
        history[fs.name] = o.answer

    return InterviewResult(
        fields=dict(history),
        outcomes=outcomes,
    )


# ----- canned I/O for tests / batch mode ------------------------------------


def canned_ask(answers: List[str]) -> Callable[[str], str]:
    """Return an ask() that pops from `answers` in FIFO order.

    If the list runs out, returns '' -- modelling "user gave up". This
    is the adapter the smoke-test + unit tests use.
    """
    buf = list(answers)

    def _ask(_prompt: str) -> str:
        if not buf:
            return ""
        return buf.pop(0)

    return _ask


def silent_say() -> Callable[[str], None]:
    def _say(_msg: str) -> None:
        pass
    return _say


def capturing_say() -> "tuple[Callable[[str], None], io.StringIO]":
    buf = io.StringIO()

    def _say(msg: str) -> None:
        buf.write(msg)
        if not msg.endswith("\n"):
            buf.write("\n")

    return _say, buf
