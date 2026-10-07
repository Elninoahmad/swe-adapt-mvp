"""Pause-condition detector for SWE-Adapt Task 01."""

import ast
import subprocess
import sys
from pathlib import Path

_DUPLICATED_PATTERN = r'^[\w\.-]+@[\w\.-]+\.\w+$'
_TEST_TIMEOUT = 30  # seconds


def _validators_exists(repo: Path) -> bool:
    return (repo / "validators.py").is_file()


def _regex_removed(repo: Path) -> bool:
    for name in ("email_service.py", "user_service.py"):
        filepath = repo / name
        if not filepath.is_file():
            return False
        if _DUPLICATED_PATTERN in filepath.read_text():
            return False
    return True


def _get_imported_names(tree: ast.AST, module: str) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                names.add(alias.asname if alias.asname else alias.name)
    return names


def _calls_validator_in_function(
    tree: ast.AST, validator_names: set[str], func_name: str
) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name) and child.func.id in validator_names:
                        return True
    return False


def _service_uses_validator(repo: Path, service_name: str) -> tuple[bool, str]:
    filepath = repo / service_name
    if not filepath.is_file():
        return False, f"{service_name} missing"

    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError as exc:
        return False, f"syntax error in {service_name}: {exc}"

    imported = _get_imported_names(tree, "validators")
    if not imported:
        return False, f"{service_name} does not import from validators"

    target_func = "send_email" if service_name == "email_service.py" else "create_user"
    if not _calls_validator_in_function(tree, imported, target_func):
        return False, f"{service_name} does not call validator in its main function"

    return True, "ok"


def _tests_pass(repo: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(repo / "tests")],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=_TEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "pytest timed out"

    if result.returncode != 0:
        return False, f"pytest failed (exit {result.returncode})"
    return True, "ok"


def is_paused(repo_path: str | Path) -> tuple[bool, str]:
    repo = Path(repo_path)

    if not _validators_exists(repo):
        return False, "validators.py does not exist"

    for svc in ("email_service.py", "user_service.py"):
        ok, reason = _service_uses_validator(repo, svc)
        if not ok:
            return False, reason

    if not _regex_removed(repo):
        return False, "duplicated regex still present in services"

    ok, reason = _tests_pass(repo)
    if not ok:
        return False, reason

    return True, "pause condition met"
