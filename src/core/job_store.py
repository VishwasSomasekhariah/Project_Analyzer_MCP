"""
Async job store for long-running MCP tool calls.

Problem this solves
--------------------
Some MCP tools (query_cpg_rag, query_pageindex_only, query_vector_only) run for
30-90 minutes. Holding a single SSE/HTTP request open that long is fragile: an
upstream proxy / load balancer closes the idle connection (~45 min on GCP),
killing the call with RemoteProtocolError.

The async job-ID pattern fixes this: a `submit_job` tool returns a job_id in
milliseconds, the real work runs as a background asyncio.Task on the server,
and the client polls `check_job_status` with short calls. No connection is ever
held open longer than a few seconds.

Durability
----------
Each job is mirrored to disk as one JSON file under JOBS_DIR (atomic write via
os.replace). The live asyncio.Task and subprocess handle live only in memory.
On server startup, `recover_on_startup()` marks any job still in queued/running
as `lost` (its task and child process died with the previous process), so the
client fails cleanly instead of polling forever.

This module is intentionally decoupled from the concrete tools: callers pass a
`runner` coroutine to `submit()`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.core.paths import JOBS_DIR

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"succeeded", "failed", "cancelled", "lost"}

# A runner is: async (params, register_proc) -> result_dict
#   register_proc(proc) lets a subprocess-based runner expose its handle so the
#   store can track the PID (for cancellation / restart cleanup).
RegisterProc = Callable[[Any], None]
Runner = Callable[[dict, RegisterProc], Awaitable[dict]]


@dataclass
class Job:
    job_id: str
    tool: str
    params: dict
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    heartbeat_at: Optional[float] = None
    pid: Optional[int] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    idempotency_key: Optional[str] = None

    def to_public(self) -> dict:
        """Serializable view returned by check_job_status / cancel_job."""
        elapsed = None
        if self.started_at:
            end = self.finished_at or time.time()
            elapsed = round(end - self.started_at, 2)
        return {
            "job_id": self.job_id,
            "tool": self.tool,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": elapsed,
            "result": self.result,
            "error": self.error,
        }


_FIELDS = set(Job.__dataclass_fields__)


def _best_effort_kill(pid: Optional[int]) -> None:
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class JobStore:
    def __init__(self, jobs_dir: str = JOBS_DIR) -> None:
        self.dir = Path(jobs_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, Job] = {}            # durable mirror (loaded from disk)
        self._tasks: Dict[str, asyncio.Task] = {}  # live tasks (not persisted)
        self._procs: Dict[str, Any] = {}           # live subprocess handles
        self._lock = asyncio.Lock()
        self._load_all()

    # ── persistence ───────────────────────────────────────────────────────────
    def _path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def _persist(self, job: Job) -> None:
        tmp = self._path(job.job_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(job)))
        os.replace(tmp, self._path(job.job_id))

    def _load_all(self) -> None:
        for f in self.dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                job = Job(**{k: v for k, v in data.items() if k in _FIELDS})
                self._jobs[job.job_id] = job
            except Exception as e:  # noqa: BLE001 - skip corrupt files, keep serving
                logger.warning("Skipping unreadable job file %s: %s", f, e)

    async def _set(self, job: Job, **fields: Any) -> None:
        async with self._lock:
            for k, v in fields.items():
                setattr(job, k, v)
            job.heartbeat_at = time.time()
            await asyncio.to_thread(self._persist, job)

    # ── submission / execution ─────────────────────────────────────────────────
    async def submit(
        self,
        tool: str,
        params: dict,
        runner: Runner,
        idempotency_key: Optional[str] = None,
    ) -> Job:
        async with self._lock:
            if idempotency_key:
                for j in self._jobs.values():
                    if j.idempotency_key == idempotency_key and j.status not in (
                        "failed",
                        "cancelled",
                        "lost",
                    ):
                        return j
            job = Job(
                job_id=uuid.uuid4().hex,
                tool=tool,
                params=params,
                idempotency_key=idempotency_key,
            )
            self._jobs[job.job_id] = job
            await asyncio.to_thread(self._persist, job)

        # IMPORTANT: spawn with asyncio.create_task (loop-level), NOT inside any
        # request-scoped anyio task group, so the task outlives the SSE request
        # that created it. Keep a strong reference or the loop may GC it.
        task = asyncio.create_task(self._run(job, runner))
        self._tasks[job.job_id] = task
        task.add_done_callback(lambda _t, jid=job.job_id: self._tasks.pop(jid, None))
        return job

    async def _run(self, job: Job, runner: Runner) -> None:
        await self._set(job, status="running", started_at=time.time())
        try:
            result = await runner(job.params, lambda p: self._register_proc(job, p))
            await self._set(
                job, status="succeeded", result=result, finished_at=time.time()
            )
        except asyncio.CancelledError:
            await self._set(job, status="cancelled", finished_at=time.time())
            raise
        except Exception as e:  # noqa: BLE001 - surface as failed job, never crash loop
            await self._set(
                job,
                status="failed",
                error=f"{e}\n{traceback.format_exc()}",
                finished_at=time.time(),
            )
        finally:
            self._procs.pop(job.job_id, None)

    def _register_proc(self, job: Job, proc: Any) -> None:
        self._procs[job.job_id] = proc
        job.pid = getattr(proc, "pid", None)
        try:
            self._persist(job)  # small write; fine to do synchronously here
        except Exception:  # noqa: BLE001
            pass

    # ── queries / control ───────────────────────────────────────────────────────
    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self, status: Optional[str] = None) -> List[Job]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    async def cancel(self, job_id: str) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status in TERMINAL_STATES:
            return job
        task = self._tasks.get(job_id)
        if task and not task.done():
            # Cancelling the task raises CancelledError at the runner's await
            # point; subprocess runners catch it and kill their child. _run then
            # marks the job cancelled.
            task.cancel()
            return job
        # No live task (e.g. after a restart) — best-effort kill + mark cancelled.
        _best_effort_kill(job.pid)
        await self._set(job, status="cancelled", finished_at=time.time())
        return job

    # ── lifecycle hooks (called at server startup) ──────────────────────────────
    def recover_on_startup(self) -> int:
        """Mark jobs orphaned by a restart as `lost`. Returns count recovered."""
        recovered = 0
        for job in list(self._jobs.values()):
            if job.status in ("queued", "running"):
                _best_effort_kill(job.pid)
                job.status = "lost"
                job.error = "server restarted while job was running"
                job.finished_at = time.time()
                self._persist(job)
                recovered += 1
        if recovered:
            logger.warning("Recovered %d orphaned job(s) -> lost", recovered)
        return recovered

    def gc(self, max_age_days: int = 7) -> int:
        """Delete terminal job files older than max_age_days. Returns count removed."""
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for job in list(self._jobs.values()):
            if job.status in TERMINAL_STATES and (job.finished_at or job.created_at) < cutoff:
                try:
                    self._path(job.job_id).unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
                self._jobs.pop(job.job_id, None)
                removed += 1
        if removed:
            logger.info("GC removed %d old job file(s)", removed)
        return removed


# Module-level singleton shared by the MCP tools and the server startup hook.
job_store = JobStore()
