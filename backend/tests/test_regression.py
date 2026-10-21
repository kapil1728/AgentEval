from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from agenteval.database import create_session_factory, list_scoring_runs, record_scoring_run
from agenteval.regression import compare_scoring_versions, fisher_exact_regression, scoring_trends
from agenteval.schemas import VersionLabel
from agenteval.scoring import ScoredRun


def version(agent: str, git_sha: str) -> VersionLabel:
    return VersionLabel(
        agent_version=agent,
        model_version="model-1",
        prompt_hash="prompt-1",
        git_sha=git_sha,
    )


def record(session_factory: sessionmaker, task_id: str, label: VersionLabel, passed: bool) -> None:
    result = ScoredRun(
        passed=passed,
        status="passed" if passed else "failed",
        tests_passed=1 if passed else 0,
        tests_total=1,
        diff_size=1,
        wall_time_seconds=2.0,
        input_tokens=10,
        output_tokens=5,
        tool_call_count=1,
        estimated_cost_usd=0.001,
        output="mock output",
    )
    with session_factory() as session:
        record_scoring_run(session, task_id, label, result)


def test_fisher_exact_detects_only_significant_lower_pass_rate() -> None:
    assert fisher_exact_regression(10, 10, 0, 10) is not None
    assert fisher_exact_regression(10, 10, 0, 10) < 0.001
    assert fisher_exact_regression(5, 10, 5, 10) == 1.0
    assert fisher_exact_regression(5, 0, 2, 3) is None


def test_compare_versions_reports_overall_and_holm_adjusted_per_task() -> None:
    factory = create_session_factory("sqlite:///:memory:")
    baseline = version("agent-v1", "base-sha")
    candidate = version("agent-v2", "candidate-sha")
    for _ in range(10):
        record(factory, "regressed-task", baseline, True)
        record(factory, "regressed-task", candidate, False)
        record(factory, "stable-task", baseline, True)
        record(factory, "stable-task", candidate, True)

    with factory() as session:
        report = compare_scoring_versions(session, baseline, candidate)
        stringent_report = compare_scoring_versions(session, baseline, candidate, alpha=0.000001)
        runs = list_scoring_runs(session)

    assert len(runs) == 40
    assert report.overall.baseline_pass_rate == 1.0
    assert report.overall.candidate_pass_rate == 0.5
    assert report.overall.significant_regression is True
    assert stringent_report.overall.significant_regression is False
    regression = next(row for row in report.per_task if row.task_id == "regressed-task")
    stable = next(row for row in report.per_task if row.task_id == "stable-task")
    assert regression.significant_regression is True
    assert regression.adjusted_p_value is not None
    assert stable.significant_regression is False
    assert stable.candidate_pass_rate == stable.baseline_pass_rate


def test_scoring_trends_aggregate_runs_per_day_and_task() -> None:
    factory = create_session_factory("sqlite:///:memory:")
    baseline = version("agent-v1", "base-sha")
    record(factory, "trend-task", baseline, True)
    record(factory, "trend-task", baseline, False)

    with factory() as session:
        overall = scoring_trends(session, days=2)
        task_trend = scoring_trends(session, days=2, task_id="trend-task")

    assert len(overall) == 1
    assert overall[0].runs == 2
    assert overall[0].passed == 1
    assert overall[0].pass_rate == 0.5
    assert len(task_trend) == 1
    assert task_trend[0].task_id == "trend-task"
