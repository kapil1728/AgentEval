from __future__ import annotations

import time
from pathlib import Path

from docker.client import DockerClient
from docker.errors import DockerException

from agenteval.sandbox import SandboxRunner, SandboxTimeout
from agenteval.schemas import RunOutcome, TaskSpec


class RunnerUnavailable(RuntimeError):
    """Raised when no usable Docker daemon is available."""


def resolve_task_workspace(tasks_root: Path, workspace: str) -> Path:
    root = tasks_root.resolve(strict=True)
    candidate = (root / workspace).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_dir():
        raise ValueError("task workspace must be a directory beneath the configured task root")
    return candidate


class DockerRunner:
    def __init__(self, client: DockerClient | None = None) -> None:
        self._client = client

    def run(self, tasks_root: Path, task: TaskSpec) -> RunOutcome:
        started = time.monotonic()
        try:
            workspace = resolve_task_workspace(tasks_root, task.workspace)
            with SandboxRunner(
                image=task.docker_image,
                timeout_seconds=task.timeout_seconds,
                client=self._client,
            ) as sandbox:
                sandbox.copy_in(workspace)
                agent_result = sandbox.exec(task.agent_command)
                test_result = sandbox.exec(task.test_command)
                passed = agent_result.exit_code == 0 and test_result.exit_code == 0
                logs = (
                    f"[agent exit {agent_result.exit_code}]\n{agent_result.output}\n"
                    f"[test exit {test_result.exit_code}]\n{test_result.output}"
                )[-100_000:]
                return RunOutcome(
                    status="passed" if passed else "failed",
                    passed=passed,
                    latency_seconds=time.monotonic() - started,
                    logs=logs,
                )
        except SandboxTimeout as error:
            return RunOutcome(
                status="timeout",
                passed=False,
                latency_seconds=time.monotonic() - started,
                logs=str(error),
            )
        except DockerException as error:
            raise RunnerUnavailable(
                "Docker is unavailable; agent execution never falls back to the host"
            ) from error
