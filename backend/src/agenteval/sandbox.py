from __future__ import annotations

import io
import math
import shlex
import tarfile
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any

import docker
from docker.client import DockerClient
from docker.errors import DockerException
from docker.models.containers import Container
from requests.exceptions import Timeout as DockerRequestTimeout


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    output: str


class SandboxTimeout(TimeoutError):
    """Raised when a sandbox command exceeds its hard deadline."""


class SandboxRunner:
    def __init__(
        self,
        image: str,
        timeout_seconds: float,
        cpu_limit: float = 2.0,
        memory_limit: str | int = "2g",
        network_disabled: bool = True,
        client: DockerClient | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not math.isfinite(cpu_limit) or cpu_limit <= 0:
            raise ValueError("cpu_limit must be a positive finite number")
        if not memory_limit:
            raise ValueError("memory_limit must be set")

        self._deadline = time.monotonic() + timeout_seconds
        self._client = client or docker.from_env(timeout=timeout_seconds)
        self._container: Container | None = None
        self._closed = False
        try:
            self._set_request_timeout(self._deadline)
            self._container = self._client.containers.create(
                image=image,
                command=["while :; do sleep 3600; done"],
                entrypoint=["/bin/sh", "-lc"],
                detach=True,
                network_disabled=network_disabled,
                read_only=True,
                nano_cpus=round(cpu_limit * 1_000_000_000),
                mem_limit=memory_limit,
                pids_limit=256,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                tmpfs={
                    "/workspace": "rw,noexec,nosuid,size=1g,uid=1000,gid=1000,mode=755",
                    "/tmp": "rw,noexec,nosuid,size=256m,mode=1777",
                },
                user="1000:1000",
                log_config=docker.types.LogConfig(
                    type="local", config={"max-size": "10m", "max-file": "2"}
                ),
            )
            self._set_request_timeout(self._deadline)
            self._container.start()
        except BaseException as error:
            self._cleanup_operation_error(error, self._deadline)
            raise

    def __enter__(self) -> SandboxRunner:
        self._ensure_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.cleanup()

    def exec(
        self,
        command: str | Sequence[str],
        timeout_seconds: float | None = None,
    ) -> ExecResult:
        container = self._require_container()
        deadline = self._deadline
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                error = ValueError("timeout_seconds must be positive")
                self._cleanup_after_error(error)
                raise error
            deadline = min(deadline, time.monotonic() + timeout_seconds)

        command_text = command if isinstance(command, str) else shlex.join(command)
        try:
            self._ensure_time_remaining(deadline)
            self._set_request_timeout(deadline)
            exec_info = self._client.api.exec_create(
                container.id,
                ["/bin/sh", "-lc", command_text],
                user="1000:1000",
                workdir="/workspace",
                privileged=False,
            )
            exec_id = exec_info["Id"]
            self._set_request_timeout(deadline)
            output = self._client.api.exec_start(
                exec_id,
                detach=False,
                tty=False,
                demux=True,
            )
            self._ensure_time_remaining(deadline)
            self._set_request_timeout(deadline)
            inspection = self._client.api.exec_inspect(exec_id)
            stdout, stderr = output if isinstance(output, tuple) else (output, None)
            combined_output = (stdout or b"") + (stderr or b"")
            return ExecResult(
                exit_code=inspection["ExitCode"],
                output=combined_output.decode("utf-8", errors="replace"),
            )
        except SandboxTimeout as error:
            self._cleanup_after_error(error)
            raise
        except BaseException as error:
            self._cleanup_operation_error(error, deadline)
            raise

    def copy_in(self, source: Path, destination: str = "/workspace") -> None:
        container = self._require_container()
        try:
            source = source.resolve(strict=True)
            remote_directory = _validate_container_path(destination)
            archive = io.BytesIO()

            def normalize_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
                if not (member.isfile() or member.isdir()):
                    raise ValueError(f"unsupported repository file type: {member.name}")
                member.uid = 1000
                member.gid = 1000
                member.uname = ""
                member.gname = ""
                if member.isdir():
                    member.mode = 0o755
                elif member.isfile():
                    member.mode = (member.mode & 0o111) | 0o644
                return member

            with tarfile.open(fileobj=archive, mode="w") as tar:
                if source.is_dir():
                    tar.add(source, arcname=".", recursive=True, filter=normalize_member)
                elif source.is_file():
                    tar.add(source, arcname=source.name, recursive=False, filter=normalize_member)
                else:
                    raise ValueError("source must be a regular file or directory")
            self._ensure_time_remaining(self._deadline)
            self._set_request_timeout(self._deadline)
            exec_info = self._client.api.exec_create(
                container.id,
                ["tar", "-x", "-f", "-", "-C", remote_directory],
                stdin=True,
                stdout=False,
                stderr=False,
                tty=False,
                privileged=False,
                user="1000:1000",
            )
            exec_id = exec_info["Id"]
            self._set_request_timeout(self._deadline)
            connection = self._client.api.exec_start(
                exec_id,
                detach=False,
                tty=False,
                socket=True,
            )
            try:
                _send_socket_bytes(connection, archive.getvalue())
            finally:
                connection.close()

            while True:
                self._set_request_timeout(self._deadline)
                inspection = self._client.api.exec_inspect(exec_id)
                if not inspection["Running"]:
                    if inspection["ExitCode"] != 0:
                        raise RuntimeError(
                            f"container could not extract archive into {remote_directory}"
                        )
                    break
                time.sleep(min(0.05, self._remaining(self._deadline)))
            self._ensure_time_remaining(self._deadline)
        except BaseException as error:
            self._cleanup_operation_error(error, self._deadline)
            raise

    def copy_out(self, source: str, destination: Path) -> None:
        container = self._require_container()
        try:
            source = _validate_container_path(source)
            destination = destination.resolve()
            self._ensure_time_remaining(self._deadline)
            self._set_request_timeout(self._deadline)
            exec_info = self._client.api.exec_create(
                container.id,
                ["tar", "-C", source, "-cf", "-", "."],
                stdout=True,
                stderr=True,
                tty=False,
                privileged=False,
                user="1000:1000",
                workdir=source,
            )
            exec_id = exec_info["Id"]
            self._set_request_timeout(self._deadline)
            output_stream = self._client.api.exec_start(
                exec_id,
                detach=False,
                tty=False,
                stream=True,
                demux=True,
            )
            with tempfile.TemporaryFile() as archive_file:
                errors = bytearray()
                for output in output_stream:
                    self._ensure_time_remaining(self._deadline)
                    stdout, stderr = output if isinstance(output, tuple) else (output, None)
                    if stdout:
                        archive_file.write(stdout)
                    if stderr:
                        errors.extend(stderr[: max(8192 - len(errors), 0)])
                self._ensure_time_remaining(self._deadline)
                self._set_request_timeout(self._deadline)
                inspection = self._client.api.exec_inspect(exec_id)
                if inspection["ExitCode"] != 0:
                    message = errors.decode("utf-8", errors="replace")
                    raise RuntimeError(f"container could not archive {source}: {message}")

                archive_file.seek(0)
                destination.mkdir(parents=True, exist_ok=True)
                root = destination.resolve(strict=True)
                with tarfile.open(fileobj=archive_file, mode="r|*") as tar:
                    for member in tar:
                        _extract_member(tar, member, root)
            self._ensure_time_remaining(self._deadline)
        except BaseException as error:
            self._cleanup_after_error(error)
            raise

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        container, self._container = self._container, None
        if container is None:
            return
        try:
            self._client.api.timeout = 5
            container.stop(timeout=1)
        except DockerException:
            pass
        finally:
            container.remove(force=True)

    def _require_container(self) -> Container:
        self._ensure_open()
        if self._container is None:
            raise RuntimeError("sandbox container is not available")
        return self._container

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("sandbox has already been cleaned up")

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SandboxTimeout("sandbox execution exceeded its hard timeout")
        return remaining

    def _ensure_time_remaining(self, deadline: float) -> None:
        self._remaining(deadline)

    def _set_request_timeout(self, deadline: float) -> None:
        self._client.api.timeout = max(0.001, self._remaining(deadline))

    def _cleanup_after_error(self, error: BaseException) -> None:
        try:
            self.cleanup()
        except BaseException as cleanup_error:
            error.add_note(f"sandbox cleanup also failed: {cleanup_error}")

    def _cleanup_operation_error(self, error: BaseException, deadline: float) -> None:
        if isinstance(error, DockerRequestTimeout) and time.monotonic() >= deadline:
            timeout_error = SandboxTimeout("sandbox execution exceeded its hard timeout")
            self._cleanup_after_error(timeout_error)
            raise timeout_error from error
        self._cleanup_after_error(error)


def _validate_container_path(path: str) -> str:
    candidate = PurePosixPath(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("container paths must be absolute and cannot traverse upward")
    return str(candidate)


def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, root: Path) -> None:
    relative = PurePosixPath(member.name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe path in container archive: {member.name}")
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"unsafe path in container archive: {member.name}")
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return
    if not member.isfile():
        raise ValueError(f"unsupported container archive entry: {member.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fileobj = tar.extractfile(member)
    if fileobj is None:
        raise ValueError(f"could not read container archive entry: {member.name}")
    with fileobj, target.open("wb") as output:
        _copy_stream(fileobj, output)


def _copy_stream(source: IO[bytes], destination: IO[bytes]) -> None:
    while chunk := source.read(1024 * 1024):
        destination.write(chunk)


def _send_socket_bytes(connection: Any, payload: bytes) -> None:
    sendall = getattr(connection, "sendall", None)
    if sendall is not None:
        sendall(payload)
        return

    underlying_socket = getattr(connection, "_sock", None)
    underlying_sendall = getattr(underlying_socket, "sendall", None)
    if underlying_sendall is not None:
        underlying_sendall(payload)
        return

    view = memoryview(payload)
    while view:
        written = connection.write(view)
        if written is None or written <= 0:
            raise OSError("Docker exec socket stopped accepting archive data")
        view = view[written:]
