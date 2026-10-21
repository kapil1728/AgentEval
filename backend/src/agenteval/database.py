from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    and_,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from agenteval.schemas import (
    RunOutcome,
    RunRecord,
    RunRequest,
    ScoringRunRecord,
    TaskSpec,
    VersionLabel,
)

if TYPE_CHECKING:
    from agenteval.scoring import ScoredRun


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    workspace: Mapped[str] = mapped_column(Text, nullable=False)
    docker_image: Mapped[str] = mapped_column(String(300), nullable=False)
    agent_command: Mapped[str] = mapped_column(Text, nullable=False)
    test_command: Mapped[str] = mapped_column(Text, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False, index=True)
    agent_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    latency_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    logs: Mapped[str] = mapped_column(Text, nullable=False)


class ScoringRunRow(Base):
    __tablename__ = "scoring_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    agent_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    git_sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    tests_passed: Mapped[int] = mapped_column(Integer, nullable=False)
    tests_total: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_size: Mapped[int] = mapped_column(Integer, nullable=False)
    wall_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    output: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False, default="")


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    connect_args = (
        {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            if "scoring_runs" in tables:
                columns = {
                    column["name"] for column in inspect(connection).get_columns("scoring_runs")
                }
                if "diff" not in columns:
                    connection.execute(
                        text("ALTER TABLE scoring_runs ADD COLUMN diff TEXT NOT NULL DEFAULT ''")
                    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def upsert_task(session: Session, task: TaskSpec) -> TaskRow:
    row = session.get(TaskRow, task.task_id)
    if row is None:
        row = TaskRow(task_id=task.task_id)
        session.add(row)
    row.title = task.title
    row.workspace = task.workspace
    row.docker_image = task.docker_image
    row.agent_command = task.agent_command
    row.test_command = task.test_command
    row.timeout_seconds = task.timeout_seconds
    session.commit()
    session.refresh(row)
    return row


def get_task(session: Session, task_id: str) -> TaskRow | None:
    return session.get(TaskRow, task_id)


def record_run(
    session: Session,
    task_id: str,
    request: RunRequest,
    outcome: RunOutcome,
) -> RunRecord:
    row = RunRow(
        task_id=task_id,
        agent_version=request.agent_version,
        model_version=request.model_version,
        prompt_version=request.prompt_version,
        passed=outcome.passed,
        status=outcome.status,
        cost_usd=request.cost_usd,
        latency_seconds=outcome.latency_seconds,
        started_at=datetime.now(UTC),
        logs=outcome.logs,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return RunRecord.model_validate(row)


def list_runs(session: Session, limit: int = 100) -> list[RunRecord]:
    rows = session.scalars(
        select(RunRow).order_by(RunRow.started_at.desc(), RunRow.id.desc()).limit(limit)
    )
    return [RunRecord.model_validate(row) for row in rows]


def record_scoring_run(
    session: Session,
    task_id: str,
    version: VersionLabel,
    result: ScoredRun,
) -> ScoringRunRecord:
    row = ScoringRunRow(
        task_id=task_id,
        agent_version=version.agent_version,
        model_version=version.model_version,
        prompt_hash=version.prompt_hash,
        git_sha=version.git_sha,
        passed=result.passed,
        status=result.status,
        tests_passed=result.tests_passed,
        tests_total=result.tests_total,
        diff_size=result.diff_size,
        wall_time_seconds=result.wall_time_seconds,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        tool_call_count=result.tool_call_count,
        estimated_cost_usd=result.estimated_cost_usd,
        started_at=datetime.now(UTC) - timedelta(seconds=result.wall_time_seconds),
        output=result.output,
        diff=result.diff,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return ScoringRunRecord.model_validate(row)


def get_scoring_run(session: Session, run_id: int) -> ScoringRunRecord | None:
    row = session.get(ScoringRunRow, run_id)
    return ScoringRunRecord.model_validate(row) if row is not None else None


def list_scoring_runs(
    session: Session,
    limit: int = 100,
    task_id: str | None = None,
    version: VersionLabel | None = None,
) -> list[ScoringRunRecord]:
    query = select(ScoringRunRow)
    filters = []
    if task_id is not None:
        filters.append(ScoringRunRow.task_id == task_id)
    if version is not None:
        filters.extend(
            [
                ScoringRunRow.agent_version == version.agent_version,
                ScoringRunRow.model_version == version.model_version,
                ScoringRunRow.prompt_hash == version.prompt_hash,
                ScoringRunRow.git_sha == version.git_sha,
            ]
        )
    if filters:
        query = query.where(and_(*filters))
    rows = session.scalars(
        query.order_by(ScoringRunRow.started_at.desc(), ScoringRunRow.id.desc()).limit(limit)
    )
    return [ScoringRunRecord.model_validate(row) for row in rows]


def list_version_labels(session: Session, agent_version: str) -> list[VersionLabel]:
    rows = session.execute(
        select(
            ScoringRunRow.agent_version,
            ScoringRunRow.model_version,
            ScoringRunRow.prompt_hash,
            ScoringRunRow.git_sha,
        )
        .where(ScoringRunRow.agent_version == agent_version)
        .distinct()
        .order_by(
            ScoringRunRow.model_version,
            ScoringRunRow.prompt_hash,
            ScoringRunRow.git_sha,
        )
    )
    return [
        VersionLabel(
            agent_version=agent,
            model_version=model,
            prompt_hash=prompt,
            git_sha=git_sha,
        )
        for agent, model, prompt, git_sha in rows
    ]
