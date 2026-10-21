from __future__ import annotations

from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
    description: str = Field(min_length=1, max_length=500)
    category: Literal["bugfix", "feature", "refactor"]
    repo_snapshot_path: Path
    setup_commands: list[str] = Field(default_factory=list)
    test_command: str = Field(min_length=1)
    timeout: int = Field(default=900, ge=1, le=7200)
    difficulty: Literal["easy", "medium", "hard"]

    @field_validator("repo_snapshot_path")
    @classmethod
    def snapshot_path_must_be_relative(cls, path: Path) -> Path:
        windows_path = PureWindowsPath(str(path))
        if (
            path.is_absolute()
            or windows_path.is_absolute()
            or ".." in path.parts
            or ".." in windows_path.parts
        ):
            raise ValueError("repo_snapshot_path must stay beneath the task root")
        return path


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: Literal["command", "mock"] = "command"
    agent_version: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    prompt_hash: str = Field(min_length=1, max_length=128)
    git_sha: str = Field(min_length=1, max_length=64)
    command: str | None = None
    mock_behavior: Literal["succeeds", "fails", "flaky", "slow"] = "succeeds"
    image: str = Field(min_length=1, max_length=300)
    input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)
    cpu_limit: float = Field(default=2.0, gt=0)
    memory_limit: str = Field(default="2g", min_length=1)

    @model_validator(mode="after")
    def command_required_for_command_adapter(self) -> AgentConfig:
        if self.adapter == "command" and (self.command is None or not self.command.strip()):
            raise ValueError("command is required when adapter is 'command'")
        return self


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
    title: str = Field(min_length=1, max_length=200)
    workspace: str = Field(min_length=1)
    docker_image: str = Field(min_length=1)
    agent_command: str = Field(min_length=1)
    test_command: str = Field(min_length=1)
    timeout_seconds: int = Field(default=900, ge=1, le=7200)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_version: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    cost_usd: float = Field(default=0.0, ge=0)


class RunRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    agent_version: str
    model_version: str
    prompt_version: str
    passed: bool
    status: Literal["passed", "failed", "timeout", "error"]
    cost_usd: float
    latency_seconds: float
    started_at: datetime
    logs: str


class RunMetrics(BaseModel):
    total_runs: int
    pass_rate: float
    average_cost_usd: float
    average_latency_seconds: float


class VersionMetrics(RunMetrics):
    agent_version: str
    model_version: str
    prompt_version: str


class VersionLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_version: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    prompt_hash: str = Field(min_length=1, max_length=128)
    git_sha: str = Field(min_length=1, max_length=64)


class ScoringRunRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    agent_version: str
    model_version: str
    prompt_hash: str
    git_sha: str
    passed: bool
    status: Literal["passed", "failed", "timeout"]
    tests_passed: int
    tests_total: int
    diff_size: int
    wall_time_seconds: float
    input_tokens: int
    output_tokens: int
    tool_call_count: int
    estimated_cost_usd: float
    started_at: datetime
    output: str
    diff: str


class RegressionStats(BaseModel):
    task_id: str | None
    baseline_runs: int
    baseline_passed: int
    baseline_pass_rate: float
    candidate_runs: int
    candidate_passed: int
    candidate_pass_rate: float
    p_value: float | None
    adjusted_p_value: float | None
    significant_regression: bool


class RegressionReport(BaseModel):
    baseline: VersionLabel
    candidate: VersionLabel
    alpha: float
    overall: RegressionStats
    per_task: list[RegressionStats]


class CompareVersionsRequest(BaseModel):
    baseline: VersionLabel
    candidate: VersionLabel
    alpha: float = Field(default=0.05, gt=0, lt=1)


class RunTrend(BaseModel):
    day: str
    task_id: str | None
    runs: int
    passed: int
    pass_rate: float
    average_latency_seconds: float
    average_cost_usd: float


class ScoringAggregate(BaseModel):
    runs: int
    passed: int
    pass_rate: float
    average_latency_seconds: float
    estimated_cost_usd: float
    input_tokens: int
    output_tokens: int
    tool_call_count: int


class TaskScoringAggregate(ScoringAggregate):
    task_id: str


class VersionScoringAggregate(ScoringAggregate):
    agent_version: str
    model_version: str
    prompt_hash: str
    git_sha: str


class ScoringReport(BaseModel):
    overall: ScoringAggregate
    by_task: list[TaskScoringAggregate]
    by_version: list[VersionScoringAggregate]


class RunOutcome(BaseModel):
    status: Literal["passed", "failed", "timeout", "error"]
    passed: bool
    latency_seconds: float = Field(ge=0)
    logs: str = ""

    @field_validator("passed")
    @classmethod
    def passed_matches_status(cls, passed: bool, info: object) -> bool:
        status = getattr(info, "data", {}).get("status")
        if status is not None and passed != (status == "passed"):
            raise ValueError("passed must be true exactly when status is 'passed'")
        return passed
