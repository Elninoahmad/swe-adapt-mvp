from pathlib import Path

def test_report_ignores_pyc_and_tests(tmp_path: Path) -> None:
    """Reporting must skip .pyc, tests/, and __pycache__/."""
    import json

    from scripts.generate_report import generate

    artifacts = tmp_path / "mock-run-artifacts"
    artifacts.mkdir()

    trace = artifacts / "trace.jsonl"
    trace.write_text(
        '{"turn": 1, "event": "change_event_injected"}\n'
        '{"turn": 2, "event": "write_file", "path": "validators.py"}\n'
    )

    pause = artifacts / "pause-snapshot"
    pause.mkdir()
    (pause / "validators.py").write_text("def validate_email(address):\n    return True\n")
    (pause / "email_service.py").write_text("from validators import validate_email\n")

    pycache = pause / "__pycache__"
    pycache.mkdir()
    (pycache / "validators.cpython-311.pyc").write_bytes(b"\x00\x01\x02\x03")

    tests_dir = pause / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_foo.py").write_text("def test_foo(): pass\n")

    final = artifacts / "final-workspace"
    final.mkdir()
    (final / "validators.py").write_text("def validate_email(address: str) -> bool:\n    return True\n")
    (final / "email_service.py").write_text("from validators import validate_email\n")

    generate(artifacts, acceptance_exit_code=0)

    report_json = artifacts / "report.json"
    assert report_json.exists()
    data = json.loads(report_json.read_text())

    churn = data["post_pause_source_line_churn"]
    assert "validators.py" in churn["files_compared"]
    assert "email_service.py" in churn["files_compared"]
    assert "__pycache__/validators.cpython-311.pyc" in churn["files_excluded"]
    assert "tests/test_foo.py" in churn["files_excluded"]
    assert churn["files_created_after_pause"] == []
