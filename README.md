# swe-adapt-mvp

MVP benchmark for testing how coding agents adapt to changing software requirements.

&gt; **Status: scripted mock only.** Every result produced by this repo so far comes from
&gt; hardcoded fake agent responses. **No real agent run exists, and no leaderboard
&gt; result exists.** Nothing here is a validated measure of agent capability yet.

## What exists today

- **One task** (`tasks/task_01_extract_and_type/`): a starter repo with duplicated
  validation logic, `INSTRUCTIONS.md` describing the refactor, a mid-task
  `CHANGE_EVENT.md` — a requirements change adding **plus-addressed email
  support** and requiring **strict typing** — pause-check tests, and a
  Docker-runnable acceptance suite (`tests_acceptance/`).
- **A tested pause detector** (`pause_condition.is_paused`): consulted after every
  agent write; when it first fires, the change event is injected exactly once and
  the workspace is snapshotted.
- **A turn-based harness**: `Orchestrator` (copied workspace with path guards;
  not a complete security sandbox; JSONL trace with content hashes — never file
  contents) and `Adapter` (agent loop with a turn limit, one injection of the
  change event).
- **Docker-isolated checks**: `DockerTestRunner` runs pause checks and
  `DockerAcceptanceRunner` runs final acceptance, both in containers with
  `--network none`, dropped capabilities, no-new-privileges, read-only mounts for
  acceptance, `--pull=never`, and a minimal allowlisted subprocess environment.
  They fail hard on Docker problems; they never fall back to host pytest.
- **A scripted dry-run CLI** (`scripts/run_agent.py`, default mode): a fixed
  sequence of fake responses — three file writes, a pause plus change event, an
  adaptation to the new requirements, then a text-only "Done." — through the real
  Orchestrator and Adapter with real Docker runners.
- **JSON/Markdown reporting** (`scripts/generate_report.py`): writes
  `report.json` and `report.md` with an explicit mode label, acceptance result,
  event/write counts, and churn.

## How the scripted dry run works

1. Docker preflight: daemon must be reachable and the tester image must exist
   locally. The CLI never pulls.
2. The starter repo is copied to a temporary workspace; the fake agent writes
   `validators.py`, `email_service.py`, `user_service.py`.
3. The pause detector fires after the third write; `CHANGE_EVENT.md` is injected
   exactly once into the conversation and a pause snapshot is saved.
4. The change event adds plus-addressed email support and requires strict typing.
   The scripted agent adapts by rewriting `validators.py` with typed signatures
   and an email regex that accepts plus-addressed addresses.
5. Final acceptance runs inside Docker against `tests_acceptance/`.
6. Artifacts and the report are written; the exit code reflects the outcome
   (0 success, 1 acceptance failed, 3 change event never fired, 4 turn limit,
   5 Docker failure).

## Artifacts

| File / directory | Contents |
| --- | --- |
| `report.json` / `report.md` | Mode label (dry runs are explicitly marked as not real agent results), acceptance status, change-event/write counts, churn summary |
| `trace.jsonl` | Ordered event stream: tool calls, writes (path + length + content hash), pause checks, change-event injection, snapshot |
| `pause-snapshot/` | Workspace as of the pause |
| `final-workspace/` | Workspace at end of run |

## The metric: post-pause source-line churn

The report counts added/removed lines (unified-diff `+`/`-`, headers excluded)
across qualifying `.py` files that exist in the pause snapshot. Files under
`tests/` or `__pycache__/`, non-Python files, and files created after the pause
are excluded.

This is a **coarse text-level metric, not AST-aware**, and it does not distinguish
necessary adaptation from destructive rework. It is **not a validated rework
ratio** — treat it as instrumentation, not a score.

## Running locally

Prerequisites: Docker, and the tester image built once:

```bash
docker build -f docker/tester/Dockerfile -t swe-adapt-tester .
```

Run the scripted dry run:

```bash
python scripts/run_agent.py --artifacts dry-run-artifacts
```

Run the test suite (hermetic unit tests plus Docker-dependent end-to-end tests,
which require the image above). Install the pinned acceptance-test dependencies
first:

```bash
python -m pip install -r tasks/task_01_extract_and_type/requirements-acceptance.txt
python -m pytest tests/ -v
```

## Running in GitHub Actions: Tests workflow

The Tests workflow runs the full suite in GitHub Actions, including the scripted
dry-run CLI end-to-end, and uploads its artifacts. It triggers on **push** and
**workflow_dispatch** (manual); opening a pull request alone does not trigger it.

1. Open the repo's **Actions** tab and select the **Tests** workflow.
2. To get a fresh run, push to the repo, or use **Run workflow** for a manual
   dispatch.
3. Once a run completes, open its summary page and scroll to the **Artifacts**
   section.
4. Download **`scripted-mock-artifacts`** and unpack it — the artifact must be
   downloaded to inspect `report.json`, `report.md`, `trace.jsonl`,
   `pause-snapshot/`, and `final-workspace/` from the scripted run.

## What is not here yet

- **No real agent run.** All results to date come from scripted fake responses.
- **No leaderboard, ranking, or validated scoring.** Churn is diagnostic
  instrumentation only.
- A manual-only live workflow exists at `.github/workflows/task-01-live.yml`, but
  it has **0 runs** and **no `ANTHROPIC_API_KEY` secret is configured** — no live
  execution has ever happened, and live-agent results are not part of the current
  evidence base.
