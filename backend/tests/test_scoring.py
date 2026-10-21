from __future__ import annotations

import shutil
from pathlib import Path
from typing import cast

import pytest
from docker.client import DockerClient
from pydantic import ValidationError

from agenteval.agent_adapters import MockAdapter, MockBehavior
from agenteval.database import create_session_factory, list_scoring_runs
from agenteval.sandbox import ExecResult, SandboxRunner
from agenteval.schemas import Task, VersionLabel
from agenteval.scoring import ScoringPipeline, TokenPrice


class FakeSandbox:
    def __init__(
        self,
        workspace: Path,
        junit_xml: str,
        test_exit_code: int = 0,
        changed_files: dict[str, str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.junit_xml = junit_xml
        self.test_exit_code = test_exit_code
        self.changed_files = changed_files or {}
        self.workspace_copy_count = 0
        self.commands: list[str] = []
        self.copied_in: list[Path] = []
        self.junit_path = ""
        self.cleaned = False

    def __enter__(self) -> FakeSandbox:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.cleaned = True

    def copy_in(self, source: Path, destination: str = "/workspace") -> None:
        self.copied_in.append(source)

    def exec(self, command: str) -> ExecResult:
        self.commands.append(command)
        if "--junitxml=" in command:
            self.junit_path = command.split("--junitxml=", maxsplit=1)[1]
            self.changed_files["test-generated.txt"] = "test-only change\n"
            return ExecResult(self.test_exit_code, "pytest output")
        return ExecResult(0, "setup complete")

    def copy_out(self, source: str, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.workspace, destination, dirs_exist_ok=True)
        if self.junit_path:
            (destination / Path(self.junit_path).name).write_text(self.junit_xml, encoding="utf-8")
        if self.workspace_copy_count > 0:
            for relative, contents in self.changed_files.items():
                path = destination / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents, encoding="utf-8")
        self.workspace_copy_count += 1


def make_task(workspace: str = "sample/repo_snapshot") -> Task:
    return Task(
        id="sample",
        description="Sample scoring task",
        category="bugfix",
        repo_snapshot_path=workspace,
        setup_commands=["python -m pip install -e ."],
        test_command="python -m pytest -q",
        timeout=30,
        difficulty="easy",
    )


def make_version(model_version: str = "model-v1") -> VersionLabel:
    return VersionLabel(
        agent_version="agent-v1",
        model_version=model_version,
        prompt_hash="prompt-hash-a",
        git_sha="a1b2c3d4",
    )


def make_pipeline(
    tmp_path: Path,
    sandboxes: list[FakeSandbox],
) -> ScoringPipeline:
    task_workspace = tmp_path / "sample" / "repo_snapshot"
    task_workspace.mkdir(parents=True, exist_ok=True)
    (task_workspace / "module.py").write_text("value = 1\n", encoding="utf-8")

    def sandbox_factory(**kwargs: object) -> SandboxRunner:
        del kwargs
        sandbox = FakeSandbox(
            workspace=task_workspace,
            junit_xml=(
                '<testsuites><testsuite tests="2" failures="0" errors="0" '
                'skipped="0"/></testsuites>'
            ),
            changed_files={"new.py": "first\nsecond\n"},
        )
        sandboxes.append(sandbox)
        return cast(SandboxRunner, sandbox)

    session_factory = create_session_factory("sqlite:///:memory:")
    return ScoringPipeline(
        tasks_root=tmp_path,
        image="python:3.12-slim",
        price_table={"model-v1": TokenPrice(2.0, 4.0)},
        session_factory=session_factory,
        client=cast(DockerClient, object()),
        sandbox_factory=sandbox_factory,
    )


def test_pipeline_runs_setup_agent_then_pytest_and_scores_result(tmp_path: Path) -> None:
    sandboxes: list[FakeSandbox] = []
    pipeline = make_pipeline(tmp_path, sandboxes)
    task = make_task()

    score = pipeline.score(task, MockAdapter(MockBehavior.SUCCEEDS), "fix this bug", make_version())

    run = score.runs[0]
    sandbox = sandboxes[0]
    assert sandbox.commands[0] == "python -m pip install -e ."
    assert "--junitxml=/workspace/agenteval-junit-" in sandbox.commands[1]
    assert run.passed is True
    assert run.tests_passed == 2
    assert run.tests_total == 2
    assert run.diff_size == 2
    assert "+++ b/new.py" in run.diff
    assert "+first" in run.diff
    assert run.input_tokens == 3
    assert run.output_tokens == 2
    assert run.tool_call_count == 1
    assert "setup complete" in run.output
    assert "scripted success" in run.output
    assert "pytest output" in run.output
    assert run.estimated_cost_usd == pytest.approx(0.000014)
    assert score.pass_at_1 == 1.0
    assert score.pass_rate == 1.0
    assert score.total_estimated_cost_usd == pytest.approx(run.estimated_cost_usd)
    assert score.pass_rate_ci95[0] <= score.pass_rate <= score.pass_rate_ci95[1]
    assert score.median_latency_seconds == run.wall_time_seconds
    assert sandbox.copied_in == [tmp_path / "sample" / "repo_snapshot"]
    assert sandbox.cleaned is True
    with pipeline._session_factory() as session:
        stored_runs = list_scoring_runs(session)
    assert len(stored_runs) == 1
    assert stored_runs[0].id == run.run_id
    assert stored_runs[0].git_sha == "a1b2c3d4"
    assert "+++ b/new.py" in stored_runs[0].diff


def test_repeated_flaky_runs_compute_pass_at_1_rate_and_median(tmp_path: Path) -> None:
    sandboxes: list[FakeSandbox] = []
    pipeline = make_pipeline(tmp_path, sandboxes)

    score = pipeline.score(
        make_task(),
        MockAdapter(MockBehavior.FLAKY),
        "fix the bug",
        make_version(),
        repeats=3,
    )

    assert len(score.runs) == 3
    assert len({id(sandbox) for sandbox in sandboxes}) == 3
    assert [run.passed for run in score.runs] == [False, True, False]
    assert score.pass_at_1 == 0.0
    assert score.pass_rate == pytest.approx(1 / 3)
    lower, upper = score.pass_rate_ci95
    assert 0 <= lower < score.pass_rate < upper <= 1
    assert score.median_latency_seconds == pytest.approx(
        sorted(run.wall_time_seconds for run in score.runs)[1]
    )
    assert all(sandbox.cleaned for sandbox in sandboxes)


def test_test_failure_uses_junit_counts_even_when_agent_succeeds(tmp_path: Path) -> None:
    sandboxes: list[FakeSandbox] = []
    pipeline = make_pipeline(tmp_path, sandboxes)
    sandbox_factory = pipeline._sandbox_factory

    def failing_tests_factory(**kwargs: object) -> SandboxRunner:
        sandbox = cast(FakeSandbox, sandbox_factory(**kwargs))
        sandbox.junit_xml = (
            '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="0"/></testsuites>'
        )
        sandbox.test_exit_code = 1
        return cast(SandboxRunner, sandbox)

    pipeline._sandbox_factory = failing_tests_factory
    score = pipeline.score(make_task(), MockAdapter(MockBehavior.SUCCEEDS), "fix", make_version())

    assert score.runs[0].passed is False
    assert score.runs[0].tests_passed == 2
    assert score.runs[0].tests_total == 3


def test_pipeline_rejects_invalid_repeat_count_and_unknown_model(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path, [])
    adapter = MockAdapter(MockBehavior.SUCCEEDS)

    with pytest.raises(ValueError, match="at least one"):
        pipeline.score(make_task(), adapter, "fix", make_version(), repeats=0)
    with pytest.raises(ValueError, match="no token price configured"):
        pipeline.score(make_task(), adapter, "fix", make_version("unknown"))


def test_task_schema_rejects_snapshot_traversal_before_scoring() -> None:
    with pytest.raises(ValidationError, match="beneath the task root"):
        make_task("../outside")


def test_pipeline_requires_pytest_junit_output(tmp_path: Path) -> None:
    sandboxes: list[FakeSandbox] = []
    pipeline = make_pipeline(tmp_path, sandboxes)
    task = make_task()
    task = task.model_copy(update={"test_command": "python -m unittest"})

    with pytest.raises(ValueError, match="pytest"):
        pipeline.score(task, MockAdapter(MockBehavior.SUCCEEDS), "fix", make_version())


def test_pipeline_persists_failure_if_junit_report_is_missing(tmp_path: Path) -> None:
    sandboxes: list[FakeSandbox] = []
    pipeline = make_pipeline(tmp_path, sandboxes)
    default_factory = pipeline._sandbox_factory

    def missing_report_factory(**kwargs: object) -> SandboxRunner:
        sandbox = cast(FakeSandbox, default_factory(**kwargs))
        original_copy_out = sandbox.copy_out

        def copy_out(source: str, destination: Path) -> None:
            if source == "/workspace" and sandbox.workspace_copy_count >= 2:
                return
            original_copy_out(source, destination)

        sandbox.copy_out = copy_out
        return cast(SandboxRunner, sandbox)

    pipeline._sandbox_factory = missing_report_factory

    score = pipeline.score(make_task(), MockAdapter(MockBehavior.SUCCEEDS), "fix", make_version())

    assert score.runs[0].status == "failed"
    assert "JUnit XML" in score.runs[0].output
    assert score.runs[0].run_id is not None
    assert sandboxes[0].cleaned is True
