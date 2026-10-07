#!/usr/bin/env python3
"""Demo: scripted mock run for SWE-Adapt Task 01.

SCRIPTED MOCK RUN — not a real agent result.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from harness.orchestrator import Orchestrator


def main():
    print("=" * 60)
    print("SCRIPTED MOCK RUN — SWE-Adapt Task 01")
    print("This is a hardcoded simulation, not a real agent result.")
    print("=" * 60)

    repo = ROOT / "tasks" / "task_01_extract_and_type" / "repo"
    change_event = ROOT / "tasks" / "task_01_extract_and_type" / "CHANGE_EVENT.md"
    trace_path = ROOT / "trace-mock-run.jsonl"

    if trace_path.exists():
        trace_path.unlink()

    orch = Orchestrator(repo, change_event, trace_path)

    print("\n[SCRIPTED MOCK RUN] Step 1: write validators.py")
    orch.run_step(
        "write_file",
        path="validators.py",
        content=(
            "import re\n\n"
            "def validate_email(address):\n"
            "    return bool(re.match(r'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$', address))\n"
        ),
    )

    print("[SCRIPTED MOCK RUN] Step 2: write email_service.py")
    orch.run_step(
        "write_file",
        path="email_service.py",
        content=(
            "from validators import validate_email\n\n"
            "def send_email(address):\n"
            "    if not validate_email(address):\n"
            "        raise ValueError(\"Invalid email\")\n"
            "    return f\"Sent to {address}\"\n"
        ),
    )

    print("[SCRIPTED MOCK RUN] Step 3: write user_service.py (triggers pause)")
    orch.run_step(
        "write_file",
        path="user_service.py",
        content=(
            "from validators import validate_email\n\n"
            "def create_user(email):\n"
            "    if not validate_email(email):\n"
            "        raise ValueError(\"Invalid email\")\n"
            "    return {\"email\": email, \"created\": True}\n"
        ),
    )

    assert orch.pause_injected, "Pause should have fired after user_service.py"
    print("[SCRIPTED MOCK RUN] Pause detected. Change event injected.")

    print("[SCRIPTED MOCK RUN] Step 4: update validators.py for change event")
    orch.run_step(
        "write_file",
        path="validators.py",
        content=(
            "import re\n\n"
            "def validate_email(address: str) -> bool:\n"
            "    return bool(re.match(r'^[\\w.+-]+@[\\w.-]+\\.\\w+$', address))\n"
        ),
    )

    print("[SCRIPTED MOCK RUN] Mock agent sequence complete.")

    artifacts = ROOT / "mock-run-artifacts"
    if artifacts.exists():
        shutil.rmtree(artifacts)
    artifacts.mkdir()

    shutil.copy(trace_path, artifacts / "trace.jsonl")

    pause_src = orch.workspace.parent / "snapshots" / "pause"
    if pause_src.exists():
        shutil.copytree(pause_src, artifacts / "pause-snapshot")

    final_dst = artifacts / "final-workspace"
    shutil.copytree(orch.workspace, final_dst)

    print(f"[SCRIPTED MOCK RUN] Trace saved to: {artifacts / 'trace.jsonl'}")
    print(f"[SCRIPTED MOCK RUN] Pause snapshot saved to: {artifacts / 'pause-snapshot'}")
    print(f"[SCRIPTED MOCK RUN] Final workspace saved to: {final_dst}")

    print("\n[SCRIPTED MOCK RUN] Running acceptance tests against final workspace...")
    env = os.environ.copy()
    env["SWE_ADAPT_REPO"] = str(orch.workspace)

    acceptance_dir = ROOT / "tasks" / "task_01_extract_and_type" / "tests_acceptance"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(acceptance_dir), "-v"],
        env=env,
        capture_output=True,
        text=True,
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print("[SCRIPTED MOCK RUN] Acceptance tests FAILED")
        sys.exit(1)

    print("[SCRIPTED MOCK RUN] Acceptance tests PASSED")

    print("\n[SCRIPTED MOCK RUN] Generating report...")
    report_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_report.py"),
         "--artifacts", str(artifacts),
         "--acceptance-exit-code", "0"],
        capture_output=True,
        text=True,
    )
    print(report_result.stdout)
    if report_result.stderr:
        print(report_result.stderr)

    if report_result.returncode != 0:
        print("[SCRIPTED MOCK RUN] Report generation FAILED")
        sys.exit(1)

    print("=" * 60)
    print("END OF SCRIPTED MOCK RUN")
    print("=" * 60)


if __name__ == "__main__":
    main()
