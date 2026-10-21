from __future__ import annotations

import difflib
import math
import shlex
import statistics
import tempfile
import time
import uuid
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from docker.client import DockerClient
from sqlalchemy.orm import Session, sessionmaker

from agenteval.agent_adapters import AgentAdapter
from agenteval.database import record_scoring_run
from agenteval.sandbox import SandboxRunner, SandboxTimeout
from agenteval.schemas import Task, VersionLabel

SandboxFactory = Callable[..., SandboxRunner]
_MAX_DIFF_CHARS = 100_000


@dataclass(frozen=True)
class TokenPrice:
    input_usd_per_million: float
    output_usd_per_million: float

    def __post_init__(self) -> None:
        prices = (self.input_usd_per_million, self.output_usd_per_million)
        if any(not math.isfinite(price) or price < 0 for price in prices):
            raise ValueError("token prices must be finite and nonnegative")


@dataclass(frozen=True)
class ScoredRun:
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
    output: str
    diff: str = ""
    run_id: int | None = None


@dataclass(frozen=True)
class TaskScore:
    task_id: str
    runs: tuple[ScoredRun, ...]
    pass_at_1: float
    pass_rate: float
    pass_rate_ci95: tuple[float, float]
    median_latency_seconds: float
    total_estimated_cost_usd: float


class ScoringError(RuntimeError):
    """Raised when a task result cannot be scored reliably."""


class ScoringPipeline:
    def __init__(
        self,
        tasks_root: Path,
        image: str,
        price_table: Mapping[str, TokenPrice],
        session_factory: sessionmaker[Session],
        client: DockerClient | None = None,
        sandbox_factory: SandboxFactory | None = None,
        cpu_limit: float = 2.0,
        memory_limit: str | int = "2g",
    ) -> None:
        self._tasks_root = tasks_root.resolve(strict=True)
        self._image = image
        self._price_table = dict(price_table)
        self._session_factory = session_factory
        self._client = client
        self._sandbox_factory = sandbox_factory or SandboxRunner
        self._cpu_limit = cpu_limit
        self._memory_limit = memory_limit

    def score(
        self,
        task: Task,
        adapter: AgentAdapter,
        instructions: str,
        version: VersionLabel,
        repeats: int = 1,
    ) -> TaskScore:
        if repeats < 1:
            raise ValueError("repeats must be at least one")
        try:
            price = self._price_table[version.model_version]
        except KeyError as error:
            raise ValueError(
                f"no token price configured for model {version.model_version!r}"
            ) from error
        workspace = self._resolve_workspace(task.repo_snapshot_path)
        results: list[ScoredRun] = []
        for _ in range(repeats):
            result = self._run_once(task, workspace, adapter, instructions, price)
            with self._session_factory() as session:
                record = record_scoring_run(session, task.id, version, result)
            results.append(replace(result, run_id=record.id))
        runs = tuple(results)
        passed_count = sum(run.passed for run in runs)
        total = len(runs)
        lower, upper = _wilson_interval(passed_count, total)
        return TaskScore(
            task_id=task.id,
            runs=runs,
            pass_at_1=1.0 if runs[0].passed else 0.0,
            pass_rate=passed_count / total,
            pass_rate_ci95=(lower, upper),
            median_latency_seconds=statistics.median(run.wall_time_seconds for run in runs),
            total_estimated_cost_usd=sum(run.estimated_cost_usd for run in runs),
        )

    def _resolve_workspace(self, relative_path: Path) -> Path:
        workspace = (self._tasks_root / relative_path).resolve(strict=True)
        if not workspace.is_relative_to(self._tasks_root) or not workspace.is_dir():
            raise ValueError("task repository snapshot must be beneath the task root")
        return workspace

    def _run_once(
        self,
        task: Task,
        workspace: Path,
        adapter: AgentAdapter,
        instructions: str,
        price: TokenPrice,
    ) -> ScoredRun:
        started = time.monotonic()
        input_tokens = 0
        output_tokens = 0
        tool_call_count = 0
        log_sections: list[str] = []
        tests_passed = 0
        tests_total = 0
        diff_size = 0
        diff = ""
        status: Literal["passed", "failed", "timeout"] = "failed"
        junit_path = f"/workspace/agenteval-junit-{uuid.uuid4().hex}.xml"
        test_command = _with_junit_xml(task.test_command, junit_path)

        try:
            with self._sandbox_factory(
                image=self._image,
                timeout_seconds=task.timeout,
                cpu_limit=self._cpu_limit,
                memory_limit=self._memory_limit,
                network_disabled=True,
                client=self._client,
            ) as sandbox:
                sandbox.copy_in(workspace)
                for setup_command in task.setup_commands:
                    setup_result = sandbox.exec(setup_command)
                    log_sections.append(f"$ {setup_command}\n{setup_result.output}")
                    if setup_result.exit_code != 0:
                        raise ScoringError(f"task setup failed: {setup_result.output}")

                with tempfile.TemporaryDirectory(prefix="agenteval-baseline-") as baseline:
                    baseline_path = Path(baseline)
                    sandbox.copy_out("/workspace", baseline_path)
                    agent_result = adapter.run_in_sandbox(sandbox, workspace, instructions)
                    input_tokens = agent_result.input_tokens
                    output_tokens = agent_result.output_tokens
                    tool_call_count = agent_result.tool_call_count
                    log_sections.append(f"[agent]\n{agent_result.output}")

                    with tempfile.TemporaryDirectory(
                        prefix="agenteval-result-"
                    ) as output_directory:
                        output_path = Path(output_directory)
                        sandbox.copy_out("/workspace", output_path)
                        diff_size = _diff_size(baseline_path, output_path)
                        diff = _diff_text(baseline_path, output_path)

                test_result = sandbox.exec(test_command)
                log_sections.append(f"$ {test_command}\n{test_result.output}")
                tests_passed, tests_total = _parse_junit_from_sandbox(sandbox, junit_path)

                status = (
                    "passed"
                    if agent_result.exit_code == 0
                    and test_result.exit_code == 0
                    and tests_total > 0
                    and tests_passed == tests_total
                    else "failed"
                )
        except SandboxTimeout as error:
            status = "timeout"
            log_sections.append(str(error))
        except ScoringError as error:
            status = "failed"
            log_sections.append(str(error))

        elapsed = time.monotonic() - started
        estimated_cost = (
            input_tokens * price.input_usd_per_million
            + output_tokens * price.output_usd_per_million
        ) / 1_000_000
        return ScoredRun(
            passed=status == "passed",
            status=status,
            tests_passed=tests_passed,
            tests_total=tests_total,
            diff_size=diff_size,
            wall_time_seconds=elapsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=tool_call_count,
            estimated_cost_usd=estimated_cost,
            output="\n\n".join(log_sections)[-100_000:],
            diff=diff,
        )


