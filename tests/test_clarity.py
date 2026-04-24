"""Clarity-loop evaluator unit tests."""
from __future__ import annotations

from canon.clarity import (
    compose_follow_up,
    evaluate,
    _score_specificity,
    _score_testability,
)
from canon.schemas import FieldSchema


def test_specificity_vague_answer_scores_low():
    # "slow" is explicitly in VAGUE_TOKENS, no units.
    assert _score_specificity("it's slow and bad") < 0.4


def test_specificity_numeric_answer_scores_high():
    # Numbers + units + named metric.
    s = _score_specificity(
        "cold-start latency P99 exceeds 2000ms on laptop hardware"
    )
    assert s >= 0.7, s


def test_testability_vague_answer_scores_low():
    assert _score_testability("should be fast and nice") < 0.5


def test_testability_observable_outcome_scores_high():
    s = _score_testability(
        "the CLI returns exit code 0 and writes a file with status 200"
    )
    assert s >= 0.7, s


def test_evaluate_empty_answer_always_fails():
    fs = FieldSchema(name="x", prompt="p", clarity_dims=["specificity"])
    r = evaluate("", fs)
    assert r.score == 0.0
    assert not r.ready_to_commit
    assert any("empty" in g for g in r.gaps)


def test_evaluate_below_threshold_produces_gaps():
    fs = FieldSchema(
        name="problem_statement",
        prompt="p",
        clarity_dims=["specificity", "testability"],
        threshold=0.7,
    )
    r = evaluate("it's slow", fs)
    assert not r.ready_to_commit
    # Both dims should be flagged as low.
    assert any("specificity" in g or "testability" in g for g in r.gaps)


def test_evaluate_at_threshold_commits():
    fs = FieldSchema(
        name="problem_statement",
        prompt="p",
        clarity_dims=["specificity", "testability"],
        threshold=0.6,
    )
    ans = (
        "cold-start latency exceeds 2000ms on laptop hardware; the test "
        "returns exit code 1 when startup is slower than 500ms"
    )
    r = evaluate(ans, fs)
    assert r.ready_to_commit, r.summary()


def test_min_items_enforced():
    fs = FieldSchema(
        name="goals",
        prompt="p",
        min_items=3,
        clarity_dims=["testability"],
    )
    r = evaluate("only one goal here", fs)
    assert not r.ready_to_commit
    assert any("need at least" in g for g in r.gaps)


def test_compose_follow_up_specificity_mentions_quantify():
    fs = FieldSchema(name="problem_statement", prompt="p",
                     clarity_dims=["specificity"])
    f = compose_follow_up(["low specificity (score 0.30)"], fs)
    assert "quantify" in f.lower() or "specific" in f.lower() or "numbers" in f.lower()


def test_consistency_flags_direct_contradiction():
    fs = FieldSchema(name="constraints", prompt="p",
                     clarity_dims=["consistency"])
    history = {
        "goals": "we must support concurrent requests at high volume",
    }
    r = evaluate("we will not support concurrent requests", fs, history)
    # consistency score should drop below 0.9 baseline.
    assert r.dim_scores["consistency"] <= 0.6


def test_goal_coverage_measured_against_history():
    fs = FieldSchema(name="approach", prompt="p", clarity_dims=["goal_coverage"])
    history = {"goals": "cache-latency under 5ms\ncache-hit-rate above 90%"}
    approach = "we add an LRU cache in front of the database to lower latency and raise hit rate"
    r = evaluate(approach, fs, history)
    assert r.dim_scores["goal_coverage"] >= 0.9
