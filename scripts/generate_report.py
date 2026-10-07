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


def generate(artifacts_dir: Path, acceptance_exit_code: int):
    trace_path = artifacts_dir / "trace.jsonl"
    pause_dir = artifacts_dir / "pause-snapshot"
    final_dir = artifacts_dir / "final-workspace"

    entries = _parse_trace(trace_path)
    writes_after, change_event_seen = _count_writes_after_change_event(entries)
    churn = _compute_churn(pause_dir, final_dir)

    report = {
        "label": "SCRIPTED MOCK RUN — not an agent result",
        "final_acceptance_result": "PASSED" if acceptance_exit_code == 0 else "FAILED",
        "change_event_seen": change_event_seen,
        "writes_after_change_event": writes_after,
        "post_pause_source_line_churn": churn,
    }

    json_path = artifacts_dir / "report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)

    md_path = artifacts_dir / "report.md"
    with open(md_path, "w") as f:
        f.write("# SWE-Adapt Mock Run Report\n\n")
        f.write("**Label:** SCRIPTED MOCK RUN — not an agent result\n\n")
        f.write("## Final Acceptance Result\n\n")
        f.write(f"- **Status:** {report['final_acceptance_result']}\n\n")
        f.write("## Scripted Actions After Change Event\n\n")
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
        f.write("Results reflect a hardcoded mock run, not a real agent.\n")

    print(f"Report saved to: {json_path}")
    print(f"Report saved to: {md_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=Path("mock-run-artifacts"))
    parser.add_argument("--acceptance-exit-code", type=int, default=0)
    args = parser.parse_args()
    generate(args.artifacts, args.acceptance_exit_code)
