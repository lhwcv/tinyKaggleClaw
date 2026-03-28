from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from research_mvp.models import (
    ConsoleInputRequest,
    ArtifactCreate,
    MessageCreate,
    ProjectCreate,
    ReviewRequest,
    TaskCompleteRequest,
    now_iso,
)
from research_mvp.logging_utils import configure_logging
from research_mvp.runtime_cli import (
    DEFAULT_CONFIG_PATH,
    ensure_runtime_layout,
    inbox_files,
    load_config,
    queue_message,
    read_json,
    refresh_status,
    runtime_dirs,
    sorted_thread_messages,
    summarize_tasks,
)
from research_mvp.store import ProjectStore

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
store = ProjectStore()
logger = configure_logging(BASE_DIR.parent / ".research-mvp-data" / "logs")


class RuntimeBoardMessageCreate(BaseModel):
    sender: str = "human"
    recipient: str
    content: str


class RuntimeTrainingCallbackCreate(BaseModel):
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


def _runtime_cfg():
    cfg = load_config(DEFAULT_CONFIG_PATH)
    ensure_runtime_layout(cfg)
    return cfg


def _runtime_agent_snapshot(cfg) -> list[dict]:
    state = refresh_status(cfg)
    agents_state = state.get("agents", {}) if isinstance(state, dict) else {}
    snapshots: list[dict] = []
    for agent in cfg.agents:
        info = agents_state.get(agent, {}) if isinstance(agents_state, dict) else {}
        inbox = inbox_files(cfg, agent)
        pending = 0
        last_message = {}
        for path in inbox:
            payload = read_json(path, {})
            if not isinstance(payload, dict):
                continue
            last_message = {
                "id": path.name,
                "from": payload.get("from", ""),
                "to": payload.get("to", ""),
                "timestamp": payload.get("timestamp", ""),
                "task_id": payload.get("task_id", ""),
                "delivered_at": payload.get("delivered_at", ""),
                "content": payload.get("content", payload.get("message", "")),
            }
            if not payload.get("delivered_at"):
                pending += 1
        snapshots.append(
            {
                "name": agent,
                "status": info.get("status", "unknown"),
                "target": info.get("target", ""),
                "last_event": info.get("last_event", ""),
                "pending_inbox": pending,
                "last_message": last_message,
            }
        )
    return snapshots


def _runtime_board_state(limit: int = 120) -> dict:
    cfg = _runtime_cfg()
    paths = runtime_dirs(cfg)
    thread_rows = sorted_thread_messages(cfg)[-limit:]
    return {
        "config_path": str(cfg.config_path),
        "session_name": cfg.session_name,
        "workdir": str(cfg.workdir),
        "runtime_root": str(cfg.runtime_root),
        "thread_path": str(paths["thread"]),
        "workflow_state": {},
        "task_summary": summarize_tasks(cfg),
        "agents": _runtime_agent_snapshot(cfg),
        "messages": thread_rows,
    }


def _send_to_tmux_target(project_id: str, target: str, content: str, *, buffer_prefix: str) -> None:
    load = subprocess.run(
        ["tmux", "load-buffer", "-b", f"{buffer_prefix}-{project_id}", "-"],
        input=content,
        text=True,
        capture_output=True,
    )
    if load.returncode != 0:
        logger.warning("Failed to load tmux buffer project=%s target=%s", project_id, target)
        raise HTTPException(status_code=500, detail=load.stderr.strip() or "Failed to load tmux buffer")

    paste = subprocess.run(
        ["tmux", "paste-buffer", "-b", f"{buffer_prefix}-{project_id}", "-t", target],
        capture_output=True,
        text=True,
    )
    subprocess.run(["tmux", "delete-buffer", "-b", f"{buffer_prefix}-{project_id}"], capture_output=True, text=True)
    if paste.returncode != 0:
        logger.warning("Failed to paste tmux buffer project=%s target=%s", project_id, target)
        raise HTTPException(status_code=500, detail=paste.stderr.strip() or "Failed to paste tmux buffer")

    for key in ("Enter", "C-m", "C-j"):
        subprocess.run(["tmux", "send-keys", "-t", target, key], capture_output=True, text=True)


class LeaderLoop:
    def __init__(self, project_store: ProjectStore):
        self.project_store = project_store
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.project_store.tick()
            except Exception:
                logger.exception("Leader loop tick failed")
            self._stop.wait(3)


