from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.orm import Session, sessionmaker

from agenteval.database import (
    create_session_factory,
    get_scoring_run,
    get_task,
    list_runs,
    list_scoring_runs,
    record_run,
    upsert_task,
)
from agenteval.metrics import compare_versions, summarize_runs
from agenteval.regression import compare_scoring_versions, scoring_trends
from agenteval.runner import DockerRunner, RunnerUnavailable
from agenteval.schemas import (
    CompareVersionsRequest,
    RegressionReport,
    RunMetrics,
    RunRecord,
    RunRequest,
    RunTrend,
    ScoringRunRecord,
    TaskSpec,
    VersionMetrics,
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def create_app(
    database_url: str | None = None,
    tasks_root: Path | None = None,
    runner: DockerRunner | None = None,
) -> FastAPI:
    database_url = database_url or os.getenv("AGENTEVAL_DATABASE_URL") or "sqlite:///./agenteval.db"
    tasks_root = tasks_root or Path(os.getenv("AGENTEVAL_TASKS_ROOT", "tasks"))
    session_factory = create_session_factory(database_url)
    app = FastAPI(title="AgentEval", version="0.1.0")
    app.state.session_factory = session_factory
    app.state.tasks_root = tasks_root
    app.state.runner = runner or DockerRunner()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/tasks", status_code=201)
    def create_task(task: TaskSpec, session: SessionDependency) -> TaskSpec:
        upsert_task(session, task)
        return task

    @app.post("/tasks/{task_id}/runs", response_model=RunRecord)
    def run_task(task_id: str, request: RunRequest, session: SessionDependency) -> RunRecord:
        task_row = get_task(session, task_id)
        if task_row is None:
            raise HTTPException(status_code=404, detail="Task not found")
        task = TaskSpec.model_validate(task_row, from_attributes=True)
        try:
            outcome = app.state.runner.run(tasks_root, task)
        except RunnerUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return record_run(session, task_id, request, outcome)

    @app.get("/runs", response_model=list[RunRecord])
    def get_runs(
        session: SessionDependency,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[RunRecord]:
        return list_runs(session, limit)

    @app.get("/metrics", response_model=RunMetrics)
    def get_metrics(session: SessionDependency) -> RunMetrics:
        return summarize_runs(session)

    @app.get("/metrics/versions", response_model=list[VersionMetrics])
    def get_version_metrics(session: SessionDependency) -> list[VersionMetrics]:
        return compare_versions(session)

    @app.get("/scoring/runs", response_model=list[ScoringRunRecord])
    def get_scoring_runs(
        session: SessionDependency,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        task_id: str | None = None,
    ) -> list[ScoringRunRecord]:
        return list_scoring_runs(session, limit=limit, task_id=task_id)

    @app.get("/scoring/runs/{run_id}", response_model=ScoringRunRecord)
    def get_scoring_run_detail(run_id: int, session: SessionDependency) -> ScoringRunRecord:
        run = get_scoring_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Scoring run not found")
        return run

    @app.post("/scoring/compare", response_model=RegressionReport)
    def compare_scoring_run_versions(
        request: CompareVersionsRequest,
        session: SessionDependency,
    ) -> RegressionReport:
        return compare_scoring_versions(
            session,
            baseline=request.baseline,
            candidate=request.candidate,
            alpha=request.alpha,
        )

    @app.get("/scoring/trends", response_model=list[RunTrend])
    def get_scoring_trends(
        session: SessionDependency,
        days: Annotated[int, Query(ge=1, le=365)] = 30,
        task_id: str | None = None,
    ) -> list[RunTrend]:
        return scoring_trends(session, days=days, task_id=task_id)

    return app


app = create_app()
