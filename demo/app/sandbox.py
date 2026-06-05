from __future__ import annotations

import io
import logging
import os
import tarfile
from typing import TYPE_CHECKING

import docker
import docker.errors

if TYPE_CHECKING:
    from app.models import Task

logger = logging.getLogger(__name__)

_SANDBOX_IMAGE = "cloudagent-sandbox:latest"
_DEFAULT_EXEC_TIMEOUT = 60  # seconds


class DockerSandbox:
    """
    Ephemeral Docker-based execution sandbox.

    Implements the Sandbox protocol defined in SPECS.md § 1.3 and § 4.
    One instance corresponds to exactly one running container.
    """

    def __init__(self, container) -> None:
        self.container = container

    def _exec_shell(self, cmd: str, **kwargs):
        """Run *cmd* via /bin/sh -c (docker-py has no shell= kwarg)."""
        return self.container.exec_run(["/bin/sh", "-c", cmd], **kwargs)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, task: "Task") -> "DockerSandbox":
        """
        Start a new sandbox container for *task*.

        Resource limits follow SPECS.md § 4.2:
          - mem_limit: 2 GB
          - cpus: 1.0
          - network_mode: bridge (read-only internet for git clone)
        """
        client = docker.from_env()
        container = client.containers.run(
            image=_SANDBOX_IMAGE,
            detach=True,
            working_dir="/workspace",
            stdout=True,
            stderr=True,
            mem_limit="2g",
            nano_cpus=int(1.0 * 1e9),  # docker-py uses nano_cpus; 1.0 CPU = 1e9
            network_mode="bridge",
            # Keep container alive with a blocking no-op process
            command="tail -f /dev/null",
        )
        logger.info("Sandbox container %s started for task %s", container.short_id, task.id)
        return cls(container)

    # ------------------------------------------------------------------
    # Sandbox protocol
    # ------------------------------------------------------------------

    def exec(self, cmd: str, timeout: int = _DEFAULT_EXEC_TIMEOUT) -> dict:
        """
        Execute *cmd* inside the container via a shell.

        stdout and stderr are combined into the ``stdout`` key of the
        returned dict because docker-py's exec_run merges streams when
        ``demux=False``.

        Returns::

            {"returncode": int, "stdout": str, "stderr": str}
        """
        try:
            exit_code, output = self._exec_shell(
                cmd,
                stdout=True,
                stderr=True,
                stdin=False,
                demux=False,
            )
            decoded = output.decode("utf-8", errors="replace") if output else ""
            return {
                "returncode": exit_code,
                "stdout": decoded,
                "stderr": "",  # combined into stdout
            }
        except docker.errors.APIError as exc:
            logger.error("exec failed: %s", exc)
            return {"returncode": 1, "stdout": "", "stderr": str(exc)}

    def read(self, path: str, line_range: tuple[int, int] | None = None) -> str:
        """
        Read a file from the container.

        *path* is treated as absolute if it starts with ``/``, otherwise
        it is interpreted relative to ``/workspace``.

        *line_range* is a 1-indexed inclusive ``(start, end)`` tuple.
        """
        full_path = path if path.startswith("/") else f"/workspace/{path}"
        exit_code, output = self.container.exec_run(
            ["cat", full_path],
            stdout=True,
            stderr=True,
            demux=False,
        )
        if exit_code != 0:
            decoded_err = output.decode("utf-8", errors="replace") if output else ""
            raise FileNotFoundError(f"Cannot read {full_path}: {decoded_err.strip()}")

        content = output.decode("utf-8", errors="replace") if output else ""

        if line_range is not None:
            start, end = line_range
            lines = content.splitlines(keepends=True)
            # 1-indexed, inclusive; clamp to available lines
            content = "".join(lines[max(0, start - 1) : end])

        return content

    def write(self, path: str, content: str) -> dict:
        """
        Write *content* to *path* inside the container.

        Uses ``tee`` so we can pipe the content via stdin without needing
        shell escaping.
        """
        full_path = path if path.startswith("/") else f"/workspace/{path}"
        dir_path = os.path.dirname(full_path) or "/"
        filename = os.path.basename(full_path)

        try:
            if dir_path != "/":
                exit_code, output = self.container.exec_run(
                    ["mkdir", "-p", dir_path],
                    demux=False,
                )
                if exit_code != 0:
                    err = output.decode("utf-8", errors="replace") if output else "mkdir failed"
                    return {"success": False, "error": err.strip()}

            data = content.encode("utf-8")
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                info = tarfile.TarInfo(name=filename)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            tar_stream.seek(0)
            self.container.put_archive(dir_path, tar_stream.read())
            return {"success": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            logger.error("write failed for %s: %s", full_path, exc)
            return {"success": False, "error": str(exc)}

    def destroy(self) -> None:
        """Stop and remove the sandbox container, ignoring errors."""
        try:
            self.container.stop(timeout=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Container stop error: %s", exc)
        try:
            self.container.remove(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Container remove error: %s", exc)
        logger.info("Sandbox container %s destroyed", self.container.short_id)