leader_loop = LeaderLoop(store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    leader_loop.start()
    yield
    leader_loop.stop()


app = FastAPI(title="Autonomous ML Research Board", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/runtime", status_code=307)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_thread(project_id: str) -> str:
    logger.info("Thread page requested for project=%s", project_id)
    return (STATIC_DIR / "thread.html").read_text(encoding="utf-8")


@app.get("/runtime", response_class=HTMLResponse)
async def runtime_board() -> str:
    return (STATIC_DIR / "runtime_board.html").read_text(encoding="utf-8")


@app.get("/api/state")
async def get_state() -> dict:
    logger.info("State requested")
    return store.state()


@app.get("/api/projects/{project_id}")
async def get_project_detail(project_id: str) -> dict:
    try:
        logger.info("Project detail requested for %s", project_id)
        return {"project": store.project_detail(project_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.get("/api/events")
async def stream_events() -> StreamingResponse:
    async def event_stream():
        while True:
            payload = json.dumps(store.state(), ensure_ascii=False)
            yield f"data: {payload}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/runtime/board")
async def get_runtime_board(limit: int = 120) -> dict:
    try:
        return _runtime_board_state(limit=limit)
    except Exception as exc:
        logger.exception("Runtime board state request failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/runtime/messages")
async def post_runtime_message(payload: RuntimeBoardMessageCreate) -> dict:
    cfg = _runtime_cfg()
    sender = payload.sender.strip() or "human"
    recipient = payload.recipient.strip()
    content = payload.content.strip()
    if sender != "human" and sender not in cfg.agents:
        raise HTTPException(status_code=400, detail=f"Unknown sender: {sender}")
    if recipient != "all" and recipient not in cfg.agents:
        raise HTTPException(status_code=400, detail=f"Unknown recipient: {recipient}")
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    message_id, task_id = queue_message(
        cfg,
        sender,
        recipient,
        content,
        create_task_record=(sender == "human" and recipient != "all"),
        task_marker=now_iso() if sender == "human" else "",
    )
    logger.info("Runtime board queued message %s -> %s id=%s", sender, recipient, message_id)
    return {"ok": True, "message_id": message_id, "task_id": task_id, "board": _runtime_board_state(limit=120)}


@app.post("/api/runtime/training-callback")
async def post_runtime_training_callback(payload: RuntimeTrainingCallbackCreate) -> dict:
    cfg = _runtime_cfg()
    recipient = payload.notify_agent.strip() or "trainer"
    if recipient not in cfg.agents:
        raise HTTPException(status_code=400, detail=f"Unknown notify_agent: {recipient}")
    lines = [
        f"Training job `{payload.job_id}` finished with status `{payload.status}`.",
        f"Title: {payload.title.strip() or '-'}",
        f"Script: {payload.script_path.strip() or '-'}",
    ]
    if payload.technical_focus:
        lines.append(f"Technical focus: {json.dumps(payload.technical_focus, ensure_ascii=False)}")
    if payload.script_args:
        lines.append(f"Script args: {json.dumps(payload.script_args, ensure_ascii=False)}")
    if payload.workdir.strip():
        lines.append(f"Workdir: {payload.workdir.strip()}")
    if payload.log_path.strip():
        lines.append(f"Log: {payload.log_path.strip()}")
    if payload.notes.strip():
        lines.append(f"Notes: {payload.notes.strip()}")
    lines.append(
        "Please inspect the training result, summarize what matters, write the result note to "
        "`docs/` using the repository's existing baseline naming pattern such as "
        "`docs/baseline_v11_1_exp_result.md`, and then send a concise summary message to leader."
    )
    content = "\n".join(lines)
    message_id, task_id = queue_message(
        cfg,
        "system",
        recipient,
        content,
        create_task_record=False,
        linked_task_id=payload.runtime_task_id.strip(),
        task_marker="",
    )
    logger.info(
        "Training callback queued for %s from job=%s status=%s message=%s",
        recipient,
        payload.job_id,
        payload.status,
        message_id,
    )
    return {"ok": True, "message_id": message_id, "task_id": task_id, "board": _runtime_board_state(limit=120)}


@app.post("/api/projects")
async def create_project(payload: ProjectCreate) -> dict:
    project = store.create_project(payload)
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/submit")
async def submit_project(project_id: str) -> dict:
    try:
        project = store.submit_project(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/leader/start")
async def start_leader_chat(project_id: str) -> dict:
    try:
        project = store.start_leader_chat(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/leader/restart")
async def restart_leader_chat(project_id: str) -> dict:
    try:
        store.clear_leader_runtime(project_id, "Leader chat was manually restarted from the web UI.")
        project = store.start_leader_chat(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.get("/api/projects/{project_id}/leader-console")
async def get_leader_console(project_id: str) -> dict:
    try:
        project = store.project_detail(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")

    target = project.get("leader_tmux_target") or ""
    if not target:
        return {"available": False, "output": "", "target": "", "status": "Leader tmux target not available"}

    result = subprocess.run(
        ["tmux", "capture-pane", "-pt", target, "-S", "-120"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Failed to capture tmux pane for project=%s target=%s", project_id, target)
        reason = result.stderr.strip() or "Failed to capture tmux pane"
        if "no server running" in reason.lower() or "failed to connect" in reason.lower() or "operation not permitted" in reason.lower():
            store.clear_leader_runtime(
                project_id,
                "Leader tmux session is no longer available. Send a new message to restart Codex.",
            )
        return {
            "available": False,
            "output": reason,
            "target": "",
            "status": "Leader tmux target unavailable",
        }

    logger.info("Leader console snapshot requested project=%s target=%s", project_id, target)
    return {
        "available": True,
        "output": result.stdout,
        "target": target,
        "status": "ok",
    }


@app.post("/api/projects/{project_id}/leader-console/send")
async def send_leader_console_input(project_id: str, payload: ConsoleInputRequest) -> dict:
    try:
        project = store.project_detail(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")

    target = project.get("leader_tmux_target") or ""
    if not target:
        logger.info("Auto-starting leader chat before console input project=%s", project_id)
        try:
            project = store.start_leader_chat(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Project not found")
        target = project.leader_tmux_target
    if not target:
        raise HTTPException(status_code=400, detail="Leader tmux target not available")

    content = payload.content.rstrip("\n")
    if not content:
        raise HTTPException(status_code=400, detail="Input cannot be empty")

    try:
        _send_to_tmux_target(project_id, target, content, buffer_prefix="console")
    except HTTPException as exc:
        logger.warning("Console input failed project=%s target=%s detail=%s", project_id, target, exc.detail)
        store.clear_leader_runtime(
            project_id,
            "Leader tmux session went away while sending console input. Restarting leader chat.",
        )
        project = store.start_leader_chat(project_id)
        target = project.leader_tmux_target
        if not target:
            raise exc
        _send_to_tmux_target(project_id, target, content, buffer_prefix="console")
    store.add_message(project_id, "human", f"[console] {content}", recipient=project.get("leader_agent_name") or "leader")
    logger.info("Sent manual console input project=%s target=%s", project_id, target)
    return {"ok": True}


@app.post("/api/projects/{project_id}/messages")
async def add_message(project_id: str, payload: MessageCreate) -> dict:
    try:
        project = store.get_project(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.sender == "human" and payload.recipient == "leader" and not project.leader_tmux_target:
        logger.info("Auto-starting leader chat before thread message project=%s", project_id)
        project = store.start_leader_chat(project_id)
    store.add_message(project_id, payload.sender, payload.content, recipient=payload.recipient)
    if payload.sender == "human" and payload.recipient == "leader":
        target = project.leader_tmux_target
        if target:
            tmux_message = (
                "Human posted a new thread comment. Reply in the shared thread, not only in the terminal.\n\n"
                f"{payload.content}"
            )
            try:
                _send_to_tmux_target(project_id, target, tmux_message, buffer_prefix="thread")
            except HTTPException as exc:
                logger.warning("Thread forward failed project=%s target=%s detail=%s", project_id, target, exc.detail)
                store.clear_leader_runtime(
                    project_id,
                    "Leader tmux session went away. Restarting leader chat and retrying the message.",
                )
                project = store.start_leader_chat(project_id)
                target = project.leader_tmux_target
                if not target:
                    raise exc
                _send_to_tmux_target(project_id, target, tmux_message, buffer_prefix="thread")
            logger.info("Forwarded human thread message to leader tmux project=%s target=%s", project_id, target)
        else:
            logger.info("Leader tmux unavailable for human thread message project=%s", project_id)
    return {"ok": True}


@app.post("/api/projects/{project_id}/docs")
async def add_doc(project_id: str, payload: ArtifactCreate) -> dict:
    try:
        project = store.add_artifact(project_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/agents/{role}/heartbeat")
async def heartbeat(project_id: str, role: str, event: str = "") -> dict:
    try:
        project = store.heartbeat(project_id, role, event=event)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/tasks/{task_id}/complete")
async def complete_task(project_id: str, task_id: str, payload: TaskCompleteRequest, role: str) -> dict:
    try:
        project = store.complete_task(project_id, task_id, role, payload.summary, payload.artifacts)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/review/approve")
async def approve_review(project_id: str, payload: ReviewRequest) -> dict:
    try:
        project = store.approve_review(project_id, payload.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}


@app.post("/api/projects/{project_id}/review/requeue")
async def requeue_review(project_id: str, payload: ReviewRequest) -> dict:
    try:
        project = store.send_back_to_todo(project_id, payload.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project": project.model_dump(mode="json")}
