from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from docker.client import DockerClient
from docker.errors import DockerException

from agenteval.runner import DockerRunner, RunnerUnavailable, resolve_task_workspace
from agenteval.sandbox import ExecResult
from agenteval.schemas import TaskSpec


def sample_task() -> TaskSpec:
    return TaskSpec(
        task_id="sample",
        title="Sample",
        workspace="sample",
        docker_image="python:3.12-slim",
        agent_command="true",
        test_command="python -m unittest",
    )


def test_resolve_workspace_rejects_traversal(tmp_path: Path) -> None:
    (tmp_path / "task").mkdir()
    with pytest.raises(ValueError, match="beneath"):
        resolve_task_workspace(tmp_path, "../outside")


def test_runner_copies_task_and_requires_agent_and_tests_to_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "sample"
    workspace.mkdir()
    sandbox = Mock()
    sandbox.__enter__ = Mock(return_value=sandbox)
    sandbox.__exit__ = Mock(return_value=None)
    sandbox.exec.side_effect = [ExecResult(1, "agent failed"), ExecResult(0, "tests passed")]
    monkeypatch.setattr("agenteval.runner.SandboxRunner", Mock(return_value=sandbox))

    result = DockerRunner(cast(DockerClient, Mock())).run(tmp_path, sample_task())

    sandbox.copy_in.assert_called_once_with(workspace)
    assert [call.args[0] for call in sandbox.exec.call_args_list] == [
        "true",
        "python -m unittest",
    ]
    assert result.status == "failed"
    assert result.passed is False
    sandbox.__exit__.assert_called_once()


def test_runner_fails_closed_without_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sample").mkdir()
    monkeypatch.setattr(
        "agenteval.sandbox.docker.from_env", Mock(side_effect=DockerException("offline"))
    )
    with pytest.raises(RunnerUnavailable, match="never falls back"):
        DockerRunner().run(tmp_path, sample_task())
