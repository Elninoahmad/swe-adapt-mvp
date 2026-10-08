#!/usr/bin/env python3
"""Generate starter_tests_digest.json from the starter repo.

Hashes every .py file under the starter's tests/ directory (ignoring
__pycache__, .pyc, and .pytest_cache) as relative POSIX path -> SHA-256.
Run this whenever the starter's tests change, and commit the output;
tests/test_starter_tests_digest.py fails if the file drifts from the
starter.  Non-Python fixtures under tests/ are out of scope.

CI never runs this script on push.  To bootstrap the JSON without a
local Python, a temporary Tests-workflow step runs it with
--out "$RUNNER_TEMP/starter_tests_digest.json" and prints the result.
"""

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TESTS_ACCEPTANCE = (
    _REPO_ROOT / "tasks" / "task_01_extract_and_type" / "tests_acceptance"
)
if str(_TESTS_ACCEPTANCE) not in sys.path:
    sys.path.insert(0, str(_TESTS_ACCEPTANCE))

from digest_utils import compute_digest

DEFAULT_STARTER = _REPO_ROOT / "tasks" / "task_01_extract_and_type" / "repo"
DEFAULT_OUT = _TESTS_ACCEPTANCE / "starter_tests_digest.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starter", type=Path, default=DEFAULT_STARTER,
                        help="starter repo directory (default: Task 01 starter)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="output JSON path")
    args = parser.parse_args(argv)

    tests_root = args.starter / "tests"
    if not tests_root.is_dir():
        print(f"error: {tests_root} does not exist", file=sys.stderr)
        return 1

    digest = compute_digest(tests_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(digest, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {len(digest)} entr{'y' if len(digest) == 1 else 'ies'} to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
