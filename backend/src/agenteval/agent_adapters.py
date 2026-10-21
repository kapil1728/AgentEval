from __future__ import annotations

import re
import shlex
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from docker.client import DockerClient

from agenteval.sandbox import SandboxRunner


@dataclass(frozen=True)
class AgentResult:
    input_tokens: int
    output_tokens: int
    tool_call_count: int
    wall_time_seconds: float
    exit_code: int
    output: str


@dataclass(frozen=True)
class UsageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0


UsageParser = Callable[[str], UsageMetrics]
SandboxFactory = Callable[..., SandboxRunner]
_USAGE_MARKER = re.compile(
    r"AGENTEVAL_USAGE input_tokens=(\d+) output_tokens=(\d+) tool_calls=(\d+)"
)


def parse_usage_marker(output: str) -> UsageMetrics:
    """Parse the vendor-neutral usage marker emitted by a configured CLI wrapper."""
    matches = list(_USAGE_MARKER.finditer(output))
    if not matches:
        return UsageMetrics()
    input_tokens, output_tokens, tool_calls = (int(value) for value in matches[-1].groups())
    return UsageMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_call_count=tool_calls,
    )


class AgentAdapter(ABC):
    @abstractmethod
    def run(self, task_workspace: Path, instructions: str) -> AgentResult:
        """Run the agent against a task workspace and return its usage and result."""

    def run_in_sandbox(
        self,
        sandbox: SandboxRunner,
        task_workspace: Path,
        instructions: str,
    ) -> AgentResult:
        raise NotImplementedError("adapters used by ScoringPipeline must support its sandbox")


class CommandAdapter(AgentAdapter):
    def __init__(
        self,
        command: str,
        image: str,
        timeout_seconds: float = 900,
        cpu_limit: float = 2.0,
        memory_limit: str | int = "2g",
        client: DockerClient | None = None,
        sandbox_factory: SandboxFactory | None = None,
        usage_parser: UsageParser = parse_usage_marker,
    ) -> None:
        if not command.strip():
            raise ValueError("command must not be empty")
        self._command = command
        self._image = image
        self._timeout_seconds = timeout_seconds
        self._cpu_limit = cpu_limit
        self._memory_limit = memory_limit
        self._client = client
        self._sandbox_factory = sandbox_factory or SandboxRunner
        self._usage_parser = usage_parser

    def run(self, task_workspace: Path, instructions: str) -> AgentResult:
        started = time.monotonic()
        workspace = task_workspace.resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("task_workspace must be a directory")

        with self._sandbox_factory(
            image=self._image,
            timeout_seconds=self._timeout_seconds,
            cpu_limit=self._cpu_limit,
            memory_limit=self._memory_limit,
            network_disabled=True,
            client=self._client,
        ) as sandbox:
            sandbox.copy_in(workspace)
            result = self.run_in_sandbox(sandbox, workspace, instructions)
        return replace(result, wall_time_seconds=time.monotonic() - started)

    def run_in_sandbox(
        self,
        sandbox: SandboxRunner,
        task_workspace: Path,
        instructions: str,
    ) -> AgentResult:
        del task_workspace
        started = time.monotonic()
        rendered_command = _render_command(self._command, instructions)
        execution = sandbox.exec(rendered_command)
        usage = self._usage_parser(execution.output)
        return AgentResult(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tool_call_count=usage.tool_call_count,
            wall_time_seconds=time.monotonic() - started,
            exit_code=execution.exit_code,
            output=execution.output,
        )


def _render_command(command: str, instructions: str) -> str:
    replacements = {
        "{workspace}": shlex.quote("/workspace"),
        "{instructions}": shlex.quote(instructions),
    }
    for placeholder, value in replacements.items():
        command = command.replace(placeholder, value)
    return command


class MockBehavior(StrEnum):
    SUCCEEDS = "succeeds"
    FAILS = "fails"
    FLAKY = "flaky"
    SLOW = "slow"


class MockAdapter(AgentAdapter):
    def __init__(
        self,
        behavior: MockBehavior,
        delay_seconds: float = 0.1,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")
        self._behavior = behavior
        self._delay_seconds = delay_seconds
        self._run_count = 0

    def run(self, task_workspace: Path, instructions: str) -> AgentResult:
        del task_workspace
        started = time.monotonic()
        self._run_count += 1

        if self._behavior is MockBehavior.SLOW:
            time.sleep(self._delay_seconds)
        failed = self._behavior is MockBehavior.FAILS or (
            self._behavior is MockBehavior.FLAKY and self._run_count % 2 == 1
        )
        output = "scripted failure" if failed else "scripted success"
        return AgentResult(
            input_tokens=len(instructions.split()),
            output_tokens=len(output.split()),
            tool_call_count=0 if failed else 1,
            wall_time_seconds=time.monotonic() - started,
            exit_code=1 if failed else 0,
            output=output,
        )

    def run_in_sandbox(
        self,
        sandbox: SandboxRunner,
        task_workspace: Path,
        instructions: str,
    ) -> AgentResult:
        del sandbox
        return self.run(task_workspace, instructions)
