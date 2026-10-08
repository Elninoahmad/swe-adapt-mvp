"""Host-side tests for the starter tests/ digest (freshness + unit behavior)."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_ACCEPTANCE = REPO_ROOT / "tasks" / "task_01_extract_and_type" / "tests_acceptance"
sys.path.insert(0, str(TESTS_ACCEPTANCE))

import digest_utils

STARTER_TESTS = REPO_ROOT / "tasks" / "task_01_extract_and_type" / "repo" / "tests"
DIGEST_FILE = TESTS_ACCEPTANCE / "starter_tests_digest.json"
GENERATOR = REPO_ROOT / "scripts" / "generate_starter_tests_digest.py"


def _write_tree(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def test_digest_file_matches_actual_starter():
    assert DIGEST_FILE.is_file(), (
        "starter_tests_digest.json missing; run "
        "python scripts/generate_starter_tests_digest.py and commit the output"
    )
    baked = json.loads(DIGEST_FILE.read_text())
    live = digest_utils.compute_digest(STARTER_TESTS)
    added, modified, deleted = digest_utils.diff_digests(baked, live)
    assert (added, modified, deleted) == ([], [], []), (
        f"starter_tests_digest.json is stale: added={added} "
        f"modified={modified} deleted={deleted}; regenerate with "
        "scripts/generate_starter_tests_digest.py"
    )


def test_detects_modified_py_file(tmp_path):
    baked = digest_utils.compute_digest(_write_tree(tmp_path / "s", {"tests/a.py": "x = 1\n"}))
    live = digest_utils.compute_digest(_write_tree(tmp_path / "l", {"tests/a.py": "x = 2\n"}))
    assert digest_utils.diff_digests(baked, live) == ([], ["tests/a.py"], [])


def test_detects_added_py_file(tmp_path):
    baked = digest_utils.compute_digest(_write_tree(tmp_path / "s", {"tests/a.py": "x = 1\n"}))
    live = digest_utils.compute_digest(
        _write_tree(tmp_path / "l", {"tests/a.py": "x = 1\n", "tests/conftest.py": ""})
    )
    assert digest_utils.diff_digests(baked, live) == (["tests/conftest.py"], [], [])


def test_detects_deleted_py_file(tmp_path):
    baked = digest_utils.compute_digest(
        _write_tree(tmp_path / "s", {"tests/a.py": "x = 1\n", "tests/b.py": "y = 1\n"})
    )
    live = digest_utils.compute_digest(_write_tree(tmp_path / "l", {"tests/a.py": "x = 1\n"}))
    assert digest_utils.diff_digests(baked, live) == ([], [], ["tests/b.py"])


def test_ignores_generated_caches(tmp_path):
    live_root = _write_tree(tmp_path / "l", {
        "tests/a.py": "x = 1\n",
        "tests/__pycache__/a.cpython-311.pyc": "junk",
        "tests/__pycache__/stray.py": "junk",
        "tests/.pytest_cache/v/cache/nodeids": "junk",
    })
    assert list(digest_utils.compute_digest(live_root)) == ["tests/a.py"]


def test_ignores_non_python_files(tmp_path):
    live_root = _write_tree(tmp_path / "l", {
        "tests/a.py": "x = 1\n",
        "tests/fixtures/data.json": "{}",
    })
    assert list(digest_utils.compute_digest(live_root)) == ["tests/a.py"]


def test_generator_output_matches_helper_and_is_deterministic(tmp_path):
    starter = _write_tree(tmp_path / "starter", {
        "tests/a.py": "x = 1\n",
        "tests/sub/conftest.py": "",
        "tests/__pycache__/c.pyc": "z",
    })
    out1, out2 = tmp_path / "d1.json", tmp_path / "d2.json"
    for out in (out1, out2):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--starter", str(starter), "--out", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
    assert out1.read_bytes() == out2.read_bytes()
    assert json.loads(out1.read_text()) == digest_utils.compute_digest(starter / "tests")
