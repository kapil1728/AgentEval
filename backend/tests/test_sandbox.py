from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from docker.client import DockerClient
from docker.errors import DockerException
from requests.exceptions import ReadTimeout

from agenteval.sandbox import SandboxRunner, SandboxTimeout, _send_socket_bytes


def make_archive(name: str, contents: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        member = tarfile.TarInfo(name)
        member.size = len(contents)
        archive.addfile(member, io.BytesIO(contents))
    return output.getvalue()


def make_client() -> tuple[Mock, Mock]:
    container = Mock()
    container.id = "sandbox-id"
    container.put_archive.return_value = True
    container.get_archive.return_value = ([make_archive("output.log", b"completed")], {})
    client = Mock()
    client.containers.create.return_value = container
    client.api.exec_create.return_value = {"Id": "exec-id"}
    client.api.exec_start.return_value = (b"completed", b"")
    client.api.exec_inspect.return_value = {"Running": False, "ExitCode": 0}
    return client, container


class WriteOnlySocket:
    def __init__(self) -> None:
        self.payload = bytearray()
        self.closed = False

    def write(self, data: memoryview) -> int:
        self.payload.extend(data)
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_socketio_archive_send_uses_underlying_socket() -> None:
    underlying = Mock()
    wrapper = Mock(spec=[])
    wrapper._sock = underlying

    _send_socket_bytes(wrapper, b"archive bytes")

    underlying.sendall.assert_called_once_with(b"archive bytes")


def test_container_uses_default_isolation_and_resource_limits() -> None:
    client, container = make_client()

    sandbox = SandboxRunner(
        image="python:3.12-slim",
        timeout_seconds=30,
        cpu_limit=1.5,
        memory_limit="512m",
        client=cast(DockerClient, client),
    )

    options = client.containers.create.call_args.kwargs
    assert options["network_disabled"] is True
    assert options["read_only"] is True
    assert options["nano_cpus"] == 1_500_000_000
    assert options["mem_limit"] == "512m"
    assert options["cap_drop"] == ["ALL"]
    assert "/workspace" in options["tmpfs"]
    assert options["tmpfs"]["/tmp"] == "rw,noexec,nosuid,size=256m,mode=1777"
    assert options["log_config"].config["max-file"] == "2"
    container.start.assert_called_once_with()
    sandbox.cleanup()


def test_copy_in_archives_repository_files(tmp_path: Path) -> None:
    client, container = make_client()
    connection = WriteOnlySocket()
    client.api.exec_start.return_value = connection
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "solution.py").write_text("answer = 42\n", encoding="utf-8")
    sandbox = SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))

    sandbox.copy_in(repository)

    exec_args = client.api.exec_create.call_args
    assert exec_args.args[0] == container.id
    assert exec_args.args[1] == ["tar", "-x", "-f", "-", "-C", "/workspace"]
    assert exec_args.kwargs["stdin"] is True
    assert exec_args.kwargs["tty"] is False
    payload = bytes(connection.payload)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        member = next(item for item in archive.getmembers() if item.isfile())
        assert member.name.endswith("solution.py")
        source = archive.extractfile(member)
        assert source is not None
        assert source.read().replace(b"\r\n", b"\n") == b"answer = 42\n"
    assert connection.closed is True
    sandbox.cleanup()


def test_exec_returns_exit_code_and_output_from_container() -> None:
    client, container = make_client()
    sandbox = SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))

    result = sandbox.exec(["echo", "ok"])

    assert result.exit_code == 0
    assert result.output == "completed"
    assert client.api.exec_create.call_args.args[0] == container.id
    assert client.api.exec_create.call_args.args[1] == ["/bin/sh", "-lc", "echo ok"]
    assert client.api.exec_start.call_args.kwargs == {
        "detach": False,
        "tty": False,
        "demux": True,
    }
    sandbox.cleanup()


def test_exec_combines_stdout_and_stderr() -> None:
    client, container = make_client()
    client.api.exec_start.return_value = (b"stdout", b"stderr")
    sandbox = SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))

    result = sandbox.exec("echo stdout; echo stderr >&2")

    assert result.output == "stdoutstderr"
    sandbox.cleanup()


def test_exec_enforces_deadline_and_cleans_container() -> None:
    client, container = make_client()

    def delayed_read_timeout(*args: object, **kwargs: object) -> None:
        time.sleep(0.05)
        raise ReadTimeout("Docker exec start timed out")

    client.api.exec_start.side_effect = delayed_read_timeout
    sandbox = SandboxRunner("python:3.12-slim", 0.05, client=cast(DockerClient, client))

    with pytest.raises(SandboxTimeout, match="hard timeout"):
        sandbox.exec("sleep 10")

    container.stop.assert_called_once_with(timeout=1)
    container.remove.assert_called_once_with(force=True)
    with pytest.raises(RuntimeError, match="cleaned up"):
        sandbox.exec("echo no longer available")


def test_docker_read_timeout_at_deadline_is_reported_as_sandbox_timeout() -> None:
    client, container = make_client()

    def delayed_read_timeout(*args: object, **kwargs: object) -> None:
        time.sleep(0.05)
        raise ReadTimeout("Docker exec start timed out")

    client.api.exec_start.side_effect = delayed_read_timeout
    sandbox = SandboxRunner("python:3.12-slim", 0.01, client=cast(DockerClient, client))

    with pytest.raises(SandboxTimeout, match="hard timeout"):
        sandbox.exec("sleep 10")

    container.remove.assert_called_once_with(force=True)


def test_exec_failure_still_removes_container() -> None:
    client, container = make_client()
    client.api.exec_create.side_effect = DockerException("exec failed")
    sandbox = SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))

    with pytest.raises(DockerException, match="exec failed"):
        sandbox.exec("false")

    container.remove.assert_called_once_with(force=True)


def test_copy_out_extracts_files_and_cleanup_is_idempotent(tmp_path: Path) -> None:
    client, container = make_client()
    client.api.exec_start.return_value = iter([(make_archive("nested/result.txt", b"done"), b"")])
    sandbox = SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))
    destination = tmp_path / "output"

    sandbox.copy_out("/workspace", destination)
    sandbox.cleanup()
    sandbox.cleanup()

    assert (destination / "nested" / "result.txt").read_bytes() == b"done"
    assert client.api.exec_create.call_args.args[1] == [
        "tar",
        "-C",
        "/workspace",
        "-cf",
        "-",
        ".",
    ]
    assert client.api.exec_start.call_args.kwargs["stream"] is True
    assert client.api.exec_start.call_args.kwargs["demux"] is True
    container.remove.assert_called_once_with(force=True)


def test_copy_in_failure_cleans_container(tmp_path: Path) -> None:
    client, container = make_client()
    sandbox = SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))

    with pytest.raises(FileNotFoundError):
        sandbox.copy_in(tmp_path / "missing-repository")

    container.remove.assert_called_once_with(force=True)


def test_start_failure_removes_created_container() -> None:
    client, container = make_client()
    container.start.side_effect = DockerException("start failed")

    with pytest.raises(DockerException, match="start failed"):
        SandboxRunner("python:3.12-slim", 30, client=cast(DockerClient, client))

    container.remove.assert_called_once_with(force=True)
