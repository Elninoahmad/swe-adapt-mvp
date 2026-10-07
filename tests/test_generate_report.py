import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_report import _build_label, generate


VALID_STATUSES = ["completed", "incomplete_turn_limit", "incomplete_error"]
INCOMPLETE_STATUSES = ["incomplete_turn_limit", "incomplete_error"]


def _make_full_artifacts(tmp_path: Path) -> Path:
    artifacts = tmp_path / "artifacts"
    pause = artifacts / "pause-snapshot"
    final = artifacts / "final-workspace"
    pause.mkdir(parents=True)
    final.mkdir(parents=True)

    (pause / "app.py").write_text("def f():\n    return 1\n")
    (final / "app.py").write_text("def f():\n    return 2\n")
    (artifacts / "trace.jsonl").write_text(
        '{"event": "start"}\n'
        '{"event": "change_event_injected"}\n'
        '{"event": "write_file", "path": "app.py"}\n'
    )
    return artifacts


def test_scripted_mock_completed_label_unchanged():
    assert _build_label("scripted-mock", "completed") == "SCRIPTED MOCK RUN — not an agent result"


def test_dry_run_completed_label():
    assert _build_label("dry-run", "completed") == "DRY RUN — not a real agent result"


def test_live_completed_label():
    assert _build_label("live", "completed") == "LIVE AGENT RUN — agent result"


@pytest.mark.parametrize("status", INCOMPLETE_STATUSES)
def test_scripted_mock_incomplete_label_warns_and_marks_incomplete(status):
    label = _build_label("scripted-mock", status)
    assert "INCOMPLETE" in label
    assert "not an agent result" in label


@pytest.mark.parametrize("status", INCOMPLETE_STATUSES)
def test_dry_run_incomplete_label_warns_and_marks_incomplete(status):
    label = _build_label("dry-run", status)
    assert "INCOMPLETE" in label
    assert "not a real agent result" in label


@pytest.mark.parametrize("status", INCOMPLETE_STATUSES)
def test_live_incomplete_labels_say_incomplete(status):
    assert "INCOMPLETE" in _build_label("live", status)


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_unknown_mode_rejected(status):
    with pytest.raises(ValueError):
        _build_label("simulation", status)


@pytest.mark.parametrize("mode", ["scripted-mock", "dry-run", "live"])
def test_unknown_status_rejected(mode):
    with pytest.raises(ValueError):
        _build_label(mode, "crashed")


@pytest.mark.parametrize("mode", ["scripted-mock", "dry-run", "live"])
@pytest.mark.parametrize("status", INCOMPLETE_STATUSES)
def test_incomplete_runs_marked_incomplete_in_report_json_and_md(tmp_path, mode, status):
    artifacts = _make_full_artifacts(tmp_path / f"{mode}-{status}")
    generate(artifacts, 1, mode=mode, status=status)

    report = json.loads((artifacts / "report.json").read_text())
    assert report["mode"] == mode
    assert report["run_status"] == status
    assert "INCOMPLETE" in report["label"]
    if mode == "scripted-mock":
        assert "not an agent result" in report["label"]
    if mode == "dry-run":
        assert "not a real agent result" in report["label"]

    md = (artifacts / "report.md").read_text()
    assert f"**Label:** {report['label']}" in md
    assert "INCOMPLETE" in md
    if mode == "scripted-mock":
        assert "not an agent result" in md
    if mode == "dry-run":
        assert "not a real agent result" in md


def test_scripted_demo_defaults_unchanged(tmp_path):
    artifacts = _make_full_artifacts(tmp_path)
    generate(artifacts, 0)  # historical scripted-demo call signature
    report = json.loads((artifacts / "report.json").read_text())
    assert report["mode"] == "scripted-mock"
    assert report["run_status"] == "completed"
    assert report["label"] == "SCRIPTED MOCK RUN — not an agent result"
    assert report["final_acceptance_result"] == "PASSED"
    assert report["writes_after_change_event"] == 1


def test_acceptance_none_is_not_run(tmp_path):
    artifacts = _make_full_artifacts(tmp_path)
    generate(artifacts, None, mode="dry-run", status="completed")
    report = json.loads((artifacts / "report.json").read_text())
    assert report["final_acceptance_result"] == "NOT RUN"


def test_incomplete_error_missing_artifacts_writes_partial_report(tmp_path):
    artifacts = tmp_path / "empty-artifacts"
    artifacts.mkdir()
    generate(artifacts, 1, mode="live", status="incomplete_error")

    report = json.loads((artifacts / "report.json").read_text())
    assert report["mode"] == "live"
    assert report["run_status"] == "incomplete_error"
    assert "INCOMPLETE" in report["label"]
    assert report["final_acceptance_result"] == "NOT RUN"
    assert report["post_pause_source_line_churn"] is None
    assert (artifacts / "report.md").exists()


def test_markdown_headings_work_for_all_modes(tmp_path):
    for mode, expected in [
        ("scripted-mock", "# SWE-Adapt Mock Run Report"),
        ("dry-run", "# SWE-Adapt Dry Run Report"),
        ("live", "# SWE-Adapt Live Agent Run Report"),
    ]:
        artifacts = _make_full_artifacts(tmp_path / mode)
        generate(artifacts, 0, mode=mode, status="completed")
        md = (artifacts / "report.md").read_text()
        assert md.startswith(expected)
        assert "## Actions After Change Event" in md


def test_incomplete_turn_limit_with_trace_but_no_snapshot_writes_partial_report(tmp_path):
    artifacts = tmp_path / "partial-artifacts"
    artifacts.mkdir()
    (artifacts / "trace.jsonl").write_text(
        '{"event": "start"}\n'
        '{"event": "change_event_injected"}\n'
        '{"event": "write_file", "path": "app.py"}\n'
    )

    generate(artifacts, 1, mode="live", status="incomplete_turn_limit")

    report = json.loads((artifacts / "report.json").read_text())
    assert "INCOMPLETE" in report["label"]
    assert report["final_acceptance_result"] == "NOT RUN"
    assert report["change_event_seen"] is True
    assert report["writes_after_change_event"] == 1
    assert report["post_pause_source_line_churn"] is None

    md = (artifacts / "report.md").read_text()
    assert "**Writes after change event:** 1" in md
    assert "unavailable (no trace)" not in md
