#!/usr/bin/env python3
"""Task 01 dry-run CLI: scripted fake responses through Adapter + Orchestrator.

Dry-run only.  No --live flag, no API key, no HTTP calls.

Before any agent step, verifies Docker is reachable and the tester image
exists locally (docker image inspect).  It never attempts an image pull;
a missing image is a hard preflight failure.  Pause checks use
DockerTestRunner and final acceptance uses DockerAcceptanceRunner; both
fail hard on Docker infrastructure errors (never host fallback).

The task prompt is read from tasks/task_01_extract_and_type/INSTRUCTIONS.md.
Uses the same fake response sequence as tests/test_end_to_end.py.

Exit codes:
    0  success (event fired, run completed, acceptance passed)
    1  acceptance failed
    3  change event never fired
    4  adapter reached its turn limit
    5  Docker preflight/infrastructure failure
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.adapter import Adapter
from harness.orchestrator import Orchestrator
from harness.test_runner import (
    DockerAcceptanceRunner,
    DockerInfrastructureError,
    DockerTestRunner,
)
from scripts.generate_report import generate

TASK_DIR = _REPO_ROOT / "tasks" / "task_01_extract_and_type"
DEFAULT_IMAGE = "swe-adapt-tester"

EXIT_ACCEPTANCE_FAILED = 1
EXIT_EVENT_NEVER_FIRED = 3
EXIT_TURN_LIMIT = 4
EXIT_DOCKER_FAILURE = 5

SYSTEM_PROMPT = "You are a helpful assistant."


class FakeResponse:
    """Minimal response object mirroring tests/test_end_to_end.py."""

    def __init__(self, tool_uses=None, text=None):
        self.tool_uses = tool_uses or []
        self.text = text


class FakeClient:
    """Scripted client: cycles through a fixed response sequence."""

    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def send(self, system_prompt, messages):
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


def dry_run_responses():
    """Same fake response sequence as the passing end-to-end test."""
    return [
        FakeResponse(
            tool_uses=[
                {
                    "id": "tu_01",
                    "name": "write_file",
                    "input": {
                        "path": "validators.py",
                        "content": (
                            "import re\n\n"
                            "def validate_email(address):\n"
                            "    return bool(re.match(r'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$', address))\n"
                        ),
                    },
                },
                {
                    "id": "tu_02",
                    "name": "write_file",
                    "input": {
                        "path": "email_service.py",
                        "content": (
                            "from validators import validate_email\n\n"
                            "def send_email(address):\n"
                            '    if not validate_email(address):\n'
                            '        raise ValueError("Invalid email")\n'
                            '    return f"Sent to {address}"\n'
                        ),
                    },
                },
                {
                    "id": "tu_03",
                    "name": "write_file",
                    "input": {
                        "path": "user_service.py",
                        "content": (
                            "from validators import validate_email\n\n"
                            "def create_user(email):\n"
                            '    if not validate_email(email):\n'
                            '        raise ValueError("Invalid email")\n'
                            '    return {"email": email, "created": True}\n'
                        ),
                    },
                },
            ]
        ),
        FakeResponse(
            tool_uses=[
                {
                    "id": "tu_04",
                    "name": "write_file",
                    "input": {
                        "path": "validators.py",
                        "content": (
                            "import re\n\n"
                            "def validate_email(address: str) -> bool:\n"
                            "    return bool(re.match(r'^[\\w.+-]+@[\\w.-]+\\.\\w+$', address))\n"
                        ),
                    },
                },
            ]
        ),
        FakeResponse(text="Done."),
    ]


def _load_task_prompt() -> str:
    return (TASK_DIR / "INSTRUCTIONS.md").read_text().strip()


def _docker_preflight(image: str) -> None:
    """Verify Docker is reachable and image exists locally. Never pulls.

    Raises DockerInfrastructureError on any failure.
    """
    try:
        info = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise DockerInfrastructureError("Docker CLI not found")
    except subprocess.TimeoutExpired:
        raise DockerInfrastructureError("docker info timed out")
    if info.returncode != 0:
        raise DockerInfrastructureError(
            f"Docker daemon unreachable: {info.stderr[:500]}"
        )

    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise DockerInfrastructureError("Docker CLI not found")
    except subprocess.TimeoutExpired:
        raise DockerInfrastructureError("docker image inspect timed out")
    if inspect.returncode != 0:
        raise DockerInfrastructureError(
            f"tester image {image!r} not found locally; refusing to pull"
        )


def _copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def run(artifacts_dir, image, max_turns, timeout, acceptance_timeout) -> int:
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    try:
        _docker_preflight(image)
    except DockerInfrastructureError as exc:
        print(f"docker preflight failed: {exc}", file=sys.stderr)
        generate(artifacts_dir, None, mode="dry-run", status="incomplete_error")
        return EXIT_DOCKER_FAILURE

    pause_runner = DockerTestRunner(image=image, timeout=timeout)
    acceptance_runner = DockerAcceptanceRunner(image=image, timeout=acceptance_timeout)

    orch = Orchestrator(
        TASK_DIR / "repo",
        TASK_DIR / "CHANGE_EVENT.md",
        trace_path=artifacts_dir / "trace.jsonl",
        test_runner=pause_runner,
        live_mode=True,
    )
    temp_root = orch.workspace.parent

    try:
        try:
            result = Adapter(
                orch, FakeClient(dry_run_responses()), max_turns=max_turns
            ).run(system_prompt=SYSTEM_PROMPT, task_prompt=_load_task_prompt())
        except DockerInfrastructureError as exc:
            print(f"docker infrastructure failure during run: {exc}", file=sys.stderr)
            status, exit_code, rc = "incomplete_error", None, EXIT_DOCKER_FAILURE
        else:
            if result.turn_limit_reached:
                print("adapter reached its turn limit", file=sys.stderr)
                status, exit_code, rc = "incomplete_turn_limit", None, EXIT_TURN_LIMIT
            elif not orch.pause_injected:
                print("change event never fired", file=sys.stderr)
                status, exit_code, rc = "incomplete_error", None, EXIT_EVENT_NEVER_FIRED
            else:
                try:
                    ok, reason = acceptance_runner.run(
                        orch.workspace, TASK_DIR / "tests_acceptance"
                    )
                except DockerInfrastructureError as exc:
                    print(
                        f"docker infrastructure failure during acceptance: {exc}",
                        file=sys.stderr,
                    )
                    status, exit_code, rc = "incomplete_error", None, EXIT_DOCKER_FAILURE
                else:
                    if ok:
                        status, exit_code, rc = "completed", 0, 0
                    else:
                        print(f"acceptance failed: {reason}", file=sys.stderr)
                        status, exit_code, rc = "completed", 1, EXIT_ACCEPTANCE_FAILED

        snapshot = temp_root / "snapshots" / "pause"
        if snapshot.exists():
            _copy_dir(snapshot, artifacts_dir / "pause-snapshot")
        _copy_dir(orch.workspace, artifacts_dir / "final-workspace")

        generate(artifacts_dir, exit_code, mode="dry-run", status=status)
        return rc
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("dry-run-artifacts"))
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument(
        "--timeout", type=int, default=60, help="pause-check container timeout (s)"
    )
    parser.add_argument(
        "--acceptance-timeout", type=int, default=120,
        help="acceptance container timeout (s)",
    )
    args = parser.parse_args(argv)
    return run(
        args.artifacts,
        args.image,
        args.max_turns,
        args.timeout,
        args.acceptance_timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
