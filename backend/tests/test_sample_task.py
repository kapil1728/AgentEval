from pathlib import Path

from agenteval.task_manifest import load_task_yaml


def test_five_sample_manifests_and_snapshots_are_valid() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    tasks_root = repository_root / "tasks"
    manifests = sorted(
        manifest
        for manifest in tasks_root.glob("*/task.yaml")
        if manifest.parent.name != "ci-smoke"
    )

    assert len(manifests) == 5
    for manifest in manifests:
        task = load_task_yaml(manifest)
        snapshot = (tasks_root / task.repo_snapshot_path).resolve()
        assert task.id == manifest.parent.name
        assert snapshot.is_relative_to(tasks_root.resolve())
        assert snapshot.is_dir()
        assert list(snapshot.glob("test_*.py"))

    ci_task = load_task_yaml(tasks_root / "ci-smoke" / "task.yaml")
    assert ci_task.id == "ci-mock-smoke"
    assert ci_task.repo_snapshot_path == Path("ci-smoke/repo_snapshot")
