"""Tests for the optional work-retention proxy in scripts/generate_report.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness.work_retention import compute_work_retention
from scripts.generate_report import generate


STARTER_FILES = {
    "validators.py": (
        "def validate_email(address):\n"
        "    return \"ok\"\n"
    ),
    "app.py": "def main():\n    pass\n",
}

PAUSE_FILES = {
    "validators.py": (
        "def validate_email(address: str) -> bool:\n"
        "    return True\n"
    ),
    "app.py": "def main():\n    pass\n",
}

FINAL_FILES = PAUSE_FILES

TRACE = '{"event": "change_event_injected"}\n{"event": "write_file"}\n'


def _write_tree(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def _full_artifacts(tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    _write_tree(artifacts / "pause-snapshot", PAUSE_FILES)
    _write_tree(artifacts / "final-workspace", FINAL_FILES)
    (artifacts / "trace.jsonl").write_text(TRACE)
    return artifacts


def test_full_report_includes_retention_when_starter_supplied(tmp_path):
    artifacts = _full_artifacts(tmp_path)
    starter = _write_tree(tmp_path / "starter", STARTER_FILES)

    generate(artifacts, 0, starter_dir=starter)

    report = json.loads((artifacts / "report.json").read_text())
    block = report["work_retention"]
    assert block["status"] == "ok"
    assert block["kind"] == "preservation_proxy"

    expected = compute_work_retention(starter, artifacts / "pause-snapshot",
                                      artifacts / "final-workspace")
    for key, value in expected.items():
        assert block[key] == value

    md = (artifacts / "report.md").read_text()
    assert "## Work Retention (Preservation Proxy)" in md
    assert "not a measure of rework or wasted effort" in md


def test_report_unchanged_without_starter(tmp_path):
    artifacts = _full_artifacts(tmp_path)

    generate(artifacts, 0)

    report = json.loads((artifacts / "report.json").read_text())
    assert "work_retention" not in report
    assert report["label"] == "SCRIPTED MOCK RUN — not an agent result"
    md = (artifacts / "report.md").read_text()
    assert "Work Retention" not in md


def test_retention_unavailable_without_pause_snapshot(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    starter = _write_tree(tmp_path / "starter", STARTER_FILES)

    generate(artifacts, 1, status="incomplete_error", starter_dir=starter)

    report = json.loads((artifacts / "report.json").read_text())
    block = report["work_retention"]
    assert block["status"] == "unavailable"
    assert block["kind"] == "preservation_proxy"
    assert block["reason"] == "no pause snapshot"
    # Structured unavailable: never a numeric zero pretending to be the metric.
    assert "work_units" not in block
    assert "work_retention_verbatim" not in block

    md = (artifacts / "report.md").read_text()
    assert "unavailable — no pause snapshot" in md


def test_retention_unavailable_without_final_workspace(tmp_path):
    artifacts = tmp_path / "artifacts"
    _write_tree(artifacts / "pause-snapshot", PAUSE_FILES)
    (artifacts / "trace.jsonl").write_text(TRACE)
    starter = _write_tree(tmp_path / "starter", STARTER_FILES)

    generate(artifacts, 0, status="incomplete_turn_limit", starter_dir=starter)

    report = json.loads((artifacts / "report.json").read_text())
    block = report["work_retention"]
    assert block["status"] == "unavailable"
    assert block["reason"] == "no final workspace"
    assert "work_units" not in block


def test_retention_unavailable_when_starter_dir_missing(tmp_path):
    artifacts = _full_artifacts(tmp_path)

    generate(artifacts, 0, starter_dir=tmp_path / "no-such-starter")

    block = json.loads((artifacts / "report.json").read_text())["work_retention"]
    assert block["status"] == "unavailable"
    assert block["reason"] == "starter directory not found"


def test_w_zero_is_measured_not_unavailable(tmp_path):
    artifacts = _full_artifacts(tmp_path)
    # Starter identical to the pause snapshot: no pre-pause additions.
    starter = _write_tree(tmp_path / "starter", PAUSE_FILES)

    generate(artifacts, 0, starter_dir=starter)

    block = json.loads((artifacts / "report.json").read_text())["work_retention"]
    assert block["status"] == "ok"
    assert block["work_units"] == 0
    assert block["work_retention_verbatim"] is None


def test_cli_starter_flag(tmp_path):
    artifacts = _full_artifacts(tmp_path)
    starter = _write_tree(tmp_path / "starter", STARTER_FILES)
    script = REPO_ROOT / "scripts" / "generate_report.py"

    with_starter = subprocess.run(
        [sys.executable, str(script), "--artifacts", str(artifacts),
         "--starter", str(starter)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert with_starter.returncode == 0, with_starter.stderr
    report = json.loads((artifacts / "report.json").read_text())
    assert report["work_retention"]["status"] == "ok"
    assert report["work_retention"]["kind"] == "preservation_proxy"

    without_starter = subprocess.run(
        [sys.executable, str(script), "--artifacts", str(artifacts)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert without_starter.returncode == 0, without_starter.stderr
    report = json.loads((artifacts / "report.json").read_text())
    assert "work_retention" not in report
