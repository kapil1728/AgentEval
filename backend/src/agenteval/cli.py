from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.orm import Session, sessionmaker

from agenteval.agent_adapters import AgentAdapter, CommandAdapter, MockAdapter, MockBehavior
from agenteval.database import (
    create_session_factory,
    list_version_labels,
    upsert_task,
)
from agenteval.metrics import scoring_report, summarize_runs
from agenteval.regression import compare_scoring_versions
from agenteval.schemas import AgentConfig, Task, TaskSpec, VersionLabel
from agenteval.scoring import ScoringPipeline, TaskScore, TokenPrice
from agenteval.task_manifest import load_agent_config_yaml, load_task_yaml

app = typer.Typer(help="Run and compare coding-agent evaluations.")


def _session_factory() -> sessionmaker[Session]:
    url = os.getenv("AGENTEVAL_DATABASE_URL", "sqlite:///./agenteval.db")
    return create_session_factory(url)


@app.command()
def register(manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    task = TaskSpec.model_validate(json.loads(manifest.read_text(encoding="utf-8")))
    with _session_factory()() as session:
        upsert_task(session, task)
    typer.echo(f"Registered task {task.task_id}")


@app.command()
def run(
    agent: Annotated[Path, typer.Option("--agent", exists=True, dir_okay=False)],
    tasks: Annotated[Path, typer.Option("--tasks", exists=True, file_okay=False)],
    repeats: Annotated[int, typer.Option("--repeats", min=1)],
    concurrency: Annotated[int, typer.Option("--concurrency", min=1)] = 1,
    task_ids: Annotated[list[str] | None, typer.Option("--task-id")] = None,
) -> None:
    config = _load_agent_config(agent)
    task_list = _load_tasks(tasks)
    if task_ids:
        available_ids = {task.id for task in task_list}
        unknown_ids = sorted(set(task_ids) - available_ids)
        if unknown_ids:
            raise typer.BadParameter(f"Unknown task ID(s): {', '.join(unknown_ids)}")
        selected_ids = set(task_ids)
        task_list = [task for task in task_list if task.id in selected_ids]
    if not task_list:
        raise typer.BadParameter(f"No task.yaml manifests found under {tasks}")
    if config.adapter == "mock":
        adapter: AgentAdapter = MockAdapter(MockBehavior(config.mock_behavior))
    else:
        if config.command is None or "{instructions}" not in config.command:
            raise typer.BadParameter("Agent command must include an {instructions} placeholder")
        adapter = CommandAdapter(
            command=config.command,
            image=config.image,
            cpu_limit=config.cpu_limit,
            memory_limit=config.memory_limit,
        )

    pipeline = ScoringPipeline(
        tasks_root=tasks,
        image=config.image,
        price_table={
            config.model_version: TokenPrice(
                config.input_usd_per_million,
                config.output_usd_per_million,
            )
        },
        session_factory=_session_factory(),
        cpu_limit=config.cpu_limit,
        memory_limit=config.memory_limit,
    )
    scores: list[TaskScore] = []
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="agenteval") as executor:
        futures = {
            executor.submit(
                pipeline.score,
                task,
                adapter,
                task.description,
                _version_label(config),
                repeats,
            ): task
            for task in task_list
        }
        for future in as_completed(futures):
            scores.append(future.result())

    for score in sorted(scores, key=lambda result: result.task_id):
        typer.echo(
            json.dumps(
                {
                    "task_id": score.task_id,
                    "run_ids": [run.run_id for run in score.runs],
                    "pass_at_1": score.pass_at_1,
                    "pass_rate": score.pass_rate,
                    "pass_rate_ci95": score.pass_rate_ci95,
                    "median_latency_seconds": score.median_latency_seconds,
                    "total_estimated_cost_usd": score.total_estimated_cost_usd,
                }
            )
        )


@app.command()
def compare(
    version_a: str,
    version_b: str,
    alpha: float = typer.Option(0.05, min=0.000001, max=0.999999),
) -> None:
    with _session_factory()() as session:
        baseline = _resolve_version(session, version_a)
        candidate = _resolve_version(session, version_b)
        report = compare_scoring_versions(session, baseline, candidate, alpha=alpha)
    typer.echo(report.model_dump_json(indent=2))
    if report.overall.significant_regression or any(
        row.significant_regression for row in report.per_task
    ):
        raise typer.Exit(code=1)


@app.command()
def metrics() -> None:
    with _session_factory()() as session:
        summary = summarize_runs(session)
    typer.echo(summary.model_dump_json(indent=2))


@app.command()
def report() -> None:
    with _session_factory()() as session:
        summary = scoring_report(session)
    typer.echo(summary.model_dump_json(indent=2))


def _load_agent_config(path: Path) -> AgentConfig:
    try:
        return load_agent_config_yaml(path)
    except Exception as error:
        raise typer.BadParameter(f"Invalid agent config: {error}") from error


def _load_tasks(tasks_root: Path) -> list[Task]:
    root = tasks_root.resolve(strict=True)
    manifests = sorted(root.rglob("task.yaml"))
    try:
        tasks = [load_task_yaml(manifest) for manifest in manifests]
    except Exception as error:
        raise typer.BadParameter(f"Invalid task manifest: {error}") from error
    task_ids = [task.id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise typer.BadParameter("Task IDs must be unique within the selected task directory")
    return tasks


def _version_label(config: AgentConfig) -> VersionLabel:
    return VersionLabel(
        agent_version=config.agent_version,
        model_version=config.model_version,
        prompt_hash=config.prompt_hash,
        git_sha=config.git_sha,
    )


def _resolve_version(session: Session, name: str) -> VersionLabel:
    versions = list_version_labels(session, name)
    if not versions:
        raise typer.BadParameter(f"No scoring runs found for agent version {name!r}")
    if len(versions) != 1:
        identities = ", ".join(
            f"{item.model_version}/{item.prompt_hash}/{item.git_sha}" for item in versions
        )
        raise typer.BadParameter(f"Agent version {name!r} is ambiguous: {identities}")
    return versions[0]


if __name__ == "__main__":
    app()
