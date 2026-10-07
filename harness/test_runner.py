"""Test runners for pause-condition checks."""

import subprocess
import sys
import uuid
from pathlib import Path


class DockerInfrastructureError(Exception):
    """Raised when Docker itself fails (daemon down, missing image, etc.).

    Distinct from pytest failures inside a successfully started container.
    """


class LocalTestRunner:
    """Runs pytest in a local subprocess.  Default for development and unit tests."""

    def run(self, repo: Path) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(repo / "tests")],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False, "pytest timed out"

        if result.returncode != 0:
            return False, f"pytest failed (exit {result.returncode})"
        return True, "ok"


class DockerTestRunner:
    """Runs pytest inside a Docker container with no network and no secrets.

    Fails hard if Docker is unavailable; never falls back to host pytest.
    """

    def __init__(
        self,
        image: str,
        timeout: int = 60,
        cpus: str = "1.0",
        memory: str = "512m",
        pids_limit: int = 64,
    ):
        self.image = image
        self.timeout = timeout
        self.cpus = cpus
        self.memory = memory
        self.pids_limit = pids_limit

    def _build_cmd(self, repo: Path) -> tuple[list[str], str]:
        container_name = f"swe-adapt-pytest-{uuid.uuid4().hex[:8]}"
        cmd = [
            "docker", "run",
            "--network", "none",
            "--rm",
            "--name", container_name,
            "-v", f"{repo.resolve()}:/workspace",
            "-w", "/workspace",
            "-e", "PYTHONUNBUFFERED=1",
            "--cpus", self.cpus,
            "--memory", self.memory,
            "--pids-limit", str(self.pids_limit),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            self.image,
            "python", "-m", "pytest", "tests/", "-v",
        ]
        return cmd, container_name

    def run(self, repo: Path) -> tuple[bool, str]:
        cmd, container_name = self._build_cmd(repo)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                raise DockerInfrastructureError(
                    f"Container timed out after {self.timeout}s; cleanup also failed: {exc}"
                ) from None
            raise DockerInfrastructureError(
                f"Container timed out after {self.timeout}s"
            )
        except FileNotFoundError:
            raise DockerInfrastructureError("Docker CLI not found")

        if result.returncode >= 125:
            raise DockerInfrastructureError(
                f"Docker daemon error (exit {result.returncode}): {result.stderr[:500]}"
            )

        docker_markers = [
            "Cannot connect to the Docker daemon",
            "Error response from daemon",
            "Unable to find image",
            "docker: Error",
        ]
        if any(m in result.stderr for m in docker_markers):
            raise DockerInfrastructureError(
                f"Docker infrastructure failure: {result.stderr[:500]}"
            )

        if result.returncode != 0:
            return False, f"pytest failed (exit {result.returncode})"
        return True, "ok"
