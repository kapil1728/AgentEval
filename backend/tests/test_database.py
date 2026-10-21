import sqlite3

from sqlalchemy.orm import Session

from agenteval.database import create_session_factory, get_task, list_runs, record_run, upsert_task
from agenteval.metrics import compare_versions, summarize_runs
from agenteval.schemas import RunOutcome, RunRequest, TaskSpec


def test_task_and_run_persist_with_metrics(tmp_path) -> None:
    factory = create_session_factory(f"sqlite:///{tmp_path / 'test.db'}")
    task = TaskSpec(
        task_id="sample",
        title="Sample",
        workspace="sample",
        docker_image="python:3.12-slim",
        agent_command="true",
        test_command="true",
    )
    request = RunRequest(agent_version="agent-1", model_version="model-1", prompt_version="p1")

    with factory() as session:
        assert isinstance(session, Session)
        upsert_task(session, task)
        assert get_task(session, "sample") is not None
        record_run(
            session,
            "sample",
            request,
            RunOutcome(status="passed", passed=True, latency_seconds=2.5),
        )
        record_run(
            session,
            "sample",
            RunRequest(
                agent_version="agent-2", model_version="model-1", prompt_version="p1", cost_usd=0.02
            ),
            RunOutcome(status="failed", passed=False, latency_seconds=4.0),
        )
        runs = list_runs(session)
        metrics = summarize_runs(session)
        comparisons = compare_versions(session)

    assert len(runs) == 2
    assert runs[0].agent_version == "agent-2"
    assert metrics.total_runs == 2
    assert metrics.pass_rate == 0.5
    assert metrics.average_latency_seconds == 3.25
    assert len(comparisons) == 2
    assert comparisons[0].agent_version == "agent-1"
    assert comparisons[0].pass_rate == 1.0
    assert comparisons[1].pass_rate == 0.0


def test_empty_metrics_are_zero(tmp_path) -> None:
    factory = create_session_factory(f"sqlite:///{tmp_path / 'empty.db'}")
    with factory() as session:
        metrics = summarize_runs(session)
    assert metrics.total_runs == 0
    assert metrics.pass_rate == 0.0


def test_sqlite_migration_adds_diff_to_existing_scoring_table(tmp_path) -> None:
    database_path = tmp_path / "before-diff.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """CREATE TABLE scoring_runs (
            id INTEGER PRIMARY KEY,
            task_id VARCHAR(100) NOT NULL,
            agent_version VARCHAR(100) NOT NULL,
            model_version VARCHAR(100) NOT NULL,
            prompt_hash VARCHAR(128) NOT NULL,
            git_sha VARCHAR(64) NOT NULL,
            passed BOOLEAN NOT NULL,
            status VARCHAR(20) NOT NULL,
            tests_passed INTEGER NOT NULL,
            tests_total INTEGER NOT NULL,
            diff_size INTEGER NOT NULL,
            wall_time_seconds FLOAT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            tool_call_count INTEGER NOT NULL,
            estimated_cost_usd FLOAT NOT NULL,
            started_at DATETIME NOT NULL,
            output TEXT NOT NULL
        )"""
    )
    connection.close()

    create_session_factory(f"sqlite:///{database_path}")

    with sqlite3.connect(database_path) as migrated:
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(scoring_runs)")}
    assert "diff" in columns
