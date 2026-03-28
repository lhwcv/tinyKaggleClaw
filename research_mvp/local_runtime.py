from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_mvp.models import now_iso


class MessageType(str, Enum):
    message = "message"


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"


class TeamMember(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    agent_id: str
    agent_type: str


class TeamRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    leader_name: str
    leader_id: str
    description: str = ""
    members: list[TeamMember] = Field(default_factory=list)


class RuntimeMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    timestamp: str = Field(default_factory=now_iso)
    from_agent: str = Field(alias="from")
    to: str
    content: str
    type: str = MessageType.message.value
    key: str = ""


class RuntimeTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    subject: str
    description: str = ""
    status: str = TaskStatus.pending.value
    owner: str = ""
    blocked_by: list[str] = Field(default_factory=list, alias="blockedBy")
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: str = Field(default_factory=now_iso)
    updatedAt: str = Field(default_factory=now_iso)


class RuntimePaths:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def team_dir(self, team: str) -> Path:
        path = self.root / "teams" / team
        path.mkdir(parents=True, exist_ok=True)
        return path

    def team_file(self, team: str) -> Path:
        return self.team_dir(team) / "team.json"

    def events_dir(self, team: str) -> Path:
        path = self.team_dir(team) / "events"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def inbox_dir(self, team: str, recipient: str) -> Path:
        path = self.team_dir(team) / "inboxes" / recipient
        path.mkdir(parents=True, exist_ok=True)
        return path

    def tasks_file(self, team: str) -> Path:
        return self.team_dir(team) / "tasks.json"

    def registry_file(self, team: str) -> Path:
        return self.team_dir(team) / "spawn_registry.json"


_ROOT = RuntimePaths(Path(os.environ.get("RESEARCH_MVP_RUNTIME_DIR", "")) if os.environ.get("RESEARCH_MVP_RUNTIME_DIR") else Path(__file__).resolve().parent.parent / ".research-mvp-data" / "runtime")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class TeamManager:
    @staticmethod
    def get_team(team_name: str) -> TeamRecord | None:
        path = _ROOT.team_file(team_name)
        if not path.exists():
            return None
        return TeamRecord.model_validate(_read_json(path, {}))

    @staticmethod
    def create_team(name: str, leader_name: str, leader_id: str, description: str = "") -> TeamRecord:
        team = TeamRecord(name=name, leader_name=leader_name, leader_id=leader_id, description=description)
        _write_json(_ROOT.team_file(name), team.model_dump(mode="json"))
        return team

    @staticmethod
    def list_members(team_name: str) -> list[TeamMember]:
        team = TeamManager.get_team(team_name)
        if not team:
            return []
        members = [TeamMember(name=team.leader_name, agent_id=team.leader_id, agent_type="leader")]
        members.extend(team.members)
        return members

    @staticmethod
    def add_member(team_name: str, member_name: str, agent_id: str, agent_type: str) -> TeamMember:
        team = TeamManager.get_team(team_name)
        if not team:
            raise KeyError(team_name)
        existing = {member.name for member in team.members}
        if member_name not in existing and member_name != team.leader_name:
            team.members.append(TeamMember(name=member_name, agent_id=agent_id, agent_type=agent_type))
            _write_json(_ROOT.team_file(team_name), team.model_dump(mode="json"))
        return TeamMember(name=member_name, agent_id=agent_id, agent_type=agent_type)


class MailboxManager:
    def __init__(self, team_name: str):
        self.team_name = team_name

    def send(
        self,
        *,
        from_agent: str,
        to: str,
        content: str,
        msg_type: MessageType = MessageType.message,
        key: str = "",
    ) -> RuntimeMessage:
        message = RuntimeMessage(
            id=f"msg-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            from_agent=from_agent,
            to=to,
            content=content,
            type=msg_type.value,
            key=key,
        )
        event_path = _ROOT.events_dir(self.team_name) / f"evt-{message.id}.json"
        inbox_path = _ROOT.inbox_dir(self.team_name, to) / f"{message.id}.json"
        payload = message.model_dump(mode="json", by_alias=True)
        _write_json(event_path, payload)
        _write_json(inbox_path, payload)
        return message

    def get_event_log(self, limit: int = 300) -> list[RuntimeMessage]:
        events = []
        for path in sorted(_ROOT.events_dir(self.team_name).glob("*.json"), reverse=True):
            events.append(RuntimeMessage.model_validate(_read_json(path, {})))
            if len(events) >= limit:
                break
        return events


class TaskStore:
    def __init__(self, team_name: str):
        self.team_name = team_name

    def _load(self) -> list[RuntimeTask]:
        return [RuntimeTask.model_validate(item) for item in _read_json(_ROOT.tasks_file(self.team_name), [])]

    def _save(self, tasks: list[RuntimeTask]) -> None:
        _write_json(_ROOT.tasks_file(self.team_name), [task.model_dump(mode="json", by_alias=True) for task in tasks])

    def create(
        self,
        *,
        subject: str,
        description: str = "",
        owner: str = "",
        blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeTask:
        tasks = self._load()
        task = RuntimeTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            subject=subject,
            description=description,
            owner=owner,
            blocked_by=blocked_by or [],
            metadata=metadata or {},
        )
        tasks.append(task)
        self._save(tasks)
        return task

    def update(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        owner: str | None = None,
        metadata: dict[str, Any] | None = None,
        caller: str = "",
        force: bool = False,
    ) -> RuntimeTask:
        del caller, force
        tasks = self._load()
        for idx, task in enumerate(tasks):
            if task.id != task_id:
                continue
            if status is not None:
                task.status = status.value if isinstance(status, TaskStatus) else str(status)
            if owner is not None:
                task.owner = owner
            if metadata is not None:
                task.metadata = metadata
            task.updatedAt = now_iso()
            tasks[idx] = task
            self._save(tasks)
            return task
        raise KeyError(task_id)

    def list_tasks(self) -> list[RuntimeTask]:
        tasks = self._load()
        tasks.sort(key=lambda task: task.createdAt)
        return tasks


def get_registry(team_name: str) -> dict[str, dict[str, Any]]:
    data = _read_json(_ROOT.registry_file(team_name), {})
    return data if isinstance(data, dict) else {}


def register_agent(
    *,
    team_name: str,
    agent_name: str,
    backend: str,
    tmux_target: str,
    pid: int = 0,
    command: list[str] | None = None,
) -> None:
    registry = get_registry(team_name)
    registry[agent_name] = {
        "backend": backend,
        "tmux_target": tmux_target,
        "pid": pid,
        "command": command or [],
        "updated_at": now_iso(),
    }
    _write_json(_ROOT.registry_file(team_name), registry)


class LocalTmuxBackend:
    def spawn(
        self,
        *,
        command: list[str],
        agent_name: str,
        agent_id: str,
        agent_type: str,
        team_name: str,
        prompt: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        skip_permissions: bool = False,
    ) -> str:
        del agent_id, agent_type, skip_permissions
        if not shutil.which("tmux"):
            return "Error: tmux not installed"
        if not command:
            return "Error: empty command"
        if not shutil.which(command[0]):
            return f"Error: command '{command[0]}' not found on PATH"

        session_name = f"research-mvp-{team_name}"
        target = f"{session_name}:{agent_name}"
        env_vars = dict(env or {})
        if cwd:
            env_vars.setdefault("PWD", cwd)

        final_command = list(command)
        if prompt:
            final_command.append(prompt)

        export_str = "; ".join(f"export {key}={shlex.quote(value)}" for key, value in env_vars.items())
        cmd_str = " ".join(shlex.quote(part) for part in final_command)
        if cwd:
            full_cmd = f"{export_str}; cd {shlex.quote(cwd)} && {cmd_str}" if export_str else f"cd {shlex.quote(cwd)} && {cmd_str}"
        else:
            full_cmd = f"{export_str}; {cmd_str}" if export_str else cmd_str

        check = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if check.returncode != 0:
            launch = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name, "-n", agent_name, full_cmd],
                capture_output=True,
                text=True,
            )
        else:
            launch = subprocess.run(
                ["tmux", "new-window", "-t", session_name, "-n", agent_name, full_cmd],
                capture_output=True,
                text=True,
            )

        if launch.returncode != 0:
            return f"Error: failed to launch tmux session: {launch.stderr.strip() or launch.stdout.strip()}"

        pid_result = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
        )
        pane_pid = 0
        if pid_result.returncode == 0 and pid_result.stdout.strip():
            try:
                pane_pid = int(pid_result.stdout.strip().splitlines()[0])
            except ValueError:
                pane_pid = 0

        register_agent(
            team_name=team_name,
            agent_name=agent_name,
            backend="tmux",
            tmux_target=target,
            pid=pane_pid,
            command=command,
        )
        return f"Agent '{agent_name}' spawned in tmux ({target})"


def get_backend(name: str = "tmux") -> LocalTmuxBackend:
    if name != "tmux":
        raise ValueError(f"Unknown backend: {name}")
    return LocalTmuxBackend()
