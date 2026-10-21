from __future__ import annotations

import shlex
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from docker.client import DockerClient

from agenteval.agent_adapters import (
    AgentAdapter,
    AgentResult,
    CommandAdapter,
    MockAdapter,
    MockBehavior,
    UsageMetrics,
    parse_usage_marker,
)
from agenteval.sandbox import ExecResult, SandboxRunner


@pytest.mark.parametrize(
    ("behavior", "expected_exit"),
    [(MockBehavior.SUCCEEDS, 0), (MockBehavior.FAILS, 1)],
)
def test_mock_adapter_success_and_failure(
    tmp_path: Path, behavior: MockBehavior, expected_exit: int
) -> None:
    result = MockAdapter(behavior).run(tmp_path, "fix the issue")

    assert result.exit_code == expected_exit
    assert result.input_tokens == 3
    assert result.output_tokens > 0
    assert result.wall_time_seconds >= 0


def test_mock_adapter_flaky_behavior_alternates_results(tmp_path: Path) -> None:
    adapter = MockAdapter(MockBehavior.FLAKY)

    first = adapter.run(tmp_path, "instructions")
    second = adapter.run(tmp_path, "instructions")
    third = adapter.run(tmp_path, "instructions")

    assert [first.exit_code, second.exit_code, third.exit_code] == [1, 0, 1]


def test_mock_adapter_slow_behavior_reports_elapsed_time(tmp_path: Path) -> None:
    adapter = MockAdapter(MockBehavior.SLOW, delay_seconds=0.02)

    result = adapter.run(tmp_path, "wait")

    assert result.exit_code == 0
    assert result.wall_time_seconds >= 0.02


def test_usage_parser_reads_last_vendor_neutral_marker() -> None:
    usage = parse_usage_marker(
        "AGENTEVAL_USAGE input_tokens=3 output_tokens=2 tool_calls=1\n"
        "AGENTEVAL_USAGE input_tokens=8 output_tokens=5 tool_calls=4"
    )

    assert usage == UsageMetrics(input_tokens=8, output_tokens=5, tool_call_count=4)
    assert parse_usage_marker("no usage metadata") == UsageMetrics()


def test_command_adapter_runs_template_inside_sandbox(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    sandbox = Mock()
    sandbox.__enter__ = Mock(return_value=sandbox)
    sandbox.__exit__ = Mock(return_value=None)
    sandbox.exec.return_value = ExecResult(
        exit_code=0,
        output="done\nAGENTEVAL_USAGE input_tokens=10 output_tokens=6 tool_calls=2",
    )
    sandbox_factory = Mock(return_value=sandbox)
    command = CommandAdapter(
        command="agent-cli --prompt {instructions} --cwd {workspace}",
        image="agent-image:latest",
        timeout_seconds=60,
        cpu_limit=1.5,
        memory_limit="1g",
        client=cast(DockerClient, Mock()),
        sandbox_factory=cast(type[SandboxRunner], sandbox_factory),
    )

    result = command.run(workspace, 'fix "the bug"')

    sandbox.copy_in.assert_called_once_with(workspace)
    sandbox.exec.assert_called_once_with(
        f"agent-cli --prompt {shlex.quote('fix "the bug"')} --cwd /workspace"
    )
    sandbox_factory.assert_called_once_with(
        image="agent-image:latest",
        timeout_seconds=60,
        cpu_limit=1.5,
        memory_limit="1g",
        network_disabled=True,
        client=command._client,
    )
    assert result == AgentResult(
        input_tokens=10,
        output_tokens=6,
        tool_call_count=2,
        wall_time_seconds=result.wall_time_seconds,
        exit_code=0,
        output="done\nAGENTEVAL_USAGE input_tokens=10 output_tokens=6 tool_calls=2",
    )
    assert result.wall_time_seconds >= 0
    sandbox.__exit__.assert_called_once()


def test_command_adapter_rejects_empty_command() -> None:
    with pytest.raises(ValueError, match="command must not be empty"):
        CommandAdapter(command=" ", image="agent-image:latest")


def test_agent_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        AgentAdapter()
