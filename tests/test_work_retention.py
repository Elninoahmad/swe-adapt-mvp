"""Tests for harness/work_retention.py (exact-line, same-file, baseline-reserved)."""

import difflib
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness.work_retention import compute_work_retention
from scripts import run_agent


def _tree(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root


def _compute(tmp_path, s0_files, s1_files, s2_files):
    return compute_work_retention(
        _tree(tmp_path / "s0", s0_files),
        _tree(tmp_path / "s1", s1_files),
        _tree(tmp_path / "s2", s2_files),
    )


def _apply_write_files(workspace: Path, tool_uses: list) -> None:
    for tu in tool_uses:
        assert tu["name"] == "write_file"
        target = workspace / tu["input"]["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tu["input"]["content"])


# --- Task 01 scripted sequence (real starter as baseline) ---

def test_task_01_scripted_sequence(tmp_path):
    responses = run_agent.dry_run_responses()
    pre_pause_uses = responses[0].tool_uses          # three write_file calls
    adaptation_uses = responses[1].tool_uses         # typed validators.py rewrite

    starter = REPO_ROOT / "tasks" / "task_01_extract_and_type" / "repo"

    s0 = tmp_path / "s0"
    shutil.copytree(starter, s0)

    s1 = tmp_path / "s1"
    shutil.copytree(starter, s1)
    _apply_write_files(s1, pre_pause_uses)

    s2 = tmp_path / "s2"
    shutil.copytree(s1, s2)
    _apply_write_files(s2, adaptation_uses)

    report = compute_work_retention(s0, s1, s2)

    # The pause->final adaptation changed exactly the validator signature
    # and its email regex (strict typing + plus-addressed email support).
    # Derive the expected lost texts from the scripted writes themselves
    # instead of hard-coding; real counts are established by CI.
    v1 = pre_pause_uses[0]["input"]["content"]
    v2 = adaptation_uses[0]["input"]["content"]
    changed = [
        line[1:].strip()
        for line in difflib.unified_diff(v1.splitlines(), v2.splitlines())
        if line.startswith("-") and not line.startswith("---")
    ]
    assert [(u["file"], u["text"]) for u in report["lost"]] == [
        ("validators.py", text) for text in changed
    ]
    assert changed == [
        "def validate_email(address):",
        r"return bool(re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', address))",
    ]

    # Counts are internally consistent; absolute values come from CI.
    assert report["work_units"] == report["retained_units"] + report["lost_units"]


# --- Baseline reservation ---

def test_baseline_one_s1_two_s2_one_unit_is_lost(tmp_path):
    s0 = {"foo.py": "def f():\n    return True\n"}
    s1 = {"foo.py": "def f():\n    return True\n    return True\n"}
    report = _compute(tmp_path, s0, s1, s0)

    assert report["work_units"] == 1
    assert report["retained_units"] == 0
    assert report["lost"] == [
        {"file": "foo.py", "line": 3, "text": "return True"}
    ]
    assert report["baseline_reserved_occurrences"] == 1


def test_baseline_reserved_but_growth_retained(tmp_path):
    s0 = {"foo.py": "def f():\n    return True\n"}
    s1 = {"foo.py": "def f():\n    return True\n    return True\n"}
    report = _compute(tmp_path, s0, s1, s1)

    assert report["work_units"] == 1
    assert report["retained_units"] == 1
    assert report["lost_units"] == 0


def test_reservation_capped_by_final_count(tmp_path):
    s0 = {"foo.py": (
        "def a():\n    return True\n"
        "def b():\n    return True\n"
        "def c():\n    return True\n"
    )}
    s1 = {"foo.py": (
        "def a():\n    return True\n"
        "def b():\n    return True\n"
        "def c():\n    return True\n"
        "def d():\n    return True\n"
    )}
    s2 = {"foo.py": (
        "def a():\n    return True\n"
        "def b():\n    return True\n"
    )}
    report = _compute(tmp_path, s0, s1, s2)

    # min(3, 2) reserved, nothing left for the added unit.  Note the added
    # `def d():` is itself a work unit with no final occurrence.
    assert report["work_units"] == 2
    assert report["retained_units"] == 0
    assert report["lost_units"] == 2
    assert report["baseline_reserved_occurrences"] == 2


def test_no_baseline_rule_is_inert(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\nVALUE = \"ok\"\nVALUE = \"ok\"\n"}
    s2 = {"foo.py": "x = 1\nVALUE = \"ok\"\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["work_units"] == 2
    assert report["retained_units"] == 1
    assert report["lost_units"] == 1


# --- Exact matching rules ---

def test_quote_change_is_lost(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\nMSG = 'hi'\n"}
    s2 = {"foo.py": "x = 1\nMSG = \"hi\"\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["retained_units"] == 0
    assert report["lost"] == [{"file": "foo.py", "line": 2, "text": "MSG = 'hi'"}]


def test_whitespace_change_is_retained(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\ny = 2\n"}
    s2 = {"foo.py": "x = 1\n        y = 2\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["retained_units"] == 1
    assert report["lost_units"] == 0


def test_comments_and_blanks_are_not_units(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\n\n# a note\n   \ny = 2\n"}
    s2 = {"foo.py": "x = 1\n\n# a note\n   \ny = 2\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["work_units"] == 1
    assert report["retained_units"] == 1


def test_identical_units_match_in_line_order(tmp_path):
    s0 = {"foo.py": "a = 1\n"}
    s1 = {"foo.py": "a = 1\nRESULT = \"ok\"\nRESULT = \"ok\"\n"}
    s2 = {"foo.py": "a = 1\nRESULT = \"ok\"\n"}
    report = _compute(tmp_path, s0, s1, s2)

    # The later unit in S1 line order is the lost one.
    assert report["retained_units"] == 1
    assert report["lost"] == [{"file": "foo.py", "line": 3, "text": 'RESULT = "ok"'}]


# --- Same-file scope ---

def test_cross_file_paste_is_lost(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\nHELPER = True\n"}
    s2 = {"foo.py": "x = 1\n", "bar.py": "HELPER = True\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["retained_units"] == 0
    assert report["lost"] == [{"file": "foo.py", "line": 2, "text": "HELPER = True"}]


def test_new_file_does_not_rescue_lost_units(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\nOLD = 1\n"}
    s2 = {"foo.py": "x = 1\n", "foo2.py": "OLD = 1\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["retained_units"] == 0
    assert report["lost"] == [{"file": "foo.py", "line": 2, "text": "OLD = 1"}]


def test_deleted_file_units_all_lost(tmp_path):
    s0 = {"foo.py": "x = 1\n"}
    s1 = {"foo.py": "x = 1\n", "gone.py": "a = 1\nb = 2\n"}
    s2 = {"foo.py": "x = 1\n"}
    report = _compute(tmp_path, s0, s1, s2)

    assert report["work_units"] == 2
    assert report["retained_units"] == 0
    assert report["lost_units"] == 2
    assert [u["file"] for u in report["lost"]] == ["gone.py", "gone.py"]


# --- Edge cases and transparency ---

def test_w_zero_ratio_is_null(tmp_path):
    same = {"foo.py": "x = 1\n"}
    report = _compute(tmp_path, same, same, same)

    assert report["work_units"] == 0
    assert report["retained_units"] == 0
    assert report["work_retention_verbatim"] is None
    assert report["lost"] == []


def test_deleted_starter_lines_are_transparent_not_units(tmp_path):
    s0 = {"foo.py": "def old_validate():\n    return True\n"}
    s1 = {"foo.py": "def new_validate():\n    return True\n"}
    s2 = {"foo.py": "def new_validate():\n    return True\n"}
    report = _compute(tmp_path, s0, s1, s2)

    # Only the replaced signature is an addition; the unchanged
    # `return True` line is diff context, and the old signature is
    # reported as a deletion, not a work unit.
    assert report["work_units"] == 1
    assert report["s0_to_s1_deleted_lines"] == 1


def test_qualification_excludes_tests_and_non_py(tmp_path):
    s0 = {}
    s1 = {
        "foo.py": "x = 1\n",
        "tests/test_foo.py": "y = 2\n",
        "notes.md": "z = 3\n",
        "pkg/__pycache__/c.py": "w = 4\n",
    }
    s2 = s1
    report = _compute(tmp_path, s0, s1, s2)

    assert report["work_units"] == 1
    assert report["retained_units"] == 1


def test_deterministic_across_runs(tmp_path):
    s0 = {"foo.py": "def f():\n    return True\n"}
    s1 = {"foo.py": "def f():\n    return True\n    return True\n"}
    files = (s0, s1, s0)
    first = _compute(tmp_path / "a", *files)
    second = _compute(tmp_path / "b", *files)
    assert first == second
