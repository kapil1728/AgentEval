from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agenteval.schemas import RunOutcome, RunRecord, RunRequest, TaskSpec


def test_task_spec_rejects_unknown_fields_and_invalid_ids() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(
            task_id="../escape",
            title="Bad task",
            workspace="task",
            docker_image="python:3.12-slim",
            agent_command="true",
            test_command="true",
            unexpected="value",
        )


def test_run_outcome_requires_pass_to_match_status() -> None:
    with pytest.raises(ValidationError, match="passed must be true"):
        RunOutcome(status="failed", passed=True, latency_seconds=1.0)


def test_run_record_serializes_version_dimensions() -> None:
    record = RunRecord(
        id=1,
        task_id="sample",
        agent_version="agent-a",
        model_version="model-a",
        prompt_version="prompt-a",
        passed=True,
        status="passed",
        cost_usd=0.01,
        latency_seconds=3.5,
        started_at=datetime.now(UTC),
        logs="ok",
    )
    assert record.model_version == "model-a"
    assert RunRequest(agent_version="a", model_version="m", prompt_version="p").cost_usd == 0
