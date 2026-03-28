from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BoardStage(str, Enum):
    todo = "todo"
    agent_working = "agent_working"
    human_review = "human_review"


class AgentStatus(str, Enum):
    idle = "idle"
    running = "running"
    waiting = "waiting"
    intervening = "intervening"
    blocked = "blocked"


class AgentRole(str, Enum):
    leader = "leader"
    researcher = "researcher"
    trainer = "trainer"


class Artifact(BaseModel):
    id: str
    label: str
    url: str
    kind: str = "doc"
    added_by: str = "human"
    created_at: str = Field(default_factory=now_iso)


class AgentSnapshot(BaseModel):
    role: AgentRole
    status: AgentStatus = AgentStatus.idle
    last_heartbeat: str = Field(default_factory=now_iso)
    last_event: str = ""
    current_task_id: str = ""


class ProjectRecord(BaseModel):
    id: str
    title: str
    description: str = ""
    acceptance_criteria: str = ""
    stage: BoardStage = BoardStage.todo
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    submitted_at: str = ""
    current_round: int = 0
    max_rounds: int = 2
    attention_required: bool = False
    leader_summary: str = ""
    review_status: str = "pending"
    leader_agent_name: str = ""
    leader_tmux_target: str = ""
    leader_prompt_path: str = ""
    leader_spawn_status: str = ""
    docs: list[Artifact] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    agents: dict[str, AgentSnapshot] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    title: str
    description: str = ""
    acceptance_criteria: str = ""
    max_rounds: int = 2


class MessageCreate(BaseModel):
    sender: str
    content: str
    recipient: str = "leader"


class ArtifactCreate(BaseModel):
    label: str
    url: str
    kind: str = "doc"
    added_by: str = "human"


class TaskCompleteRequest(BaseModel):
    summary: str = ""
    artifacts: list[ArtifactCreate] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    note: str = ""


class ConsoleInputRequest(BaseModel):
    content: str
