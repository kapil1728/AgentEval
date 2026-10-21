from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from agenteval.database import ScoringRunRow
from agenteval.schemas import (
    RegressionReport,
    RegressionStats,
    RunTrend,
    VersionLabel,
)


def compare_scoring_versions(
    session: Session,
    baseline: VersionLabel,
    candidate: VersionLabel,
    alpha: float = 0.05,
) -> RegressionReport:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    baseline_runs = _runs_for_version(session, baseline)
    candidate_runs = _runs_for_version(session, candidate)
    overall = _compare_group(
        None,
        [passed for _, passed in baseline_runs],
        [passed for _, passed in candidate_runs],
        alpha,
    )

    task_ids = sorted({task_id for task_id, _ in baseline_runs + candidate_runs})
    per_task = [
        _compare_group(
            task_id,
            [passed for run_task, passed in baseline_runs if run_task == task_id],
            [passed for run_task, passed in candidate_runs if run_task == task_id],
            alpha,
        )
        for task_id in task_ids
    ]
    per_task = _apply_holm_correction(per_task, alpha)
    return RegressionReport(
        baseline=baseline,
        candidate=candidate,
        alpha=alpha,
        overall=overall,
        per_task=per_task,
    )


def _runs_for_version(session: Session, version: VersionLabel) -> list[tuple[str, bool]]:
    rows = session.execute(
        select(ScoringRunRow.task_id, ScoringRunRow.passed).where(
            ScoringRunRow.agent_version == version.agent_version,
            ScoringRunRow.model_version == version.model_version,
            ScoringRunRow.prompt_hash == version.prompt_hash,
            ScoringRunRow.git_sha == version.git_sha,
        )
    ).all()
    return [(task_id, passed) for task_id, passed in rows]


def _compare_group(
    task_id: str | None,
    baseline: list[bool],
    candidate: list[bool],
    alpha: float,
) -> RegressionStats:
    baseline_count = len(baseline)
    candidate_count = len(candidate)
    baseline_passed = sum(baseline)
    candidate_passed = sum(candidate)
    baseline_rate = baseline_passed / baseline_count if baseline_count else 0.0
    candidate_rate = candidate_passed / candidate_count if candidate_count else 0.0
    p_value = fisher_exact_regression(
        baseline_passed, baseline_count, candidate_passed, candidate_count
    )
    return RegressionStats(
        task_id=task_id,
        baseline_runs=baseline_count,
        baseline_passed=baseline_passed,
        baseline_pass_rate=baseline_rate,
        candidate_runs=candidate_count,
        candidate_passed=candidate_passed,
        candidate_pass_rate=candidate_rate,
        p_value=p_value,
        adjusted_p_value=p_value,
        significant_regression=(
            p_value is not None and candidate_rate < baseline_rate and p_value <= alpha
        ),
    )


def _apply_holm_correction(
    comparisons: list[RegressionStats], alpha: float
) -> list[RegressionStats]:
    testable: list[tuple[int, float]] = []
    for index, comparison in enumerate(comparisons):
        if comparison.p_value is not None:
            testable.append((index, comparison.p_value))
    ordered = sorted(testable, key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running_max = 0.0
    test_count = len(ordered)
    for rank, (index, p_value) in enumerate(ordered):
        running_max = max(running_max, min(1.0, p_value * (test_count - rank)))
        adjusted[index] = running_max

    return [
        comparison.model_copy(
            update={
                "adjusted_p_value": adjusted.get(index, comparison.p_value),
                "significant_regression": (
                    comparison.candidate_pass_rate < comparison.baseline_pass_rate
                    and adjusted.get(index, 1.0) <= alpha
                ),
            }
        )
        for index, comparison in enumerate(comparisons)
    ]


def fisher_exact_regression(
    baseline_passed: int,
    baseline_total: int,
    candidate_passed: int,
    candidate_total: int,
) -> float | None:
    """One-sided Fisher exact p-value for a lower candidate pass rate."""
    if baseline_total <= 0 or candidate_total <= 0:
        return None
    if not 0 <= baseline_passed <= baseline_total:
        raise ValueError("baseline pass count must be within its run count")
    if not 0 <= candidate_passed <= candidate_total:
        raise ValueError("candidate pass count must be within its run count")
    if candidate_passed / candidate_total >= baseline_passed / baseline_total:
        return 1.0

    population = baseline_total + candidate_total
    successes = baseline_passed + candidate_passed
    draws = candidate_total
    lower = max(0, draws - (population - successes))
    upper = min(candidate_passed, draws, successes)
    log_denominator = _log_choose(population, draws)
    probabilities = [
        math.exp(
            _log_choose(successes, candidate_successes)
            + _log_choose(population - successes, draws - candidate_successes)
            - log_denominator
        )
        for candidate_successes in range(lower, upper + 1)
    ]
    return min(1.0, math.fsum(probabilities))


def _log_choose(total: int, selected: int) -> float:
    if selected < 0 or selected > total:
        return -math.inf
    return math.lgamma(total + 1) - math.lgamma(selected + 1) - math.lgamma(total - selected + 1)


def scoring_trends(
    session: Session,
    days: int = 30,
    task_id: str | None = None,
) -> list[RunTrend]:
    if days < 1:
        raise ValueError("days must be at least one")
    day = func.date(ScoringRunRow.started_at)
    query = select(
        day,
        func.count(ScoringRunRow.id),
        func.coalesce(func.sum(ScoringRunRow.passed.cast(Integer)), 0),
        func.avg(ScoringRunRow.wall_time_seconds),
        func.avg(ScoringRunRow.estimated_cost_usd),
    ).where(ScoringRunRow.started_at >= datetime.now(UTC) - timedelta(days=days))
    if task_id is not None:
        query = query.where(ScoringRunRow.task_id == task_id)
    query = query.group_by(day).order_by(day)
    rows = session.execute(query).all()
    result: list[RunTrend] = []
    for day_value, total, passed, average_latency, average_cost in rows:
        run_count = cast(int, total)
        passed_count = cast(int, passed)
        result.append(
            RunTrend(
                day=str(day_value),
                task_id=task_id,
                runs=run_count,
                passed=passed_count,
                pass_rate=passed_count / run_count if run_count else 0.0,
                average_latency_seconds=cast(float, average_latency),
                average_cost_usd=cast(float, average_cost),
            )
        )
    return result
