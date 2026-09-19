from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from architecture_explorer import analyze_project, build_project_snapshot

DEFAULT_EXCLUDES = {"__pycache__", ".git", ".venv", "node_modules", "venv", "dist", "build"}


class RepoWatcher:
    def __init__(self, repo_path: str | Path, poll_interval_seconds: int = 5):
        self.repo_path = Path(repo_path).resolve()
        self.poll_interval_seconds = poll_interval_seconds
        self.last_snapshot: dict[str, Any] | None = None
        self.summary: dict[str, Any] | None = None
        self.last_updated: str | None = None
        self.file_state: dict[str, int] = {}
        self._refresh_snapshot()

    def _iter_files(self):
        for path in sorted(self.repo_path.rglob("*")):
            if any(part in DEFAULT_EXCLUDES for part in path.parts):
                continue
            if path.is_file():
                yield path

    def _snapshot_file_state(self) -> dict[str, int]:
        state: dict[str, int] = {}
        for path in self._iter_files():
            rel = path.relative_to(self.repo_path).as_posix()
            state[rel] = path.stat().st_mtime_ns
        return state

    def _refresh_snapshot(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self.summary = analyze_project(self.repo_path)
        self.last_snapshot = build_project_snapshot(self.summary)
        self.file_state = self._snapshot_file_state()
        self.last_updated = datetime.now(timezone.utc).isoformat()
        return self.summary, self.last_snapshot

    def has_changes(self) -> bool:
        return self._snapshot_file_state() != self.file_state

    def force_refresh(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return self._refresh_snapshot()

    def scan(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.summary is None or self.has_changes():
            return self._refresh_snapshot()
        return self.summary, self.last_snapshot

    def status(self) -> dict[str, Any]:
        changed = self.has_changes()
        summary = self.summary or {}
        return {
            "repo_path": str(self.repo_path),
            "last_updated": self.last_updated,
            "changed": changed,
            "stale": changed,
            "poll_interval_seconds": self.poll_interval_seconds,
            "module_count": len(summary.get("modules", [])),
            "layer_count": len((self.last_snapshot or {}).get("layers", {})),
        }
