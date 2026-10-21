from __future__ import annotations

from typing import cast

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from agenteval.database import RunRow, ScoringRunRow
from agenteval.schemas import (
    RunMetrics,
    ScoringAggregate,
    ScoringReport,
    TaskScoringAggregate,
    VersionMetrics,
    VersionScoringAggregate,
)


def summarize_runs(session: Session) -> RunMetrics:
    total, passed, average_cost, average_latency = cast(
        tuple[int, int, float, float],
        session.execute(
            select(
                func.count(RunRow.id),
                func.coalesce(func.sum(RunRow.passed.cast(Integer)), 0),
                func.coalesce(func.avg(RunRow.cost_usd), 0.0),
                func.coalesce(func.avg(RunRow.latency_seconds), 0.0),
            )
        ).one(),
    )
    return RunMetrics(
        total_runs=total,
        pass_rate=(passed / total) if total else 0.0,
        average_cost_usd=average_cost,
        average_latency_seconds=average_latency,
    )


def compare_versions(session: Session) -> list[VersionMetrics]:
    rows = cast(
        list[tuple[str, str, str, int, int, float, float]],
        session.execute(
            select(
                RunRow.agent_version,
                RunRow.model_version,
                RunRow.prompt_version,
                func.count(RunRow.id),
                func.coalesce(func.sum(RunRow.passed.cast(Integer)), 0),
                func.coalesce(func.avg(RunRow.cost_usd), 0.0),
                func.coalesce(func.avg(RunRow.latency_seconds), 0.0),
            )
            .group_by(RunRow.agent_version, RunRow.model_version, RunRow.prompt_version)
            .order_by(RunRow.agent_version, RunRow.model_version, RunRow.prompt_version)
        ).all(),
    )
    return [
        VersionMetrics(
            agent_version=agent_version,
            model_version=model_version,
            prompt_version=prompt_version,
            total_runs=total_runs,
            pass_rate=passed / total_runs,
            average_cost_usd=average_cost,
            average_latency_seconds=average_latency,
        )
        for (
            agent_version,
            model_version,
            prompt_version,
            total_runs,
            passed,
            average_cost,
            average_latency,
        ) in rows
    ]


def scoring_report(session: Session) -> ScoringReport:
    task_ids = session.scalars(
        select(ScoringRunRow.task_id).distinct().order_by(ScoringRunRow.task_id)
    )
    by_task = [
        TaskScoringAggregate(
            task_id=task_id,
            **_scoring_aggregate(session, [ScoringRunRow.task_id == task_id]).model_dump(),
        )
        for task_id in task_ids
    ]
    version_rows = session.execute(
        select(
            ScoringRunRow.agent_version,
            ScoringRunRow.model_version,
            ScoringRunRow.prompt_hash,
            ScoringRunRow.git_sha,
        )
        .distinct()
        .order_by(
            ScoringRunRow.agent_version,
            ScoringRunRow.model_version,
            ScoringRunRow.prompt_hash,
            ScoringRunRow.git_sha,
        )
    )
    by_version = [
        VersionScoringAggregate(
            agent_version=agent_version,
            model_version=model_version,
            prompt_hash=prompt_hash,
            git_sha=git_sha,
            **_scoring_aggregate(
                session,
                [
                    ScoringRunRow.agent_version == agent_version,
                    ScoringRunRow.model_version == model_version,
                    ScoringRunRow.prompt_hash == prompt_hash,
                    ScoringRunRow.git_sha == git_sha,
                ],
            ).model_dump(),
        )
        for agent_version, model_version, prompt_hash, git_sha in version_rows
    ]
    return ScoringReport(
        overall=_scoring_aggregate(session), by_task=by_task, by_version=by_version
    )


def _scoring_aggregate(
    session: Session,
    filters: list[ColumnElement[bool]] | None = None,
) -> ScoringAggregate:
    query = select(
        func.count(ScoringRunRow.id),
        func.coalesce(func.sum(ScoringRunRow.passed.cast(Integer)), 0),
        func.coalesce(func.avg(ScoringRunRow.wall_time_seconds), 0.0),
        func.coalesce(func.sum(ScoringRunRow.estimated_cost_usd), 0.0),
        func.coalesce(func.sum(ScoringRunRow.input_tokens), 0),
        func.coalesce(func.sum(ScoringRunRow.output_tokens), 0),
        func.coalesce(func.sum(ScoringRunRow.tool_call_count), 0),
    )
    if filters:
        query = query.where(*filters)
    runs, passed, average_latency, total_cost, input_tokens, output_tokens, tool_calls = cast(
        tuple[int, int, float, float, int, int, int], session.execute(query).one()
    )
    return ScoringAggregate(
        runs=runs,
        passed=passed,
        pass_rate=passed / runs if runs else 0.0,
        average_latency_seconds=average_latency,
        estimated_cost_usd=total_cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_call_count=tool_calls,
    )
