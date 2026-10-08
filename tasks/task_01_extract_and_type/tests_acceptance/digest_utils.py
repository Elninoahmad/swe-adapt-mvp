"""Shared digest logic for the starter tests/ integrity check.

Used by three consumers that must agree exactly:
- scripts/generate_starter_tests_digest.py (writes the baked digest)
- tests_acceptance/test_acceptance.py (compares the live workspace)
- tests/test_starter_tests_digest.py (host freshness + unit tests)

Scope: .py files under tests/ only.  Non-Python fixtures are out of scope.
Generated caches (__pycache__, .pyc, .pytest_cache) are ignored so valid
runs do not fail.
"""

import hashlib
from pathlib import Path

_IGNORED_DIRS = frozenset({"__pycache__", ".pytest_cache"})
_IGNORED_SUFFIXES = (".pyc",)


def iter_test_py_files(tests_root: Path):
    """Yield (relative POSIX path, absolute path) for qualifying .py files."""
    tests_root = Path(tests_root)
    if not tests_root.is_dir():
        return
    for path in sorted(tests_root.rglob("*.py")):
        rel_parts = path.relative_to(tests_root).parts
        if any(part in _IGNORED_DIRS for part in rel_parts):
            continue
        if any(path.name.endswith(suffix) for suffix in _IGNORED_SUFFIXES):
            continue
        yield path.relative_to(tests_root).as_posix(), path


def compute_digest(tests_root: Path) -> dict:
    """Relative POSIX path -> SHA-256 of file bytes, sorted by path."""
    digest = {}
    for rel, path in iter_test_py_files(tests_root):
        digest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(digest.items()))


def diff_digests(baked: dict, live: dict):
    """Return (added, modified, deleted) relative-path lists, sorted."""
    added = sorted(set(live) - set(baked))
    deleted = sorted(set(baked) - set(live))
    modified = sorted(
        key for key in set(baked) & set(live) if baked[key] != live[key]
    )
    return added, modified, deleted
