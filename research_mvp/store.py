from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from research_mvp.models import (
    AgentRole,
    AgentSnapshot,
    AgentStatus,
    Artifact,
    ArtifactCreate,
    BoardStage,
    ProjectCreate,
    ProjectRecord,
    now_iso,
)
from research_mvp.logging_utils import configure_logging
from research_mvp.local_runtime import (
    MailboxManager,
    MessageType,
    TaskStatus,
    TeamManager,
    TaskStore,
    get_backend,
    get_registry,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_ROOT = REPO_ROOT / ".research-mvp-data"
VENV_BIN = REPO_ROOT / ".venv" / "bin"

os.environ["PATH"] = str(VENV_BIN) + os.pathsep + os.environ.get("PATH", "")


TEAM_NAME = "ml-research-lab"
ROLE_ORDER = {
    "researcher": 0,
    "trainer": 1,
}
logger = configure_logging(DEFAULT_DATA_ROOT / "logs")


class ProjectStore:
    def __init__(self, data_root: Path | None = None):
        self.data_root = data_root or DEFAULT_DATA_ROOT
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._projects_path = self.data_root / "projects.json"
        self._lock = threading.RLock()
        self._bootstrap_team()
        logger.info("ProjectStore initialized at %s", self.data_root)

    def _bootstrap_team(self) -> None:
        team = TeamManager.get_team(TEAM_NAME)
        if not team:
            TeamManager.create_team(
                name=TEAM_NAME,
                leader_name="leader",
                leader_id="leader-core",
                description="Autonomous ML research loop",
            )

        existing = {member.name for member in TeamManager.list_members(TEAM_NAME)}
        for role in ("researcher", "trainer"):
            if role not in existing:
                TeamManager.add_member(
                    TEAM_NAME,
                    member_name=role,
                    agent_id=f"{role}-core",
                    agent_type=role,
                )

    def _load_all(self) -> list[ProjectRecord]:
        if not self._projects_path.exists():
            return []
        data = json.loads(self._projects_path.read_text(encoding="utf-8"))
        return [ProjectRecord.model_validate(item) for item in data]

    def _save_all(self, projects: list[ProjectRecord]) -> None:
        payload = [project.model_dump(mode="json") for project in projects]
        self._projects_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_projects(self) -> list[ProjectRecord]:
        with self._lock:
            return [self._hydrate_runtime_fields(project) for project in self._load_all()]

    def get_project(self, project_id: str) -> ProjectRecord:
        with self._lock:
            for project in self._load_all():
                if project.id == project_id:
                    return self._hydrate_runtime_fields(project)
        raise KeyError(project_id)

    def create_project(self, request: ProjectCreate) -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = ProjectRecord(
                id=uuid.uuid4().hex[:8],
                title=request.title,
                description=request.description,
                acceptance_criteria=request.acceptance_criteria,
                max_rounds=max(1, request.max_rounds),
                agents=self._default_agents(),
            )
            projects.insert(0, project)
            self._save_all(projects)
        logger.info("Created project %s title=%s", project.id, project.title)
        self.add_message(project.id, "leader", f"Project created: {project.title}")
        return project

    def submit_project(self, project_id: str) -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            if project.stage != BoardStage.todo:
                return project
            spawn = self._spawn_leader_for_project(project)
            if not spawn["ok"]:
                logger.warning("Leader spawn failed for %s: %s", project.id, spawn["message"])
                project.attention_required = True
                project.leader_spawn_status = spawn["message"]
                project.updated_at = now_iso()
                self._save_all(projects)
                self.add_message(project.id, "system", spawn["message"], recipient="leader")
                return project
            project.stage = BoardStage.agent_working
            project.submitted_at = now_iso()
            project.current_round = 1
            project.updated_at = now_iso()
            project.review_status = "pending"
            project.attention_required = False
            project.leader_agent_name = spawn["agent_name"]
            project.leader_tmux_target = spawn["tmux_target"]
            project.leader_prompt_path = spawn["prompt_path"]
            project.leader_spawn_status = spawn["message"]
            self._create_round_tasks(project, 1)
            self._save_all(projects)
        logger.info(
            "Submitted project %s stage=%s leader_target=%s",
            project.id,
            project.stage,
            project.leader_tmux_target,
        )
        self.add_message(
            project_id,
            "leader",
            "Submission accepted. Codex leader launched in tmux and baseline planning starts now under the repository's current baseline layout.",
        )
        return self.get_project(project_id)

    def start_leader_chat(self, project_id: str) -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            project = self._hydrate_runtime_fields(project)
            if project.leader_tmux_target:
                logger.info(
                    "Leader chat already active project=%s target=%s",
                    project.id,
                    project.leader_tmux_target,
                )
                return project
            spawn = self._spawn_leader_for_project(project)
            if not spawn["ok"]:
                logger.warning("Leader chat spawn failed for %s: %s", project.id, spawn["message"])
                project.attention_required = True
                project.leader_spawn_status = spawn["message"]
                project.updated_at = now_iso()
                self._save_all(projects)
                self.add_message(project.id, "system", spawn["message"], recipient="leader")
                return project
            project.leader_agent_name = spawn["agent_name"]
            project.leader_tmux_target = spawn["tmux_target"]
            project.leader_prompt_path = spawn["prompt_path"]
            project.leader_spawn_status = spawn["message"]
            project.updated_at = now_iso()
            self._save_all(projects)
        logger.info(
            "Started leader chat project=%s stage=%s target=%s",
            project.id,
            project.stage,
            project.leader_tmux_target,
        )
        self.add_message(
            project_id,
            "system",
            "Leader chat launched in tmux. Use the console pane for direct Codex conversation.",
            recipient=project.leader_agent_name or "leader",
        )
        return self.get_project(project_id)

    def clear_leader_runtime(self, project_id: str, reason: str = "") -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            project.leader_tmux_target = ""
            project.attention_required = True
            if reason:
                project.leader_spawn_status = reason
            project.updated_at = now_iso()
            self._save_all(projects)
        logger.warning("Cleared stale leader runtime project=%s reason=%s", project_id, reason or "n/a")
        if reason:
            self.add_message(project_id, "system", reason, recipient=project.leader_agent_name or "leader")
        return self.get_project(project_id)

    def approve_review(self, project_id: str, note: str = "") -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            project.review_status = "approved"
            if note:
                project.leader_summary = (project.leader_summary + "\n\nHuman note: " + note).strip()
            project.updated_at = now_iso()
            self._save_all(projects)
        self.add_message(project_id, "human", "Human approved the review result.")
        return self.get_project(project_id)

    def send_back_to_todo(self, project_id: str, note: str = "") -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            project.stage = BoardStage.todo
            project.attention_required = False
            project.review_status = "requeued"
            if note:
                project.leader_summary = (project.leader_summary + "\n\nRequeue note: " + note).strip()
            project.updated_at = now_iso()
            self._save_all(projects)
        self.add_message(project_id, "human", "Returned project to TODO for another pass.")
        return self.get_project(project_id)

    def add_artifact(self, project_id: str, artifact: ArtifactCreate) -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            project.docs.insert(
                0,
                Artifact(
                    id=uuid.uuid4().hex[:8],
                    label=artifact.label,
                    url=artifact.url,
                    kind=artifact.kind,
                    added_by=artifact.added_by,
                ),
            )
            project.updated_at = now_iso()
            self._save_all(projects)
        self.add_message(project_id, artifact.added_by, f"Added {artifact.kind} link: {artifact.label}")
        return self.get_project(project_id)

    def add_message(
        self,
        project_id: str,
        sender: str,
        content: str,
        recipient: str = "leader",
        msg_type: MessageType = MessageType.message,
    ) -> None:
        logger.info("Thread message project=%s sender=%s recipient=%s", project_id, sender, recipient)
        try:
            project = self.get_project(project_id)
        except KeyError:
            project = None
        if (
            project
            and sender == "human"
            and recipient == "leader"
            and not project.leader_tmux_target
        ):
            logger.warning(
                "Human sent leader-thread message without active leader chat project=%s stage=%s",
                project_id,
                project.stage,
            )
        mailbox = MailboxManager(TEAM_NAME)
        mailbox.send(
            from_agent=sender,
            to=recipient,
            content=content,
            msg_type=msg_type,
            key=project_id,
        )
        self._touch_agent(sender, project_id, content)

    def heartbeat(self, project_id: str, role: str, event: str = "") -> ProjectRecord:
        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            agent = project.agents.setdefault(role, AgentSnapshot(role=AgentRole(role)))
            agent.last_heartbeat = now_iso()
            if event:
                agent.last_event = event
            if agent.status in {AgentStatus.idle, AgentStatus.waiting}:
                agent.status = AgentStatus.running
            project.updated_at = now_iso()
            self._save_all(projects)
        logger.info("Heartbeat project=%s role=%s event=%s", project_id, role, event)
        return self.get_project(project_id)

    def complete_task(
        self,
        project_id: str,
        task_id: str,
        role: str,
        summary: str = "",
        artifacts: list[ArtifactCreate] | None = None,
    ) -> ProjectRecord:
        store = TaskStore(TEAM_NAME)
        metadata: dict[str, Any] = {}
        if summary:
            metadata["summary"] = summary
        if artifacts:
            metadata["artifacts"] = [artifact.model_dump(mode="json") for artifact in artifacts]
        store.update(
            task_id,
            status=TaskStatus.completed,
            metadata=metadata,
            caller=role,
            force=True,
        )
        for artifact in artifacts or []:
            self.add_artifact(project_id, artifact)
        self.add_message(project_id, role, summary or f"{role} completed task {task_id}.")
        logger.info("Completed task project=%s task=%s role=%s", project_id, task_id, role)

        with self._lock:
            projects = self._load_all()
            project = self._find_project(projects, project_id)
            if role in project.agents:
                project.agents[role].status = AgentStatus.idle
                project.agents[role].current_task_id = ""
                project.agents[role].last_heartbeat = now_iso()
            project.updated_at = now_iso()
            self._save_all(projects)
        return self.get_project(project_id)

    def state(self) -> dict[str, Any]:
        projects = []
        for project in self.list_projects():
            tasks = self.project_tasks(project.id)
            messages = self.project_messages(project.id)
            projects.append(
                {
                    **project.model_dump(mode="json"),
                    "tasks": tasks,
                    "messages": messages[:60],
                }
            )
        return {
            "team": TEAM_NAME,
            "projects": projects,
            "generated_at": now_iso(),
        }

    def project_detail(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        return {
            **project.model_dump(mode="json"),
            "tasks": self.project_tasks(project_id),
            "messages": self.project_messages(project_id),
        }

    def project_tasks(self, project_id: str) -> list[dict[str, Any]]:
        store = TaskStore(TEAM_NAME)
        tasks = []
        for task in store.list_tasks():
            if task.metadata.get("project_id") != project_id:
                continue
            task_data = task.model_dump(mode="json", by_alias=True)
            task_data["role"] = task.metadata.get("role", "")
            task_data["round"] = task.metadata.get("round", 0)
            tasks.append(task_data)
        tasks.sort(key=lambda item: (item["round"], ROLE_ORDER.get(item["role"], 99), item["createdAt"]))
        return tasks

    def project_messages(self, project_id: str) -> list[dict[str, Any]]:
        mailbox = MailboxManager(TEAM_NAME)
        messages = []
        for message in mailbox.get_event_log(limit=300):
            data = message.model_dump(mode="json", by_alias=True, exclude_none=True)
            if data.get("key") == project_id:
                messages.append(data)
        return messages

    def tick(self, idle_timeout_seconds: int = 45) -> None:
        with self._lock:
            projects = self._load_all()
            changed = False

            for project in projects:
                if project.stage != BoardStage.agent_working:
                    continue

                tasks = self.project_tasks(project.id)
                active = next((task for task in tasks if task["status"] == TaskStatus.in_progress.value), None)

                if active:
                    role = active.get("role", "")
                    agent = project.agents.get(role)
                    if agent and self._is_stale(agent.last_heartbeat, idle_timeout_seconds):
                        logger.info(
                            "Idle timeout project=%s role=%s task=%s",
                            project.id,
                            role,
                            active.get("id"),
                        )
                        changed = self._handle_idle_intervention(project, active, agent) or changed
                    continue

                pending = next((task for task in tasks if task["status"] == TaskStatus.pending.value), None)
                if pending:
                    logger.info("Dispatch pending task project=%s task=%s", project.id, pending.get("id"))
                    self._start_task(project, pending)
                    changed = True
                    continue

                if tasks:
                    completed_round = max(task["round"] for task in tasks)
                    trainer_done = any(
                        task["round"] == completed_round
                        and task["role"] == "trainer"
                        and task["status"] == TaskStatus.completed.value
                        for task in tasks
                    )
                    if trainer_done and completed_round < project.max_rounds:
                        project.current_round = completed_round + 1
                        self._create_round_tasks(project, project.current_round)
                        changed = True
                        self.add_message(
                            project.id,
                            "leader",
                            f"Round {completed_round} summarized. Launching round {project.current_round}.",
                        )
                    elif trainer_done:
                        project.stage = BoardStage.human_review
                        project.review_status = "needs_confirmation"
                        project.attention_required = False
                        project.leader_summary = self._build_leader_summary(project.id, tasks)
                        self._set_all_agents_idle(project)
                        changed = True
                        self.add_message(
                            project.id,
                            "leader",
                            "Trainer closed the final round. Moving project to Human Review.",
                        )

            if changed:
                for project in projects:
                    project.updated_at = now_iso()
                self._save_all(projects)

    def _start_task(self, project: ProjectRecord, task_data: dict[str, Any]) -> None:
        store = TaskStore(TEAM_NAME)
        role = task_data.get("role", "")
        store.update(
            task_data["id"],
            status=TaskStatus.in_progress,
            owner=role,
            caller=role,
            force=True,
        )
        for name, agent in project.agents.items():
            if name == role:
                agent.status = AgentStatus.running
                agent.current_task_id = task_data["id"]
                agent.last_heartbeat = now_iso()
                agent.last_event = f"Started round {task_data.get('round')} task"
            elif name != AgentRole.leader.value:
                agent.status = AgentStatus.waiting
                agent.current_task_id = ""
        project.agents["leader"].status = AgentStatus.running
        project.attention_required = False
        self.add_message(
            project.id,
            "leader",
            f"Dispatching {role} for round {task_data.get('round')}: {task_data.get('subject')}.",
            recipient=role,
        )
        logger.info("Started task project=%s role=%s task=%s", project.id, role, task_data["id"])

    def _handle_idle_intervention(
        self,
        project: ProjectRecord,
        active_task: dict[str, Any],
        agent: AgentSnapshot,
    ) -> bool:
        if agent.status == AgentStatus.intervening:
            return False

        task_id = active_task["id"]
        if active_task["metadata"].get("intervened"):
            return False

        content = f"{agent.role.value} has gone idle. Leader is checking whether the task is complete."
        self.add_message(project.id, "leader", content)

        if self._has_done_signal(project.id, agent.role.value):
            store = TaskStore(TEAM_NAME)
            metadata = dict(active_task["metadata"])
            metadata["intervened"] = now_iso()
            metadata["summary"] = metadata.get("summary", "Leader inferred completion after idle timeout.")
            store.update(task_id, status=TaskStatus.completed, metadata=metadata, caller="leader", force=True)
            agent.status = AgentStatus.idle
            agent.current_task_id = ""
            project.attention_required = False
            self.add_message(project.id, "leader", f"Inferred completion for {agent.role.value} after timeout.")
            logger.info("Inferred completion project=%s role=%s", project.id, agent.role.value)
        else:
            store = TaskStore(TEAM_NAME)
            metadata = dict(active_task["metadata"])
            metadata["intervened"] = now_iso()
            store.update(task_id, metadata=metadata, caller="leader", force=True)
            agent.status = AgentStatus.intervening
            agent.last_event = "Leader intervention requested"
            project.attention_required = True
            logger.warning("Leader intervention requested project=%s role=%s", project.id, agent.role.value)
        return True

    def _has_done_signal(self, project_id: str, role: str) -> bool:
        messages = self.project_messages(project_id)[:8]
        keywords = ("done", "completed", "finished", "ready for review")
        for message in messages:
            if message.get("from") != role:
                continue
            content = (message.get("content") or "").lower()
            if any(keyword in content for keyword in keywords):
                return True
        return False

    def _build_leader_summary(self, project_id: str, tasks: list[dict[str, Any]]) -> str:
        trainer_summary = ""
        for task in reversed(tasks):
            if task.get("role") == "trainer":
                trainer_summary = task.get("metadata", {}).get("summary", "")
                break
        return trainer_summary or f"Project {project_id} completed all configured rounds and is ready for review."

    def _set_all_agents_idle(self, project: ProjectRecord) -> None:
        for agent in project.agents.values():
            agent.status = AgentStatus.idle
            agent.current_task_id = ""
            agent.last_heartbeat = now_iso()

    def _create_round_tasks(self, project: ProjectRecord, round_number: int) -> None:
        store = TaskStore(TEAM_NAME)
        research = store.create(
            subject=f"Round {round_number}: design experiment and baseline_v{round_number}",
            description="Researcher proposes improvement ideas and prepares trainable code.",
            owner="researcher",
            metadata={"project_id": project.id, "role": "researcher", "round": round_number},
        )
        trainer = store.create(
            subject=f"Round {round_number}: run training queue",
            description="Trainer waits for research output, then executes the training plan.",
            owner="trainer",
            blocked_by=[research.id],
            metadata={"project_id": project.id, "role": "trainer", "round": round_number},
        )
        project.task_ids.extend([research.id, trainer.id])
        project.agents = project.agents or self._default_agents()

    def _hydrate_runtime_fields(self, project: ProjectRecord) -> ProjectRecord:
        if project.leader_agent_name and project.leader_tmux_target and project.leader_prompt_path:
            return project

        agent_name = project.leader_agent_name or f"leader-{project.id}"
        registry = get_registry(TEAM_NAME)
        info = registry.get(agent_name, {})
        prompt_path = self.data_root / "prompts" / f"leader-{project.id}.md"

        project.leader_agent_name = agent_name if info or prompt_path.exists() else project.leader_agent_name
        project.leader_tmux_target = project.leader_tmux_target or info.get("tmux_target", "")
        project.leader_prompt_path = project.leader_prompt_path or (str(prompt_path) if prompt_path.exists() else "")
        if not project.leader_spawn_status and info:
            target = info.get("tmux_target", "")
            if target:
                project.leader_spawn_status = f"Agent '{agent_name}' spawned in tmux ({target})"
        return project

    def _spawn_leader_for_project(self, project: ProjectRecord) -> dict[str, str | bool]:
        prompts_dir = self.data_root / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = prompts_dir / f"leader-{project.id}.md"

        prompt_path.write_text(self._build_leader_prompt(project), encoding="utf-8")

        agent_name = f"leader-{project.id}"
        existing = {member.name for member in TeamManager.list_members(TEAM_NAME)}
        if agent_name not in existing:
            TeamManager.add_member(
                TEAM_NAME,
                member_name=agent_name,
                agent_id=f"{agent_name}-core",
                agent_type="leader",
            )

        backend = get_backend("tmux")
        spawn_message = backend.spawn(
            command=["codex"],
            agent_name=agent_name,
            agent_id=f"{agent_name}-runtime",
            agent_type="leader",
            team_name=TEAM_NAME,
            prompt=prompt_path.read_text(encoding="utf-8"),
            cwd=str(REPO_ROOT),
            env={
                "PROJECT_ID": project.id,
                "RESEARCH_BOARD_URL": f"http://127.0.0.1:8090/projects/{project.id}",
                "RESEARCH_MVP_PROJECT_ID": project.id,
            },
            skip_permissions=False,
        )

        registry = get_registry(TEAM_NAME)
        tmux_target = registry.get(agent_name, {}).get("tmux_target", "")
        ok = not spawn_message.startswith("Error")
        logger.info(
            "Spawn leader project=%s ok=%s agent=%s target=%s message=%s",
            project.id,
            ok,
            agent_name,
            tmux_target,
            spawn_message,
        )
        return {
            "ok": ok,
            "message": spawn_message,
            "agent_name": agent_name,
            "tmux_target": tmux_target,
            "prompt_path": str(prompt_path),
        }

    def _build_leader_prompt(self, project: ProjectRecord) -> str:
        thread = self.project_messages(project.id)
        discussion = "\n".join(
            f"- [{msg.get('timestamp', '')}] {msg.get('from', '?')} -> {msg.get('to', 'leader')}: {msg.get('content', '')}"
            for msg in reversed(thread[-40:])
        ) or "- No prior discussion"

        return f"""You are the agent leader for an autonomous ML research project.

Project:
- ID: {project.id}
- Title: {project.title}
- Acceptance criteria: {project.acceptance_criteria or "n/a"}
- Board URL: http://127.0.0.1:8090/projects/{project.id}

Current TODO-thread discussion:
{discussion}

Your job:
1. Continue the human discussion from the thread context above.
2. Keep the shared thread updated with clear progress notes for human, researcher, and trainer.
3. When the task is ready, propose the next concrete execution plan for the built-in researcher -> trainer loop.
4. If you are blocked, report the blocker into the shared thread instead of going silent.

Operational notes:
- Repository root: {REPO_ROOT}
- Team name: {TEAM_NAME}
- Your runtime agent name: leader-{project.id}
- This MVP does not depend on ClawTeam. Use the shared thread and the board state shown in the web UI.

Thread-first behavior:
- Before doing anything else, summarize the current plan back into the shared thread.
- Treat the TODO thread as the planning room.
- Once active execution starts, continue logging key decisions and handoffs into the same thread.
"""

    def _default_agents(self) -> dict[str, AgentSnapshot]:
        return {
            role.value: AgentSnapshot(role=role, status=AgentStatus.idle)
            for role in AgentRole
        }

    def _find_project(self, projects: list[ProjectRecord], project_id: str) -> ProjectRecord:
        for project in projects:
            if project.id == project_id:
                return project
        raise KeyError(project_id)

    def _touch_agent(self, sender: str, project_id: str, content: str) -> None:
        if sender not in {"leader", "researcher", "trainer", "human"}:
            return
        with self._lock:
            projects = self._load_all()
            try:
                project = self._find_project(projects, project_id)
            except KeyError:
                return
            if sender in project.agents:
                project.agents[sender].last_heartbeat = now_iso()
                project.agents[sender].last_event = content
                if project.agents[sender].status == AgentStatus.idle and sender != "leader":
                    project.agents[sender].status = AgentStatus.running
            project.updated_at = now_iso()
            self._save_all(projects)

    @staticmethod
    def _is_stale(last_heartbeat: str, idle_timeout_seconds: int) -> bool:
        if not last_heartbeat:
            return True
        try:
            from datetime import datetime, timezone

            heartbeat = datetime.fromisoformat(last_heartbeat)
            now = datetime.now(timezone.utc)
            return (now - heartbeat).total_seconds() > idle_timeout_seconds
        except ValueError:
            return True
