from __future__ import annotations

import asyncio
from collections import deque
import contextlib
import fcntl
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_ROOT = Path(os.environ.get("TRAIN_SERVICE_DATA_ROOT", REPO_ROOT / ".research-mvp-data" / "train-service")).expanduser()
JOBS_PATH = DATA_ROOT / "jobs.json"
SCHEDULER_LOCK_PATH = DATA_ROOT / "scheduler.lock"
DEFAULT_CALLBACK_URL = os.environ.get("TRAIN_SERVICE_CALLBACK_URL", "http://127.0.0.1:8090/api/runtime/training-callback")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def ensure_layout() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    SCHEDULER_LOCK_PATH.touch(exist_ok=True)
    if not JOBS_PATH.exists():
        write_json(JOBS_PATH, {"jobs": [], "updated_at": now_iso()})


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize_path(value: str, *, must_exist: bool = False) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = (REPO_ROOT / raw).resolve()
    else:
        raw = raw.resolve()
    if must_exist and not raw.exists():
        raise FileNotFoundError(str(raw))
    return raw


def infer_experiment_name(script_path: Path, workdir: Path) -> str:
    pattern = re.compile(r"^exp_v[\w.-]+$")
    for candidate in (script_path, *script_path.parents):
        name = candidate.name
        if pattern.match(name):
            return name
        if candidate == workdir:
            break
    return "exp_misc"


def derive_output_dir(script_path: Path, workdir: Path) -> Path:
    return workdir / "output" / infer_experiment_name(script_path, workdir)


def load_jobs() -> dict[str, Any]:
    ensure_layout()
    data = read_json(JOBS_PATH, {"jobs": [], "updated_at": now_iso()})
    if not isinstance(data, dict):
        return {"jobs": [], "updated_at": now_iso()}
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        data["jobs"] = []
    return data


def save_jobs(store: dict[str, Any]) -> None:
    store["updated_at"] = now_iso()
    write_json(JOBS_PATH, store)


def list_jobs() -> list[dict[str, Any]]:
    store = load_jobs()
    jobs = store.get("jobs", [])
    if not isinstance(jobs, list):
        return []
    return [job for job in jobs if isinstance(job, dict)]


