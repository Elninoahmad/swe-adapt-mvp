#!/usr/bin/env python3
"""Generate JSON and Markdown reports from a scripted mock run.

Reads the trace, pause snapshot, and final workspace produced by
demo_mock_run.py.  Computes post-pause source-line churn and writes
report.json + report.md into the artifacts directory.
"""

import argparse
import json
import difflib
from pathlib import Path

_VALID_MODES = ("scripted-mock", "dry-run", "live")
_VALID_STATUSES = ("completed", "incomplete_turn_limit", "incomplete_error")

_MODE_TITLES = {
    "scripted-mock": "Mock Run",
    "dry-run": "Dry Run",
    "live": "Live Agent Run",
}


def _parse_trace(trace_path: Path):
    entries = []
    with open(trace_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _count_writes_after_change_event(entries):
    injected = False
    count = 0
    for e in entries:
        if e.get("event") == "change_event_injected":
            injected = True
        if injected and e.get("event") == "write_file":
            count += 1
    return count, injected


def _qualify_source(path: Path, root: Path) -> bool:
    if path.suffix != ".py":
        return False
    rel_parts = path.relative_to(root).parts
    return not any(part == "tests" or part == "__pycache__" for part in rel_parts)


def _compute_churn(pause_dir: Path, final_dir: Path):
    """Post-pause source-line churn for qualifying Python source files."""
    pause_files = {
        f.relative_to(pause_dir): f
        for f in pause_dir.rglob("*")
        if f.is_file() and _qualify_source(f, pause_dir)
    }
    final_files = {
        f.relative_to(final_dir): f
        for f in final_dir.rglob("*")
        if f.is_file() and _qualify_source(f, final_dir)
    }

    files_compared = []
    files_excluded = []
    files_created_after_pause = []
    added_lines = 0
    removed_lines = 0

    for f in pause_dir.rglob("*"):
        if not f.is_file():
            continue
        if not _qualify_source(f, pause_dir):
            files_excluded.append(str(f.relative_to(pause_dir)))

    for rel, pf in pause_files.items():
        files_compared.append(str(rel))
        if rel not in final_files:
            lines = [ln for ln in pf.read_text().splitlines() if ln.strip()]
            removed_lines += len(lines)
            continue

        ff = final_files[rel]
        pause_text = pf.read_text()
        final_text = ff.read_text()

        if pause_text == final_text:
            continue

        diff = list(difflib.unified_diff(
            pause_text.splitlines(keepends=True),
            final_text.splitlines(keepends=True),
            fromfile=str(rel),
            tofile=str(rel),
        ))
        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                added_lines += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed_lines += 1

    for rel in final_files:
        if rel not in pause_files:
            files_created_after_pause.append(str(rel))

    return {
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "files_compared": sorted(files_compared),
        "files_excluded": sorted(files_excluded),
        "files_created_after_pause": sorted(files_created_after_pause),
    }


def _build_label(mode: str, status: str) -> str:
    if mode not in _VALID_MODES:
        raise ValueError(f"unknown mode: {mode!r}")
    if status not in _VALID_STATUSES:
        raise ValueError(f"unknown status: {status!r}")

    incomplete = status != "completed"

    if mode == "scripted-mock":
        if incomplete:
            return "SCRIPTED MOCK RUN — INCOMPLETE: not an agent result"
        return "SCRIPTED MOCK RUN — not an agent result"
    if mode == "dry-run":
        if incomplete:
            return "DRY RUN — INCOMPLETE: not a real agent result"
        return "DRY RUN — not a real agent result"

    if status == "completed":
        return "LIVE AGENT RUN — agent result"
    if status == "incomplete_turn_limit":
        return "LIVE AGENT RUN — INCOMPLETE: turn limit reached"
    return "LIVE AGENT RUN — INCOMPLETE: error"


def _write_partial_report(artifacts_dir: Path, label: str, mode: str, status: str):
    """Write a partial report when an error-incomplete run produced no artifacts."""
    report = {
        "mode": mode,
        "run_status": status,
        "label": label,
        "final_acceptance_result": "NOT RUN",
        "change_event_seen": False,
        "writes_after_change_event": 0,
        "post_pause_source_line_churn": None,
    }

    json_path = artifacts_dir / "report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    md_path = artifacts_dir / "report.md"
    with open(md_path, "w") as f:
        f.write(f"# SWE-Adapt {_MODE_TITLES[mode]} Report\n\n")
        f.write(f"**Label:** {label}\n\n")
        f.write("## Final Acceptance Result\n\n")
        f.write("- **Status:** NOT RUN\n\n")
        f.write("## Actions After Change Event\n\n")
        f.write("- **Writes after change event:** unavailable (no trace)\n")
        f.write("- **Change event delivered:** unknown (no trace)\n\n")
        f.write("## Post-Pause Source-Line Churn\n\n")
        f.write("- **Status:** unavailable (no pause snapshot / final workspace)\n\n")
        f.write("### Scope and Limitations\n\n")
        f.write("The run ended with an error before a trace or workspace snapshot ")
        f.write("was produced, so acceptance, write counts, and churn could not be measured.\n")

    print(f"Report saved to: {json_path}")
    print(f"Report saved to: {md_path}")


def generate(artifacts_dir: Path, acceptance_exit_code, mode: str = "scripted-mock", status: str = "completed"):
    trace_path = artifacts_dir / "trace.jsonl"
    pause_dir = artifacts_dir / "pause-snapshot"
    final_dir = artifacts_dir / "final-workspace"

    label = _build_label(mode, status)

    if status == "incomplete_error" and (
        not trace_path.exists() or not pause_dir.exists() or not final_dir.exists()
    ):
        _write_partial_report(artifacts_dir, label, mode, status)
        return

    entries = _parse_trace(trace_path)
    writes_after, change_event_seen = _count_writes_after_change_event(entries)
    churn = _compute_churn(pause_dir, final_dir)

    if acceptance_exit_code is None:
        acceptance_result = "NOT RUN"
    else:
        acceptance_result = "PASSED" if acceptance_exit_code == 0 else "FAILED"

    report = {
        "mode": mode,
        "run_status": status,
        "label": label,
        "final_acceptance_result": acceptance_result,
        "change_event_seen": change_event_seen,
        "writes_after_change_event": writes_after,
        "post_pause_source_line_churn": churn,
    }

    json_path = artifacts_dir / "report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    md_path = artifacts_dir / "report.md"
    with open(md_path, "w") as f:
        f.write(f"# SWE-Adapt {_MODE_TITLES[mode]} Report\n\n")
        f.write(f"**Label:** {label}\n\n")
        f.write("## Final Acceptance Result\n\n")
        f.write(f"- **Status:** {report['final_acceptance_result']}\n\n")
        f.write("## Actions After Change Event\n\n")
        f.write(f"- **Writes after change event:** {writes_after}\n")
        f.write(f"- **Change event delivered:** {change_event_seen}\n\n")
        f.write("## Post-Pause Source-Line Churn\n\n")
        f.write(f"- **Added lines:** {churn['added_lines']}\n")
        f.write(f"- **Removed lines:** {churn['removed_lines']}\n")
        f.write(f"- **Files compared:** {', '.join(churn['files_compared']) or 'none'}\n")
        f.write(f"- **Files excluded:** {', '.join(churn['files_excluded']) or 'none'}\n")
        f.write(f"- **Files created after pause:** {', '.join(churn['files_created_after_pause']) or 'none'}\n\n")
        f.write("### Scope and Limitations\n\n")
        f.write("Churn is measured only across qualifying Python source files ")
        f.write("present in the pause snapshot. Files in `tests/` or `__pycache__/`, ")
        f.write("non-`.py` files, and generated artifacts are excluded. ")
        f.write("Line counts come from unified-diff `+` and `-` lines, excluding headers. ")
        f.write("This is a coarse text-level metric, not AST-aware. ")
        f.write("It does not distinguish necessary adaptation from destructive rework. ")
        if mode == "live":
            f.write("Results reflect a live agent run.\n")
        else:
            f.write("Results reflect a hardcoded mock run, not a real agent.\n")

    print(f"Report saved to: {json_path}")
    print(f"Report saved to: {md_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=Path("mock-run-artifacts"))
    parser.add_argument("--mode", default="scripted-mock", choices=_VALID_MODES)
    parser.add_argument("--status", default="completed", choices=_VALID_STATUSES)
    parser.add_argument(
        "--acceptance-exit-code",
        default="0",
        help="integer exit code, or 'none' for NOT RUN",
    )
    args = parser.parse_args()

    raw_code = str(args.acceptance_exit_code).strip().lower()
    acceptance_exit_code = None if raw_code == "none" else int(raw_code)

    generate(args.artifacts, acceptance_exit_code, mode=args.mode, status=args.status)
