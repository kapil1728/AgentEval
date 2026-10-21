import json
import threading
import time
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

import agenteval.cli as cli
from agenteval.agent_adapters import MockAdapter
from agenteval.cli import app
from agenteval.database import create_session_factory, record_scoring_run
from agenteval.schemas import Task
from agenteval.scoring import ScoredRun, TaskScore


def test_register_command_loads_manifest(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    manifest = tasks / "task.json"
    manifest.write_text(
        '{"task_id":"cli-sample","title":"CLI sample","workspace":"sample",'
        '"docker_image":"python:3.12-slim","agent_command":"true","test_command":"true"}',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        ["register", str(manifest)],
        env={
            "AGENTEVAL_DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}",
        },
    )
    assert result.exit_code == 0
    assert "Registered task cli-sample" in result.stdout


def test_run_command_respects_configured_concurrency(tmp_path: Path, monkeypatch) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    for task_id in ("task-a", "task-b", "task-c"):
        task_dir = tasks_dir / task_id
        task_dir.mkdir()
        (task_dir / "task.yaml").write_text(
            f"id: {task_id}\n"
            f"description: Run {task_id}\n"
            "category: bugfix\n"
            f"repo_snapshot_path: {task_id}/repo_snapshot\n"
            "setup_commands: []\n"
            "test_command: python -m pytest -q\n"
            "timeout: 30\n"
            "difficulty: easy\n",
            encoding="utf-8",
        )
    agent_config = tmp_path / "agent.yaml"
    agent_config.write_text(
        "agent_version: agent-v1\n"
        "model_version: model-v1\n"
        "prompt_hash: prompt-a\n"
        "git_sha: abc123\n"
        "command: 'agent-cli --prompt {instructions}'\n"
        "image: python:3.12-slim\n"
        "input_usd_per_million: 1.0\n"
        "output_usd_per_million: 2.0\n",
        encoding="utf-8",
    )
    lock = threading.Lock()
    active = 0
    max_active = 0

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def score(
            self,
            task: Task,
            adapter: MockAdapter,
            instructions: str,
            version: object,
            repeats: int,
        ) -> TaskScore:
            nonlocal active, max_active
            del adapter, instructions, version
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            result = ScoredRun(
                passed=True,
                status="passed",
                tests_passed=1,
                tests_total=1,
                diff_size=1,
                wall_time_seconds=0.03,
                input_tokens=1,
                output_tokens=1,
                tool_call_count=1,
                estimated_cost_usd=0.0,
                output="ok",
                run_id=1,
            )
            return TaskScore(
                task.id, tuple(result for _ in range(repeats)), 1.0, 1.0, (0.2, 1.0), 0.03, 0.0
            )

    monkeypatch.setattr(cli, "ScoringPipeline", FakePipeline)
    monkeypatch.setattr(cli, "_session_factory", lambda: cast(sessionmaker[Session], object()))
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--agent",
            str(agent_config),
            "--tasks",
            str(tasks_dir),
            "--repeats",
            "2",
            "--concurrency",
            "2",
            "--task-id",
            "task-a",
            "--task-id",
            "task-c",
        ],
    )

    assert result.exit_code == 0, result.output
    assert max_active == 2
    summaries = [json.loads(line) for line in result.stdout.splitlines()]
    assert {summary["task_id"] for summary in summaries} == {"task-a", "task-c"}
    assert all(len(summary["run_ids"]) == 2 for summary in summaries)


def test_compare_command_exits_nonzero_on_significant_regression(
    tmp_path: Path, monkeypatch
) -> None:
    factory = create_session_factory(f"sqlite:///{tmp_path / 'cli-compare.db'}")
    baseline = cli.VersionLabel(
        agent_version="agent-a", model_version="model", prompt_hash="prompt", git_sha="sha-a"
    )
    candidate = cli.VersionLabel(
        agent_version="agent-b", model_version="model", prompt_hash="prompt", git_sha="sha-b"
    )
    for _ in range(10):
        with factory() as session:
            record_scoring_run(session, "task", baseline, _scored_result(True))
            record_scoring_run(session, "task", candidate, _scored_result(False))
    monkeypatch.setattr(cli, "_session_factory", lambda: factory)

    result = CliRunner().invoke(app, ["compare", "agent-a", "agent-b"])

    assert result.exit_code == 1
    comparison = json.loads(result.stdout)
    assert comparison["overall"]["significant_regression"] is True


def test_report_command_prints_persisted_scoring_summary(tmp_path: Path, monkeypatch) -> None:
    factory = create_session_factory(f"sqlite:///{tmp_path / 'cli-report.db'}")
    with factory() as session:
        record_scoring_run(
            session,
            "task",
            cli.VersionLabel(
                agent_version="agent-a",
                model_version="model",
                prompt_hash="prompt",
                git_sha="sha-a",
            ),
            _scored_result(True),
        )
    monkeypatch.setattr(cli, "_session_factory", lambda: factory)

    result = CliRunner().invoke(app, ["report"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["overall"]["runs"] == 1
    assert report["overall"]["pass_rate"] == 1.0
    assert report["by_task"][0]["task_id"] == "task"


def _scored_result(passed: bool) -> ScoredRun:
    return ScoredRun(
        passed=passed,
        status="passed" if passed else "failed",
        tests_passed=1 if passed else 0,
        tests_total=1,
        diff_size=1,
        wall_time_seconds=1.0,
        input_tokens=2,
        output_tokens=1,
        tool_call_count=1,
        estimated_cost_usd=0.001,
        output="mock output",
    )
