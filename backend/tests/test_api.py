from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from agenteval.api import create_app
from agenteval.database import record_scoring_run
from agenteval.runner import DockerRunner
from agenteval.schemas import RunOutcome, VersionLabel
from agenteval.scoring import ScoredRun


class FakeRunner:
    def run(self, tasks_root: Path, task: object) -> RunOutcome:
        return RunOutcome(status="passed", passed=True, latency_seconds=1.25, logs="ok")


def test_task_run_and_metrics_http_flow(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        tasks_root=tmp_path,
        runner=cast(DockerRunner, FakeRunner()),
    )
    client = TestClient(app)
    task = {
        "task_id": "sample",
        "title": "Sample",
        "workspace": "sample",
        "docker_image": "python:3.12-slim",
        "agent_command": "true",
        "test_command": "true",
    }

    response = client.post("/tasks", json=task)
    assert response.status_code == 201
    run = client.post(
        "/tasks/sample/runs",
        json={"agent_version": "agent-1", "model_version": "model-1", "prompt_version": "p1"},
    )
    assert run.status_code == 200
    assert run.json()["passed"] is True
    assert client.get("/metrics").json()["pass_rate"] == 1.0
    versions = client.get("/metrics/versions").json()
    assert versions[0]["model_version"] == "model-1"
    assert len(client.get("/runs").json()) == 1


def test_scoring_run_list_detail_compare_and_trends_api(tmp_path: Path) -> None:
    app = create_app(database_url=f"sqlite:///{tmp_path / 'scoring-api.db'}")
    session_factory = app.state.session_factory
    baseline = VersionLabel(
        agent_version="agent-v1",
        model_version="model-1",
        prompt_hash="prompt-a",
        git_sha="base-sha",
    )
    candidate = VersionLabel(
        agent_version="agent-v2",
        model_version="model-1",
        prompt_hash="prompt-a",
        git_sha="candidate-sha",
    )

    with session_factory() as session:
        for _ in range(10):
            record_scoring_run(session, "regressed-task", baseline, scored_result(True))
            record_scoring_run(session, "regressed-task", candidate, scored_result(False))
        for _ in range(2):
            record_scoring_run(session, "stable-task", baseline, scored_result(True))
            record_scoring_run(session, "stable-task", candidate, scored_result(True))

    client = TestClient(app)
    runs = client.get("/scoring/runs", params={"task_id": "regressed-task"})
    assert runs.status_code == 200
    assert len(runs.json()) == 20
    run_id = runs.json()[0]["id"]
    detail = client.get(f"/scoring/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["task_id"] == "regressed-task"
    assert detail.json()["prompt_hash"] == "prompt-a"
    assert detail.json()["diff"] == "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert client.get("/scoring/runs/99999").status_code == 404

    comparison = client.post(
        "/scoring/compare",
        json={"baseline": baseline.model_dump(), "candidate": candidate.model_dump()},
    )
    assert comparison.status_code == 200
    assert comparison.json()["overall"]["significant_regression"] is True
    rows = {row["task_id"]: row for row in comparison.json()["per_task"]}
    assert rows["regressed-task"]["significant_regression"] is True
    assert rows["stable-task"]["significant_regression"] is False

    trends = client.get("/scoring/trends", params={"days": 2, "task_id": "regressed-task"})
    assert trends.status_code == 200
    assert len(trends.json()) == 1
    assert trends.json()[0]["runs"] == 20
    assert trends.json()[0]["pass_rate"] == 0.5


def scored_result(passed: bool) -> ScoredRun:
    return ScoredRun(
        passed=passed,
        status="passed" if passed else "failed",
        tests_passed=1 if passed else 0,
        tests_total=1,
        diff_size=1,
        wall_time_seconds=2.0,
        input_tokens=10,
        output_tokens=5,
        tool_call_count=1,
        estimated_cost_usd=0.001,
        output="api test run",
        diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
    )
