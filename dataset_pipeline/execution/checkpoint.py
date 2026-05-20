"""
Per-(query_id, plan_id) checkpoint manager with atomic writes.
"""

from __future__ import annotations

import logging
import os

from dataset_pipeline.utils.io import load_json, save_json

logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self, checkpoint_dir: str, name: str = "execution") -> None:
        os.makedirs(checkpoint_dir, exist_ok=True)
        self._path = os.path.join(checkpoint_dir, f"{name}_state.json")
        self._state: dict = self._load()

    def _load(self) -> dict:
        if os.path.exists(self._path):
            try:
                return load_json(self._path)
            except Exception as e:
                logger.warning(f"Checkpoint load failed, starting fresh: {e}")
        return {"completed": [], "failed": []}

    def _save(self) -> None:
        save_json(self._path, self._state)

    def is_done(self, trace_id: str) -> bool:
        return trace_id in self._state["completed"]

    def mark_done(self, trace_id: str) -> None:
        if trace_id not in self._state["completed"]:
            self._state["completed"].append(trace_id)
            self._save()

    def mark_failed(self, trace_id: str) -> None:
        if trace_id not in self._state["failed"]:
            self._state["failed"].append(trace_id)
            self._save()

    @property
    def completed_count(self) -> int:
        return len(self._state["completed"])

    @property
    def failed_count(self) -> int:
        return len(self._state["failed"])
