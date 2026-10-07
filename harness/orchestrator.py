"""Orchestrator core for SWE-Adapt MVP.

Drives a turn-based agent loop inside a copied workspace.  After every
write_file, checks is_paused().  When the pause condition first becomes
true, injects CHANGE_EVENT.md exactly once, snapshots the workspace,
and continues.  No API calls; tools are restricted to list_files,
read_file, and write_file with path sandboxing.
"""

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pause_condition import is_paused


class Orchestrator:
    def __init__(
        self,
        workspace_src: Path,
        change_event_src: Path,
        trace_path: Path | None = None,
    ):
        self.workspace = Path(tempfile.mkdtemp()) / "workspace"
        shutil.copytree(workspace_src, self.workspace)

        self.change_event = Path(change_event_src).read_text()
        self.change_event_src = Path(change_event_src)
        self.trace_path = trace_path
        self.trace: list[dict[str, Any]] = []
        self.turn = 0
        self.pause_injected = False
        self.conversation: list[dict[str, Any]] = []

        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            if self.trace_path.exists():
                self.trace_path.unlink()

    def _resolve_path(self, raw_path: str) -> Path:
        if Path(raw_path).is_absolute():
            raise ValueError(f"Absolute paths not allowed: {raw_path}")

        parts = Path(raw_path).parts
        current = self.workspace
        for part in parts:
            if part == ".":
                continue
            next_path = current / part
            if next_path.is_symlink():
                raise ValueError(f"Symlink detected in path: {raw_path}")
            current = next_path

        resolved = current.resolve()
        try:
            resolved.relative_to(self.workspace.resolve())
        except ValueError:
            raise ValueError(f"Path escapes workspace: {raw_path}")

        return resolved

    def list_files(self, path: str = ".") -> list[str]:
        target = self._resolve_path(path)
        if not target.exists():
            return []
        return [
            str(f.relative_to(self.workspace))
            for f in target.rglob("*")
            if f.is_file()
        ]

    def read_file(self, path: str) -> str:
        target = self._resolve_path(path)
        if not target.is_file():
            raise FileNotFoundError(f"Not a file: {path}")
        return target.read_text()

    def write_file(self, path: str, content: str) -> None:
        target = self._resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        self._log(
            "write_file",
            {"path": path, "content_length": len(content)},
        )
        self._check_pause()

    def _check_pause(self) -> None:
        paused, reason = is_paused(self.workspace)
        self._log("pause_check", {"paused": paused, "reason": reason})
        if paused and not self.pause_injected:
            self._inject_change_event()
            self._save_pause_snapshot()

    def _inject_change_event(self) -> None:
        self.pause_injected = True
        self.conversation.append(
            {"role": "user", "content": self.change_event}
        )
        self._log(
            "change_event_injected",
            {"source": str(self.change_event_src)},
        )

    def _save_pause_snapshot(self) -> None:
        snapshot_dir = self.workspace.parent / "snapshots" / "pause"
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        shutil.copytree(self.workspace, snapshot_dir)
        self._log("pause_snapshot", {"path": str(snapshot_dir)})

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        self.turn += 1
        entry = {
            "turn": self.turn,
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self.trace.append(entry)
        if self.trace_path:
            with open(self.trace_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def run_step(self, tool_name: str, **kwargs: Any) -> Any:
        log_data: dict[str, Any] = {"tool": tool_name}
        if tool_name == "write_file":
            log_data["path"] = kwargs.get("path")
            content = kwargs.get("content", "")
            log_data["content_length"] = len(content)
            log_data["content_hash"] = hashlib.sha256(
                content.encode()
            ).hexdigest()[:16]
        elif tool_name == "read_file":
            log_data["path"] = kwargs.get("path")
        elif tool_name == "list_files":
            log_data["path"] = kwargs.get("path", ".")
        else:
            log_data["kwargs"] = kwargs
        self._log("tool_call", log_data)

        if tool_name == "list_files":
            return self.list_files(**kwargs)
        if tool_name == "read_file":
            return self.read_file(**kwargs)
        if tool_name == "write_file":
            return self.write_file(**kwargs)
        raise ValueError(f"Unknown tool: {tool_name}")
