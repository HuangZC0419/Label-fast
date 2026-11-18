"""内存任务状态表，供单进程 Worker 使用。"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def create(
        self,
        task_id: str,
        *,
        source_path: str,
        task_dir: str,
        filename: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        now = time.time()
        record = {
            "task_id": task_id,
            "status": "queued",
            "progress": 0,
            "stage": "排队中",
            "message": "",
            "error": "",
            "page_count": 0,
            "source_path": source_path,
            "task_dir": task_dir,
            "filename": filename,
            "options": options,
            "created_ts": now,
            "finished_ts": None,
        }
        with self._lock:
            self._tasks[task_id] = record
        return self.public(task_id)

    def update(self, task_id: str, **changes: Any) -> dict[str, Any] | None:
        public_fields = {
            "status",
            "progress",
            "stage",
            "message",
            "error",
            "page_count",
        }
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            for key, value in changes.items():
                if key in public_fields:
                    task[key] = value
            if task.get("status") in {"completed", "failed", "cancelled"}:
                if task.get("finished_ts") is None:
                    task["finished_ts"] = time.time()
            return self.public(task_id)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task is not None else None

    def public(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task_id,
                "status": task["status"],
                "progress": task["progress"],
                "stage": task["stage"],
                "message": task["message"],
                "error": task["error"],
                "page_count": task["page_count"],
            }

    def active_ids(self) -> set[str]:
        with self._lock:
            return {
                key
                for key, task in self._tasks.items()
                if task.get("status") in {"queued", "running"}
            }

    def purge_finished_before(self, cutoff: float) -> list[str]:
        with self._lock:
            removed: list[str] = []
            for task_id, task in list(self._tasks.items()):
                finished = task.get("finished_ts")
                if finished is not None and finished < cutoff:
                    removed.append(task_id)
                    self._tasks.pop(task_id, None)
            return removed
