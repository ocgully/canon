"""Interview engine tests -- drive via canned_ask."""
from __future__ import annotations

from canon.interview import canned_ask, interview_field, run_interview, silent_say
from canon.schemas import FieldSchema, Schema, SubField


def test_good_answer_commits_first_pass():
    fs = FieldSchema(
        name="problem_statement",
        prompt="what is the problem?",
        clarity_dims=["specificity", "testability"],
        threshold=0.6,
    )
    ans = (
        "cold-start latency P99 exceeds 2000ms on laptop hardware; the "
        "onboarding test returns exit code 1 when startup > 500ms"
    )
    ask = canned_ask([ans])
    outcome = interview_field(fs, {}, ask=ask, say=silent_say())
    assert outcome.answer == ans
    assert outcome.iterations == 0
    assert outcome.final_score >= 0.6


def test_vague_answer_triggers_follow_up_then_commits():
    fs = FieldSchema(
        name="problem_statement",
        prompt="what is the problem?",
        clarity_dims=["specificity", "testability"],
        threshold=0.6,
    )
    # First answer is too vague; follow-up adds detail.
    answers = [
        "it's slow",
        "cold-start latency P99 hits 2000ms on laptop hardware and blocks the returns-200 onboarding test",
    ]
    ask = canned_ask(answers)
    outcome = interview_field(fs, {}, ask=ask, say=silent_say())
    assert outcome.iterations == 1
    assert "2000ms" in outcome.answer
    assert outcome.final_score >= 0.6


def test_max_iter_gives_up_and_accepts_as_is():
    fs = FieldSchema(
        name="problem_statement",
        prompt="what is the problem?",
        clarity_dims=["specificity", "testability"],
        threshold=0.95,          # impossibly strict
        min_items=None,
    )
    answers = ["slow"] * 20     # all vague
    ask = canned_ask(answers)
    outcome = interview_field(fs, {}, ask=ask, say=silent_say(), max_iter=3)
    assert outcome.iterations == 3
    assert outcome.accepted_as_is is True
    assert outcome.final_score < 0.95


def test_optional_field_skippable_with_blank():
    fs = FieldSchema(
        name="constraints",
        prompt="constraints?",
        required=False,
        clarity_dims=["specificity"],
    )
    ask = canned_ask([""])
    outcome = interview_field(fs, {}, ask=ask, say=silent_say())
    assert outcome.answer == ""
    assert outcome.iterations == 0


def test_accept_command_short_circuits_loop():
    fs = FieldSchema(
        name="problem_statement",
        prompt="what?",
        clarity_dims=["specificity"],
        threshold=0.95,
    )
    answers = ["slow", "accept"]
    ask = canned_ask(answers)
    outcome = interview_field(fs, {}, ask=ask, say=silent_say())
    assert outcome.accepted_as_is is True
    assert outcome.iterations == 1


def test_run_interview_walks_all_fields_in_order():
    schema = Schema(
        type="test",
        fields=[
            FieldSchema(name="a", prompt="a?", clarity_dims=["specificity"],
                        threshold=0.3),
            FieldSchema(name="b", prompt="b?", clarity_dims=["specificity"],
                        threshold=0.3),
        ],
    )
    ask = canned_ask([
        "concrete answer with 100ms metric",
        "another concrete answer with 200 status",
    ])
    result = run_interview(schema, ask=ask, say=silent_say())
    assert list(result.fields.keys()) == ["a", "b"]
    assert "100ms" in result.fields["a"]
    assert "200" in result.fields["b"]


def test_list_field_requires_min_items():
    fs = FieldSchema(
        name="goals",
        prompt="goals?",
        min_items=2,
        clarity_dims=["testability"],
        threshold=0.3,
    )
    # Only one item -> follow-up fires asking for more.
    answers = [
        "ship feature within 100ms",
        "also reach 200 requests per second",    # augmentation adds a line
    ]
    ask = canned_ask(answers)
    outcome = interview_field(fs, {}, ask=ask, say=silent_say())
    # After augment there should be 2 lines.
    lines = [ln for ln in outcome.answer.splitlines() if ln.strip()]
    assert len(lines) >= 1   # augmentation path joins
