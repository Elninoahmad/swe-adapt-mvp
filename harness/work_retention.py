"""Work-retention proxy: exact-line, same-file, baseline-reserved matching.

Given three snapshots — starter (S0), pause point (S1), final workspace (S2) —
this module measures how many of the lines the agent added before the pause
survive verbatim into the final workspace.

Design rules (deliberately conservative and reproducible):

- Same-file matching only.  A line from S1/foo.py can only match in
  S2/foo.py.  Moves, splits, and re-creation under a new name read as lost.
- Exact stripped-text matching.  Whitespace-only normalization; any content
  change (including quote style) is a change.  No fuzzy similarity, no
  rename/move semantics.
- Comment-only and blank lines are never work units.
- One-to-one occurrence counting.  Each S0->S1 added-line occurrence is one
  unit; identical text cannot be counted as more retained units than there
  are occurrences.
- Baseline reservation.  Occurrences of a line that already existed in S0
  are reserved before units may match: an identical line in the final file
  is attributed to the starter, never to the agent.  Identical lines have
  no inferable provenance; this convention makes the proxy hard to inflate
  at the cost of occasionally under-crediting (see limitations).

This is a proxy for verbatim preservation only.  It does NOT measure
wasted work, rework, or adaptation quality: lines changed in response to
the change event count as lost here by design, and retained lines may be
wrong (acceptance tests judge correctness).  Read it next to post-pause
churn, never instead of it.

Limitations: deletion work (lines removed S0->S1) is not part of W and is
reported separately as s0_to_s1_deleted_lines; cross-file moves read as
lost; small W makes the ratio unstable, so counts are the primary output.
"""

import difflib
from collections import defaultdict
from pathlib import Path


def _qualify_source(path: Path, root: Path) -> bool:
    """Same qualification rules as the churn metric."""
    if path.suffix != ".py":
        return False
    rel_parts = path.relative_to(root).parts
    return not any(part == "tests" or part == "__pycache__" for part in rel_parts)


def _qualified_files(root: Path) -> dict:
    """Relative path -> list of lines, for qualifying source files."""
    files = {}
    for f in sorted(root.rglob("*")):
        if f.is_file() and _qualify_source(f, root):
            files[str(f.relative_to(root))] = f.read_text().splitlines()
    return files


def _unit_text(line: str):
    """Stripped text if the line is a work unit, else None."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    return stripped


def _occurrence_counts(lines: list) -> dict:
    counts = {}
    for line in lines:
        stripped = line.strip()
        counts[stripped] = counts.get(stripped, 0) + 1
    return counts


def _opcodes(old_lines: list, new_lines: list):
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    return matcher.get_opcodes()


def _added_units(old_lines: list, new_lines: list) -> list:
    """(1-based S1 line number, stripped text) for each added work unit."""
    units = []
    for tag, _i1, _i2, j1, j2 in _opcodes(old_lines, new_lines):
        if tag in ("insert", "replace"):
            for j in range(j1, j2):
                text = _unit_text(new_lines[j])
                if text is not None:
                    units.append((j + 1, text))
    return units


def _deleted_line_count(old_lines: list, new_lines: list) -> int:
    count = 0
    for tag, i1, i2, _j1, _j2 in _opcodes(old_lines, new_lines):
        if tag in ("delete", "replace"):
            count += i2 - i1
    return count


def compute_work_retention(starter_dir, pause_dir, final_dir) -> dict:
    """Compute the work-retention proxy from three snapshot directories."""
    s0 = _qualified_files(Path(starter_dir))
    s1 = _qualified_files(Path(pause_dir))
    s2 = _qualified_files(Path(final_dir))

    # Collect work units: S0->S1 added lines, grouped per (file, text) in
    # S1 line order; also the S0->S1 deletion transparency count.
    units = defaultdict(list)  # (file, text) -> [s1_lineno, ...]
    work_units = 0
    deleted_lines = 0
    for rel, new_lines in s1.items():
        old_lines = s0.get(rel, [])
        for lineno, text in _added_units(old_lines, new_lines):
            units[(rel, text)].append(lineno)
            work_units += 1
        if rel in s0:
            deleted_lines += _deleted_line_count(old_lines, new_lines)
    for rel, old_lines in s0.items():
        if rel not in s1:
            deleted_lines += len(old_lines)

    retained_by_file = defaultdict(int)
    lost = []
    retained_units = 0
    baseline_reserved = 0
    for (rel, text), linenos in units.items():
        baseline = _occurrence_counts(s0.get(rel, [])).get(text, 0)
        final = _occurrence_counts(s2.get(rel, [])).get(text, 0)
        reserved = min(baseline, final)
        baseline_reserved += reserved
        available = final - reserved
        # Units survive in S1 line order, one-to-one against unreserved
        # final occurrences; the excess units (later in S1 order) are lost.
        r = min(len(linenos), available)
        retained_units += r
        retained_by_file[rel] += r
        for lineno in linenos[r:]:
            lost.append({"file": rel, "line": lineno, "text": text})

    return {
        "work_units": work_units,
        "retained_units": retained_units,
        "lost_units": work_units - retained_units,
        "work_retention_verbatim": (
            retained_units / work_units if work_units else None
        ),
        "baseline_reserved_occurrences": baseline_reserved,
        "s0_to_s1_deleted_lines": deleted_lines,
        "retained_by_file": dict(sorted(retained_by_file.items())),
        "lost": sorted(lost, key=lambda u: (u["file"], u["line"])),
    }
