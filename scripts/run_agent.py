#!/usr/bin/env python3
"""Task 01 CLI: scripted fake responses (default) or live agent (--live).

Dry-run is the default and is unchanged: scripted fake responses through
Adapter + Orchestrator, Docker pause checks, Docker final acceptance.

--live uses AnthropicClient with a caller-supplied --model, reads the key
only from ANTHROPIC_API_KEY (never a CLI argument), and never falls back
to fake responses or host pytest.  Before any agent step, verifies Docker
is reachable and the tester image exists locally (docker image inspect);
it never attempts an image pull.

The task prompt is read from tasks/task_01_extract_and_type/INSTRUCTIONS.md.

Exit codes:
    0  success (event fired, run completed, acceptance passed)
    1  acceptance failed
    2  usage error (e.g. --live without --model, invalid --max-tokens)
    3  change event never fired
    4  adapter reached its turn limit
    5  Docker preflight/infrastructure failure
    6  live configuration or API failure
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness.adapter import Adapter
from harness.anthropic_client import AnthropicApiError, AnthropicClient
from harness.orchestrator import Orchestrator
from harness.test_runner import (
    DockerAcceptanceRunner,
    DockerInfrastructureError,
    DockerTestRunner,
    _docker_env,
)
from scripts.generate_report import generate

TASK_DIR = _REPO_ROOT / "tasks" / "task_01_extract_and_type"
DEFAULT_IMAGE = "swe-adapt-tester"

EXIT_ACCEPTANCE_FAILED = 1
EXIT_EVENT_NEVER_FIRED = 3
EXIT_TURN_LIMIT = 4
EXIT_DOCKER_FAILURE = 5
EXIT_API_FAILURE = 6

SYSTEM_PROMPT = "You are a helpful assistant."


class LiveConfigError(Exception):
    """Live mode misconfiguration (e.g. missing API key or model)."""


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


def build_client(live: bool, model, max_tokens: int):
    """Select the agent client.  Only the live branch reads the API key."""
    if not live:
        return FakeClient(dry_run_responses())

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise LiveConfigError("ANTHROPIC_API_KEY is not set")
    if not model:
        raise LiveConfigError("--model is required for live mode")
    return AnthropicClient(api_key=api_key, model=model, max_tokens=max_tokens)


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
            env=_docker_env(),
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
            env=_docker_env(),
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


def _positive_int(value):
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid positive integer: {value!r}")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return ivalue


def run(artifacts_dir, image, max_turns, timeout, acceptance_timeout,
        live=False, model=None, max_tokens=4096) -> int:
    mode = "live" if live else "dry-run"
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    try:
        _docker_preflight(image)
    except DockerInfrastructureError as exc:
        print(f"docker preflight failed: {exc}", file=sys.stderr)
       generate(
    artifacts_dir, None, mode=mode, status="incomplete_error",
    starter_dir=TASK_DIR / "repo",
)

        return EXIT_DOCKER_FAILURE

    try:
        client = build_client(live=live, model=model, max_tokens=max_tokens)
    except LiveConfigError as exc:
        print(f"live configuration error: {exc}", file=sys.stderr)
        generate(artifacts_dir, None, mode=mode, status="incomplete_error", starter_dir=TASK_DIR / "repo")

        return EXIT_API_FAILURE

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
                orch, client, max_turns=max_turns
            ).run(system_prompt=SYSTEM_PROMPT, task_prompt=_load_task_prompt())
        except DockerInfrastructureError as exc:
            print(f"docker infrastructure failure during run: {exc}", file=sys.stderr)
            status, exit_code, rc = "incomplete_error", None, EXIT_DOCKER_FAILURE
        except (AnthropicApiError, LiveConfigError) as exc:
            print(f"api failure during run: {exc}", file=sys.stderr)
            status, exit_code, rc = "incomplete_error", None, EXIT_API_FAILURE
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

       generate(artifacts_dir, exit_code, mode=mode, status=status, starter_dir=TASK_DIR / "repo")

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
    parser.add_argument(
        "--live", action="store_true",
        help="run a live agent via AnthropicClient (default: scripted dry-run)",
    )
    parser.add_argument(
        "--model", default=None,
        help="model name for --live (required with --live)",
    )
    parser.add_argument(
        "--max-tokens", type=_positive_int, default=4096,
        help="per-request output token cap for --live (default: 4096)",
    )
    args = parser.parse_args(argv)

    if args.live and not args.model:
        parser.error("--model is required with --live")

    return run(
        args.artifacts,
        args.image,
        args.max_turns,
        args.timeout,
        args.acceptance_timeout,
        live=args.live,
        model=args.model,
        max_tokens=args.max_tokens,
    )


if __name__ == "__main__":
    sys.exit(main())
