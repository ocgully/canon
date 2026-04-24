"""Clarity-loop evaluator (plan §4).

Rules-first scoring: regex + length + structure heuristics score a raw
answer against the dims declared on the field. If an optional agent
runner is configured, it can bias the score; but rules always run
first, because rules are deterministic and rules always produce a
score even offline.

Scoring is deliberately soft-edged so that 'barely under the threshold'
still fires a useful follow-up rather than collapsing to 0. The
composite is the MIN of the per-dim scores (weakest-link), plus a
hard-gap list that the interview turns into targeted follow-ups.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ----- soft regex signals ---------------------------------------------------

# Tokens that suggest vagueness if present and nothing more specific.
VAGUE_TOKENS = re.compile(
    r"\b(slow|fast|good|bad|better|worse|nice|easy|hard|maybe|probably|"
    r"should\s+work|just\s+works|stuff|things|etc\.?|some|soon|later)\b",
    re.IGNORECASE,
)

# Tokens that suggest specificity: numbers + units, named metrics.
SPECIFIC_TOKENS = re.compile(
    r"(\b\d+(\.\d+)?\s*(ms|s|sec|secs|seconds|kb|mb|gb|tb|req|rps|%|percent|"
    r"p50|p95|p99|p999)\b"
    r"|\b(P50|P95|P99|P999|SLA|SLO|RPS|QPS|TTFB|TTI|LCP|FID|CLS)\b"
    r"|\b(http|https)://"
    r"|\b(\d{3,})\b)",
    re.IGNORECASE,
)

# Tokens that suggest testability: observable outcomes.
TESTABLE_TOKENS = re.compile(
    r"\b("
    r"returns?|yields?|emits?|writes?|raises?|contains?|matches?|equals?|"
    r"200|201|204|400|401|403|404|422|500|503|"
    r"within|under|below|above|at\s+most|at\s+least|less\s+than|greater\s+than|"
    r"exit\s+code|status\s+code|assert|expect|test"
    r")\b",
    re.IGNORECASE,
)

# Scope markers.
SCOPE_TOKENS = re.compile(
    r"\b(in\s+scope|out\s+of\s+scope|does\s+not|won'?t|won t|excluded?|"
    r"not\s+(?:addressing|handling|covering))\b",
    re.IGNORECASE,
)


@dataclass
class ClarityResult:
    """What the evaluator learned about an answer."""

    score: float                 # composite in [0, 1]
    dim_scores: Dict[str, float] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)  # human-readable gap descriptions
    ready_to_commit: bool = False

    def summary(self) -> str:
        dims = ", ".join(f"{k}={v:.2f}" for k, v in sorted(self.dim_scores.items()))
        gaps = "; ".join(self.gaps) if self.gaps else "no gaps"
        return f"score={self.score:.2f} ({dims}) [{gaps}]"


def _score_specificity(text: str) -> float:
    if not text.strip():
        return 0.0
    vague_hits = len(VAGUE_TOKENS.findall(text))
    specific_hits = len(SPECIFIC_TOKENS.findall(text))
    # Base: 0.5; +0.15 per specific hit, -0.2 per vague hit; clamp [0,1].
    base = 0.5
    base += 0.15 * specific_hits
    base -= 0.2 * vague_hits
    # Length matters up to a point (1 word answers rarely are specific).
    n_words = len(text.split())
    if n_words < 5:
        base -= 0.2
    elif n_words >= 15:
        base += 0.1
    return max(0.0, min(1.0, base))


def _score_testability(text: str) -> float:
    if not text.strip():
        return 0.0
    testable_hits = len(TESTABLE_TOKENS.findall(text))
    has_number = bool(SPECIFIC_TOKENS.search(text))
    vague_hits = len(VAGUE_TOKENS.findall(text))
    base = 0.4
    base += 0.2 * testable_hits
    if has_number:
        base += 0.2
    base -= 0.2 * vague_hits
    return max(0.0, min(1.0, base))


def _score_scope_clarity(text: str) -> float:
    if not text.strip():
        return 0.0
    scope_hits = len(SCOPE_TOKENS.findall(text))
    if scope_hits >= 1:
        return min(1.0, 0.6 + 0.15 * scope_hits)
    # Lists of items (one per line) get partial credit.
    non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(non_empty_lines) >= 2:
        return 0.55
    return 0.35


def _score_completeness(text: str, field_schema: Any) -> float:
    if not text.strip():
        return 0.0
    min_items = getattr(field_schema, "min_items", None)
    if min_items:
        non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(non_empty_lines) < min_items:
            return max(0.0, 0.3 * len(non_empty_lines) / max(1, min_items))
        return min(1.0, 0.7 + 0.1 * (len(non_empty_lines) - min_items))
    # No min_items: length as a soft proxy.
    n_words = len(text.split())
    if n_words < 3:
        return 0.2
    if n_words < 10:
        return 0.5
    return 0.8


def _score_consistency(text: str, history: Dict[str, str]) -> float:
    """Flag direct surface-level contradictions with earlier answers.

    Phase 1A is a heuristic: the same noun-phrase asserted in two
    directions by different fields is flagged. Not meant to catch deep
    semantic contradictions -- that's phase 2's job with an LLM.
    """
    if not text.strip():
        return 0.0
    # Cheap pass: if the field claims NOT-X and an earlier field claimed
    # X (or vice versa) for a short quoted token, drop the score.
    lowered = text.lower()
    flagged = False
    for prev_name, prev_answer in history.items():
        if not prev_answer:
            continue
        prev_low = prev_answer.lower()
        # Look for explicit "not X" vs "X" on 2+ word phrases.
        for m in re.finditer(r"\b(not|no|never)\s+(\w+\s+\w+)", lowered):
            phrase = m.group(2)
            if phrase in prev_low and f"not {phrase}" not in prev_low:
                flagged = True
                break
    return 0.5 if flagged else 0.9


def _score_goal_coverage(text: str, history: Dict[str, str]) -> float:
    """Plan.approach must mention each goal. Rough: fraction of goal
    bullets whose nouns appear in the approach text."""
    goals = history.get("goals", "") or ""
    if not goals.strip():
        return 0.7   # no goals yet -> can't measure; pass
    goal_lines = [ln.strip() for ln in goals.splitlines() if ln.strip()]
    if not goal_lines:
        return 0.7
    lowered = text.lower()
    hits = 0
    for gl in goal_lines:
        # Grab 2-3 "signal" words from the goal (>4 chars, not stopword).
        words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", gl)]
        stop = {"that", "this", "with", "from", "will", "must", "have",
                "they", "their", "ther", "then", "when", "each", "such",
                "should", "could", "would"}
        signal = [w for w in words if w not in stop][:3]
        if any(w in lowered for w in signal):
            hits += 1
    return min(1.0, hits / len(goal_lines))


def evaluate(
    answer: str,
    field_schema: Any,
    history: Optional[Dict[str, str]] = None,
    agent_runner: Optional[Any] = None,
) -> ClarityResult:
    """Score an answer against a field's clarity dimensions.

    Rules always run first and produce a baseline. If an agent_runner
    is supplied, its adjustments are applied on top -- but phase 1A
    does NOT ship an LLM-backed runner; offline is the default path.
    """
    history = history or {}
    dims = list(getattr(field_schema, "clarity_dims", []) or [])
    dim_scores: Dict[str, float] = {}

    for d in dims:
        if d == "specificity":
            dim_scores[d] = _score_specificity(answer)
        elif d == "testability":
            dim_scores[d] = _score_testability(answer)
        elif d == "scope_clarity":
            dim_scores[d] = _score_scope_clarity(answer)
        elif d == "completeness":
            dim_scores[d] = _score_completeness(answer, field_schema)
        elif d == "consistency":
            dim_scores[d] = _score_consistency(answer, history)
        elif d == "goal_coverage":
            dim_scores[d] = _score_goal_coverage(answer, history)
        else:
            # Unknown dim -> neutral pass.
            dim_scores[d] = 0.75

    # Always check completeness on list-shaped answers even if not
    # declared, so min_items is enforced.
    if getattr(field_schema, "min_items", None):
        complete = _score_completeness(answer, field_schema)
        dim_scores.setdefault("completeness", complete)

    # Composite: weakest link. Empty-answer overrides to 0.
    if not answer.strip():
        score = 0.0
    elif not dim_scores:
        # No dims declared -> presence alone scores mid (0.75).
        score = 0.75
    else:
        score = min(dim_scores.values())

    # Hard-gap detection: produce human-readable reasons to regenerate.
    # We flag a dim as a gap when it's the weakest AND it's under
    # threshold (not just under 0.5) -- so borderline answers still
    # produce a targeted follow-up.
    gaps: List[str] = []
    if not answer.strip():
        gaps.append("empty answer")
    threshold = getattr(field_schema, "threshold", 0.7)
    for dim, s in dim_scores.items():
        if s < 0.5:
            gaps.append(f"low {dim.replace('_', ' ')} (score {s:.2f})")
    # If score is under threshold but no dim was below 0.5, flag the
    # weakest dim so the follow-up is still targeted.
    if (dim_scores and min(dim_scores.values()) < threshold
            and not any(g.startswith("low ") for g in gaps)):
        weakest = min(dim_scores.items(), key=lambda kv: kv[1])
        gaps.append(
            f"low {weakest[0].replace('_', ' ')} (score {weakest[1]:.2f})"
        )
    # min_items shortfall is always a gap.
    min_items = getattr(field_schema, "min_items", None)
    if min_items:
        n_lines = len([ln for ln in (answer or "").splitlines() if ln.strip()])
        if n_lines < min_items:
            gaps.append(
                f"need at least {min_items} items (got {n_lines})"
            )

    ready = (score >= threshold) and not any(
        g.startswith("need at least") or g == "empty answer" for g in gaps
    )

    # Optional: let an agent_runner refine. Phase 1A stub: a runner
    # object is accepted but not required.
    if agent_runner is not None and hasattr(agent_runner, "refine_clarity"):
        try:
            refined = agent_runner.refine_clarity(answer, field_schema, history,
                                                  rules_score=score, gaps=gaps)
            if refined and isinstance(refined, dict):
                if "score" in refined:
                    score = (score + float(refined["score"])) / 2.0
                if "gaps" in refined:
                    gaps = list(gaps) + list(refined["gaps"] or [])
                ready = (score >= threshold) and not any(
                    g.startswith("need at least") or g == "empty answer"
                    for g in gaps
                )
        except Exception:  # pragma: no cover -- agent runner errors are soft
            pass

    return ClarityResult(
        score=round(score, 3),
        dim_scores={k: round(v, 3) for k, v in dim_scores.items()},
        gaps=gaps,
        ready_to_commit=ready,
    )


def compose_follow_up(gaps: List[str], field_schema: Any) -> str:
    """Turn a gap list into a targeted follow-up question.

    The engine PREPENDS the follow-up to the prior answer so detail
    augments rather than replaces ("augment, don't replace" from the
    spec)."""
    if not gaps:
        return "Can you add a bit more detail?"

    leading = gaps[0]
    name = field_schema.name.replace("_", " ")

    if "low specificity" in leading:
        return (
            f"That's a bit vague for '{name}'. Can you quantify it -- "
            "concrete numbers, units, named metrics, or a specific "
            "scenario? Replace words like 'slow' / 'better' / 'some' "
            "with measurable terms."
        )
    if "low testability" in leading:
        return (
            f"How would we TEST whether '{name}' is satisfied? Phrase "
            "it as an observable outcome (e.g. 'returns 200', 'completes "
            "in under N ms', 'produces file X with content Y')."
        )
    if "low scope clarity" in leading:
        return (
            f"Be explicit about what's IN scope vs OUT of scope for "
            f"'{name}'. List a few items on each side."
        )
    if "low completeness" in leading:
        return (
            f"The '{name}' answer feels thin. Can you expand -- more "
            "detail, or additional items?"
        )
    if "low consistency" in leading:
        return (
            f"The '{name}' answer seems to contradict something said "
            "earlier. Can you reconcile, or state which assertion wins?"
        )
    if "low goal coverage" in leading:
        return (
            f"The '{name}' doesn't obviously address every goal from "
            "the spec. Re-state it in a way that covers each goal."
        )
    if "need at least" in leading:
        return f"You need more items for '{name}'. {leading}. Add them, one per line."
    return f"The '{name}' answer needs work -- {leading}. Please revise."
