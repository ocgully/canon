# The clarity-loop (deep dive)

## Intent

SpecKit's Q&A stops at the user's first answer. Canon's doesn't. A clarity-loop evaluates every answer against the dimensions declared for that field and keeps asking follow-ups until the composite score clears the threshold -- or MAX_ITER trips and Canon accepts-as-is with a quality stamp.

**The loop is rules-first.** Regex + length + structure heuristics always run. If an agent runner is plugged in, it biases the score on top; it never replaces the rules. That's how Canon stays deterministic offline.

## Dimensions

| Dim | What it catches | Example bad | Example good |
|---|---|---|---|
| `specificity` | vague words without measurable content | "it's slow" | "cold-start P99 > 2000ms" |
| `testability` | unobservable outcomes | "should work" | "returns exit code 0" |
| `completeness` | missing sub-fields / min_items | 1 goal when 3 needed | 3 testable goals |
| `consistency` | surface contradiction with earlier answers | "no async" vs earlier "concurrent" | aligned claims |
| `scope_clarity` | missing in-scope / out-of-scope boundaries | "cache stuff" | "cache read paths; not writes" |
| `goal_coverage` | plan.approach doesn't mention each spec goal | approach skips 2 of 3 goals | approach names each |

## Composite scoring

The composite score is the **minimum** of the per-dim scores (weakest-link). That means you can't paper over a testability gap with strong specificity -- you have to fix the weakest dim.

## The augment-don't-replace rule

When a follow-up fires, the user's new text is **appended to or merged with** the original, not substituted. This is why a vague "it's slow" followed by "the test returns 200 after 2000ms" lands as a composite answer that contains both phrasings. The Pedia block captures the full composite; the original words are preserved in history.

## Accept-as-is escape hatch

After MAX_ITER iterations (or anytime you type `accept`), Canon commits the current text with:

```yaml
canon_field_quality:
  problem_statement:
    score: 0.42
    iterations: 5
    accepted_as_is: true
    gaps_at_commit: ["low specificity (score 0.32)", "low testability (score 0.42)"]
```

This metadata is a first-class signal: `canon check` in phase 1B can warn on blocks with accepted-as-is fields, and the phase-2 spec-quality assistant can prioritize them for review.

## Tuning

```bash
canon config set clarity.threshold 0.8     # harder to commit
canon config set clarity.max_iter 3        # faster giveup
```

Per-field overrides live in the schema source; to change a per-field threshold today, edit `canon/schemas/<type>.py` and submit a PR.

## Integration with an agent runner

`--agent claude` (or codex, etc.) changes the behaviour only after MAX_ITER trips, or when the rules score is borderline. Canon writes a structured context file:

```
.canon/interview-context/<session-id>/
  context.md       # human-readable -- task, gaps, answers-so-far
  context.json     # machine-readable sidecar
```

Then invokes the named binary with `--` stop-parsing, streams stdout back, and substitutes as the refined answer. If the binary isn't on PATH, the files are still written and the command runs the rules-only path. This is the same pattern as Sextant's AI conversation panel: Canon assembles context, the agent session holds the conversation.

Nothing is phoned home from Canon. No API key is required. No telemetry.

## Rules reference

The regex tables live in `canon/clarity.py`:

- `VAGUE_TOKENS` -- explicitly low-signal words
- `SPECIFIC_TOKENS` -- numbers + units + named metrics
- `TESTABLE_TOKENS` -- observable-outcome verbs and status codes
- `SCOPE_TOKENS` -- explicit scope markers

They are deliberately soft-edged -- not a one-word veto, just signals summed into a score. This lets the loop err on the side of "ask a follow-up" rather than "reject outright".