def summarize_jobs(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def get_job(job_id: str) -> dict[str, Any] | None:
    for job in list_jobs():
        if str(job.get("id")) == job_id:
            return job
    return None


def update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    store = load_jobs()
    jobs = store.get("jobs", [])
    if not isinstance(jobs, list):
        raise KeyError(job_id)
    for job in jobs:
        if isinstance(job, dict) and str(job.get("id")) == job_id:
            job.update(updates)
            job["updated_at"] = now_iso()
            save_jobs(store)
            return job
    raise KeyError(job_id)


def append_job_event(job_id: str, message: str) -> None:
    store = load_jobs()
    jobs = store.get("jobs", [])
    if not isinstance(jobs, list):
        return
    for job in jobs:
        if isinstance(job, dict) and str(job.get("id")) == job_id:
            events = job.setdefault("events", [])
            if not isinstance(events, list):
                events = []
                job["events"] = events
            events.append({"timestamp": now_iso(), "message": message})
            job["updated_at"] = now_iso()
            save_jobs(store)
            return


def recover_incomplete_jobs() -> int:
    store = load_jobs()
    jobs = store.get("jobs", [])
    if not isinstance(jobs, list):
        return 0
    recovered = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        status = str(job.get("status", ""))
        if status != "running":
            continue
        job["status"] = "queued"
        job["updated_at"] = now_iso()
        job["started_at"] = ""
        job["error"] = ""
        events = job.setdefault("events", [])
        if isinstance(events, list):
            events.append({"timestamp": now_iso(), "message": "job re-queued after service restart"})
        recovered += 1
    if recovered:
        save_jobs(store)
    return recovered


class JobCreateRequest(BaseModel):
    title: str = ""
    script_path: str
    technical_focus: list[str] = Field(default_factory=list)
    script_args: list[str] = Field(default_factory=list)
    workdir: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    runtime_task_id: str = ""
    notify_agent: str = "trainer"
    callback_url: str = ""
    notes: str = ""


class JobActionResponse(BaseModel):
    ok: bool
    train_task_id: str
    status: str


class ResearchMVPCallbackRequest(BaseModel):
    job_id: str
    status: str
    title: str = ""
    script_path: str = ""
    technical_focus: list[str] = Field(default_factory=list)
    script_args: list[str] = Field(default_factory=list)
    workdir: str = ""
    runtime_task_id: str = ""
    notify_agent: str = "trainer"
    log_path: str = ""
    notes: str = ""


def create_job(payload: JobCreateRequest) -> dict[str, Any]:
    script_path = normalize_path(payload.script_path, must_exist=True)
    if not script_path.is_file():
        raise ValueError(f"script_path is not a file: {script_path}")
    workdir = normalize_path(payload.workdir) if payload.workdir.strip() else script_path.parent
    if not workdir.exists() or not workdir.is_dir():
        raise ValueError(f"workdir is not a directory: {workdir}")

    store = load_jobs()
    jobs = store.get("jobs", [])
    if not isinstance(jobs, list):
        jobs = []
        store["jobs"] = jobs

    job_id = f"train-{uuid4().hex[:10]}"
    callback_url = payload.callback_url.strip() or DEFAULT_CALLBACK_URL
    title = payload.title.strip() or script_path.stem
    output_dir = derive_output_dir(script_path, workdir)
    job = {
        "id": job_id,
        "title": title,
        "status": "queued",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "started_at": "",
        "finished_at": "",
        "script_path": str(script_path),
        "script_args": payload.script_args,
        "workdir": str(workdir),
        "technical_focus": payload.technical_focus,
        "runtime_task_id": payload.runtime_task_id.strip(),
        "notify_agent": payload.notify_agent.strip() or "trainer",
        "callback_url": callback_url,
        "notes": payload.notes.strip(),
        "env": payload.env,
        "log_path": str(script_path.parent / "train_log.txt"),
        "output_dir": str(output_dir),
        "error": "",
        "exit_code": None,
        "events": [{"timestamp": now_iso(), "message": "job queued"}],
    }
    jobs.append(job)
    save_jobs(store)
    return job


def queue_snapshot() -> dict[str, Any]:
    jobs = list_jobs()
    jobs.sort(key=lambda item: str(item.get("created_at", "")))
    queued = [job for job in jobs if str(job.get("status")) == "queued"]
    running = [job for job in jobs if str(job.get("status")) == "running"]
    recent = list(reversed(jobs[-10:]))
    return {
        "queued_count": len(queued),
        "running_count": len(running),
        "queued_ids": [str(job.get("id", "")) for job in queued],
        "running_ids": [str(job.get("id", "")) for job in running],
        "recent": recent,
    }


def read_log_tail(path: Path, *, lines: int = 120) -> list[str]:
    if lines <= 0:
        return []
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return [line.rstrip("\n") for line in deque(handle, maxlen=lines)]


def run_shell_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id", ""))
    script_path = Path(str(job.get("script_path", "")))
    if not script_path.exists():
        raise RuntimeError(f"script not found: {script_path}")

    log_path = Path(str(job.get("log_path", script_path.parent / "train_log.txt")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(str(job.get("workdir", script_path.parent)))
    output_dir = Path(str(job.get("output_dir", derive_output_dir(script_path, workdir))))
    output_dir.mkdir(parents=True, exist_ok=True)
    focus = job.get("technical_focus", [])

    env = os.environ.copy()
    env.update({k: str(v) for k, v in (job.get("env", {}) or {}).items()})
    env.update(
        {
            "TRAIN_SERVICE_JOB_ID": job_id,
            "TRAIN_SERVICE_OUTPUT_DIR": str(output_dir),
            "TRAIN_SERVICE_LOG_PATH": str(log_path),
            "TRAIN_SERVICE_TECHNICAL_FOCUS": "; ".join(str(item) for item in focus),
            "TRAIN_SERVICE_RUNTIME_TASK_ID": str(job.get("runtime_task_id", "")),
        }
    )

    command = ["bash", str(script_path), *[str(arg) for arg in (job.get("script_args", []) or [])]]
    append_job_event(job_id, f"running script: {' '.join(command)}")
    recent_lines: deque[str] = deque(maxlen=40)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== {now_iso()} {job_id} START {' '.join(command)} =====\n")
        handle.flush()

        process = subprocess.Popen(
            command,
            cwd=str(workdir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            recent_lines.append(line.rstrip("\n"))
        process.stdout.close()
        exit_code = process.wait()
        handle.write(f"===== {now_iso()} {job_id} END exit_code={exit_code} =====\n")
        handle.flush()

    if exit_code != 0:
        tail = "\n".join(line for line in recent_lines if line.strip())
        raise RuntimeError(tail or f"script failed with code {exit_code}")
    return {
        "exit_code": exit_code,
        "log_path": str(log_path),
        "output_dir": str(output_dir),
    }


def post_callback(job: dict[str, Any]) -> None:
    callback_url = str(job.get("callback_url", "")).strip()
    if not callback_url:
        return
    payload = {
        "job_id": job.get("id", ""),
        "status": job.get("status", ""),
        "title": job.get("title", ""),
        "script_path": job.get("script_path", ""),
        "technical_focus": job.get("technical_focus", []),
        "script_args": job.get("script_args", []),
        "workdir": job.get("workdir", ""),
        "runtime_task_id": job.get("runtime_task_id", ""),
        "notify_agent": job.get("notify_agent", "trainer"),
        "log_path": job.get("log_path", ""),
        "notes": job.get("notes", ""),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        callback_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        append_job_event(str(job.get("id", "")), f"callback delivered to {callback_url}")
    except urllib.error.URLError as exc:
        append_job_event(str(job.get("id", "")), f"callback failed: {exc}")


class JobWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._lock_handle: Any | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _next_job(self) -> dict[str, Any] | None:
        jobs = list_jobs()
        if any(str(job.get("status")) == "running" for job in jobs):
            return None
        queued = [job for job in jobs if str(job.get("status")) == "queued"]
        if not queued:
            return None
        queued.sort(key=lambda job: str(job.get("created_at", "")))
        return queued[0]

    def _acquire_scheduler_lock(self) -> bool:
        ensure_layout()
        handle = SCHEDULER_LOCK_PATH.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._lock_handle = handle
        return True

    def _release_scheduler_lock(self) -> None:
        if self._lock_handle is None:
            return
        with contextlib.suppress(OSError):
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            self._lock_handle.close()
        self._lock_handle = None

    def _run(self) -> None:
        ensure_layout()
        if not self._acquire_scheduler_lock():
            return
        while not self._stop.is_set():
            job = self._next_job()
            if job is None:
                self._stop.wait(1.0)
                continue
            job_id = str(job.get("id", ""))
            update_job(job_id, status="running", started_at=now_iso(), error="")
            append_job_event(job_id, "job started")
            try:
                result = run_shell_job(job)
                finished = update_job(
                    job_id,
                    status="succeeded",
                    finished_at=now_iso(),
                    exit_code=result.get("exit_code", 0),
                    log_path=result.get("log_path", job.get("log_path", "")),
                    output_dir=result.get("output_dir", job.get("output_dir", "")),
                )
                append_job_event(job_id, "job succeeded")
                post_callback(finished)
            except Exception as exc:
                failed = update_job(
                    job_id,
                    status="failed",
                    finished_at=now_iso(),
                    error=str(exc),
                )
                append_job_event(job_id, f"job failed: {exc}")
                post_callback(failed)
        self._release_scheduler_lock()


worker = JobWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_layout()
    recover_incomplete_jobs()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Train Service", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/board")
async def board() -> dict[str, Any]:
    jobs = list_jobs()
    jobs.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return {
        "service": "train_service",
        "data_root": str(DATA_ROOT),
        "counts": summarize_jobs(jobs),
        "queue": queue_snapshot(),
        "jobs": jobs,
        "callback_url": DEFAULT_CALLBACK_URL,
    }


@app.get("/jobs")
async def get_jobs() -> dict[str, Any]:
    jobs = list_jobs()
    jobs.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return {"jobs": jobs, "counts": summarize_jobs(jobs), "queue": queue_snapshot()}


@app.post("/jobs", response_model=JobActionResponse)
async def post_jobs(payload: JobCreateRequest) -> JobActionResponse:
    try:
        job = create_job(payload)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JobActionResponse(ok=True, train_task_id=str(job["id"]), status=str(job["status"]))


@app.get("/jobs/{job_id}")
async def get_job_detail(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job}


@app.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, lines: int = 120) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if lines < 1 or lines > 2000:
        raise HTTPException(status_code=400, detail="lines must be between 1 and 2000")

    log_path = Path(str(job.get("log_path", ""))).expanduser()
    log_lines = read_log_tail(log_path, lines=lines)
    return {
        "job_id": str(job.get("id", "")),
        "status": str(job.get("status", "")),
        "log_path": str(log_path),
        "exists": log_path.exists(),
        "lines": log_lines,
        "line_count": len(log_lines),
    }


@app.get("/queue")
async def get_queue() -> dict[str, Any]:
    return queue_snapshot()


@app.post("/jobs/{job_id}/cancel", response_model=JobActionResponse)
async def cancel_job(job_id: str) -> JobActionResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    status = str(job.get("status", ""))
    if status != "queued":
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status {status}")
    updated = update_job(job_id, status="cancelled", finished_at=now_iso(), error="job cancelled by user")
    append_job_event(job_id, "job cancelled")
    return JobActionResponse(ok=True, train_task_id=job_id, status=str(updated["status"]))


@app.post("/callbacks/research-mvp", response_model=JobActionResponse)
async def callback_research_mvp(payload: ResearchMVPCallbackRequest) -> JobActionResponse:
    job = get_job(payload.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    updated = update_job(
        payload.job_id,
        status=payload.status,
        title=payload.title.strip() or job.get("title", ""),
        script_path=payload.script_path.strip() or job.get("script_path", ""),
        technical_focus=payload.technical_focus,
        script_args=payload.script_args,
        workdir=payload.workdir.strip() or job.get("workdir", ""),
        runtime_task_id=payload.runtime_task_id.strip() or job.get("runtime_task_id", ""),
        notify_agent=payload.notify_agent.strip() or job.get("notify_agent", "trainer"),
        log_path=payload.log_path.strip() or job.get("log_path", ""),
        notes=payload.notes.strip() or job.get("notes", ""),
    )
    append_job_event(payload.job_id, "research_mvp-style callback received")
    post_callback(updated)
    return JobActionResponse(ok=True, train_task_id=payload.job_id, status=str(updated["status"]))


@app.get("/docs/api", response_class=HTMLResponse)
async def api_docs_page() -> str:
    body = (BASE_DIR / "API.md").read_text(encoding="utf-8")
    escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<html><body><pre>{escaped}</pre></body></html>"
