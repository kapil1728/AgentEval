from pathlib import Path

import pytest
from pydantic import ValidationError

from agenteval.schemas import Task
from agenteval.task_manifest import load_task_yaml


def valid_task_data() -> dict[str, object]:
    return {
        "id": "bugfix-example",
        "description": "Correct the boundary case.",
        "category": "bugfix",
        "repo_snapshot_path": "bugfix-example/repo_snapshot",
        "setup_commands": ["python -m pip install pytest"],
        "test_command": "python -m pytest -q",
        "timeout": 120,
        "difficulty": "easy",
    }


def test_task_accepts_valid_manifest_fields() -> None:
    task = Task.model_validate(valid_task_data())

    assert task.id == "bugfix-example"
    assert task.category == "bugfix"
    assert task.repo_snapshot_path == Path("bugfix-example/repo_snapshot")
    assert task.timeout == 120


@pytest.mark.parametrize("category", ["bug", "feature-request", "cleanup"])
def test_task_rejects_unknown_categories(category: str) -> None:
    data = valid_task_data()
    data["category"] = category

    with pytest.raises(ValidationError, match="category"):
        Task.model_validate(data)


@pytest.mark.parametrize("difficulty", ["trivial", "expert", 3])
def test_task_rejects_unknown_difficulty(difficulty: object) -> None:
    data = valid_task_data()
    data["difficulty"] = difficulty

    with pytest.raises(ValidationError, match="difficulty"):
        Task.model_validate(data)


def test_task_rejects_missing_fields_and_invalid_timeout() -> None:
    data = valid_task_data()
    del data["description"]
    data["timeout"] = 0

    with pytest.raises(ValidationError) as error:
        Task.model_validate(data)

    assert {item["loc"][0] for item in error.value.errors()} >= {"description", "timeout"}


@pytest.mark.parametrize("path", ["../outside", "safe/../../outside", r"C:\outside", r"..\outside"])
def test_task_rejects_snapshot_path_traversal(path: str) -> None:
    data = valid_task_data()
    data["repo_snapshot_path"] = path

    with pytest.raises(ValidationError, match="beneath the task root"):
        Task.model_validate(data)


def test_task_rejects_absolute_snapshot_path(tmp_path: Path) -> None:
    data = valid_task_data()
    data["repo_snapshot_path"] = str(tmp_path.resolve())

    with pytest.raises(ValidationError, match="beneath the task root"):
        Task.model_validate(data)


def test_load_task_yaml_parses_and_validates(tmp_path: Path) -> None:
    manifest = tmp_path / "task.yaml"
    manifest.write_text(
        "id: yaml-task\n"
        "description: Loaded from YAML.\n"
        "category: refactor\n"
        "repo_snapshot_path: yaml-task/repo_snapshot\n"
        "setup_commands: []\n"
        "test_command: python -m pytest -q\n"
        "timeout: 300\n"
        "difficulty: medium\n",
        encoding="utf-8",
    )

    task = load_task_yaml(manifest)

    assert task.id == "yaml-task"
    assert task.category == "refactor"
    assert task.difficulty == "medium"