def _with_junit_xml(test_command: str, junit_path: str) -> str:
    quoted_path = shlex.quote(junit_path)
    if "{junit_xml}" in test_command:
        return test_command.replace("{junit_xml}", quoted_path)
    try:
        parts = shlex.split(test_command)
    except ValueError as error:
        raise ValueError("test_command must be a parseable pytest command") from error
    is_pytest = bool(parts) and (
        parts[0] in {"pytest", "py.test"}
        or (len(parts) >= 3 and parts[0].startswith("python") and parts[1:3] == ["-m", "pytest"])
    )
    if not is_pytest:
        raise ValueError("test_command must invoke pytest or include a {junit_xml} placeholder")
    if "--junitxml" in parts or "--junit-xml" in parts:
        raise ValueError("test_command must not configure its own JUnit output path")
    return f"{test_command} --junitxml={quoted_path}"


def _parse_junit_from_sandbox(sandbox: SandboxRunner, junit_path: str) -> tuple[int, int]:
    with tempfile.TemporaryDirectory(prefix="agenteval-junit-") as directory:
        output_path = Path(directory)
        sandbox.copy_out("/workspace", output_path)
        xml_path = output_path / Path(junit_path).name
        try:
            root = ElementTree.parse(xml_path).getroot()
        except (ElementTree.ParseError, OSError) as error:
            raise ScoringError("pytest did not produce a readable JUnit XML report") from error

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
    failures = sum(
        int(suite.attrib.get("failures", "0")) + int(suite.attrib.get("errors", "0"))
        for suite in suites
    )
    skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    return max(tests - failures - skipped, 0), tests


def _diff_size(original: Path, modified: Path) -> int:
    original_files = _file_contents(original)
    modified_files = _file_contents(modified)
    changed_lines = 0
    for path in original_files.keys() | modified_files.keys():
        before = original_files.get(path, b"")
        after = modified_files.get(path, b"")
        if before == after:
            continue
        try:
            before_lines = before.decode("utf-8").splitlines()
            after_lines = after.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            changed_lines += 1
            continue
        for operation, before_start, before_end, after_start, after_end in difflib.SequenceMatcher(
            a=before_lines, b=after_lines, autojunk=False
        ).get_opcodes():
            if operation in {"replace", "delete"}:
                changed_lines += before_end - before_start
            if operation in {"replace", "insert"}:
                changed_lines += after_end - after_start
    return changed_lines


def _diff_text(original: Path, modified: Path) -> str:
    original_files = _file_contents(original)
    modified_files = _file_contents(modified)
    diff_lines: list[str] = []
    for path in sorted(original_files.keys() | modified_files.keys()):
        before = original_files.get(path, b"")
        after = modified_files.get(path, b"")
        if before == after:
            continue
        try:
            before_lines = before.decode("utf-8").splitlines()
            after_lines = after.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            diff_lines.append(f"Binary file {path} changed")
            continue
        diff_lines.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{path}" if path in original_files else "/dev/null",
                tofile=f"b/{path}" if path in modified_files else "/dev/null",
                lineterm="",
            )
        )
    patch = "\n".join(diff_lines)
    return (patch + "\n" if patch else "")[:_MAX_DIFF_CHARS]


def _file_contents(root: Path) -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__"} for part in relative.parts):
            continue
        files[relative] = path.read_bytes()
    return files


def _wilson_interval(
    successes: int, total: int, z_score: float = 1.959963984540054
) -> tuple[float, float]:
    proportion = successes / total
    z_squared = z_score**2
    denominator = 1 + z_squared / total
    center = (proportion + z_squared / (2 * total)) / denominator
    margin = (
        z_score
        * math.sqrt(proportion * (1 - proportion) / total + z_squared / (4 * total**2))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)
