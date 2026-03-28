from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_mvp.models import now_iso

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = DEFAULT_REPO_ROOT / "research_mvp" / "runtime.toml"
DEFAULT_AGENTS = ("leader", "researcher", "trainer")
DEFAULT_STALL_TIMEOUT_SECONDS = 600
DEFAULT_NUDGE_COOLDOWN_SECONDS = 300
DEFAULT_TRAIN_QUEUE_IDLE_REMINDER_SECONDS = 3600
RUNTIME_DEBUG = False
DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CODEX_COMMAND = ["codex", "-m", DEFAULT_CODEX_MODEL, "--dangerously-bypass-approvals-and-sandbox"]
DEFAULT_SUBMIT_KEYS = ["Enter", "Enter"]


@dataclass
class RuntimeConfig:
    config_path: Path
    repo_root: Path
    workdir: Path
    runtime_root: Path
    session_name: str
    codex_command: list[str]
    agents: list[str]
    env: dict[str, str]
    agent_env: dict[str, dict[str, str]]
    submit_keys: list[str]
    submit_delay_ms: int
    stall_timeout_seconds: int
    nudge_cooldown_seconds: int
    train_queue_idle_reminder_seconds: int


def debug_print(message: str) -> None:
    if RUNTIME_DEBUG:
        print(f"[debug] {message}")


def default_config_text() -> str:
    return f"""session_name = "research-runtime"
repo_root = "{DEFAULT_REPO_ROOT}"
workdir = "{DEFAULT_REPO_ROOT}"
runtime_root = "{DEFAULT_REPO_ROOT / '.research-mvp-data' / 'runtime'}"
codex_command = ["codex", "-m", "{DEFAULT_CODEX_MODEL}", "--dangerously-bypass-approvals-and-sandbox"]
agents = ["leader", "researcher", "trainer"]
submit_keys = ["Enter", "Enter"]
submit_delay_ms = 500
stall_timeout_seconds = 600
nudge_cooldown_seconds = 300
train_queue_idle_reminder_seconds = 3600

[env]
PYTHONUNBUFFERED = "1"

[agent_env.leader]

[agent_env.researcher]

[agent_env.trainer]

"""


def load_config(path: Path) -> RuntimeConfig:
    if not path.exists():
        raise SystemExit(f"config not found: {path}\nrun `rt init-config` first")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    repo_root = Path(raw.get("repo_root") or DEFAULT_REPO_ROOT).expanduser().resolve()
    workdir = Path(raw.get("workdir") or repo_root).expanduser().resolve()
    runtime_root = Path(raw.get("runtime_root") or (repo_root / ".research-mvp-data" / "runtime")).expanduser().resolve()
    codex_command = [str(part) for part in raw.get("codex_command", DEFAULT_CODEX_COMMAND)]
    agents = [str(agent) for agent in raw.get("agents", list(DEFAULT_AGENTS))]
    env = {str(key): str(value) for key, value in raw.get("env", {}).items()}
    agent_env = {
        str(agent): {str(key): str(value) for key, value in values.items()}
        for agent, values in raw.get("agent_env", {}).items()
        if isinstance(values, dict)
    }
    submit_keys = [str(key) for key in raw.get("submit_keys", DEFAULT_SUBMIT_KEYS)]
    submit_delay_ms = int(raw.get("submit_delay_ms", 250))
    stall_timeout_seconds = int(raw.get("stall_timeout_seconds", DEFAULT_STALL_TIMEOUT_SECONDS))
    nudge_cooldown_seconds = int(raw.get("nudge_cooldown_seconds", DEFAULT_NUDGE_COOLDOWN_SECONDS))
    train_queue_idle_reminder_seconds = int(
        raw.get("train_queue_idle_reminder_seconds", DEFAULT_TRAIN_QUEUE_IDLE_REMINDER_SECONDS)
    )
    return RuntimeConfig(
        config_path=path,
        repo_root=repo_root,
        workdir=workdir,
        runtime_root=runtime_root,
        session_name=str(raw.get("session_name") or "research-runtime"),
        codex_command=codex_command,
        agents=agents,
        env=env,
        agent_env=agent_env,
        submit_keys=submit_keys,
        submit_delay_ms=submit_delay_ms,
        stall_timeout_seconds=stall_timeout_seconds,
        nudge_cooldown_seconds=nudge_cooldown_seconds,
        train_queue_idle_reminder_seconds=train_queue_idle_reminder_seconds,
    )


def runtime_dirs(cfg: RuntimeConfig) -> dict[str, Path]:
    root = cfg.runtime_root
    paths = {
        "root": root,
        "agents": root / "agents",
        "inbox": root / "inbox",
        "logs": root / "logs",
        "state": root / "state.json",
        "thread": root / "thread.jsonl",
        "tasks": root / "tasks.json",
    }
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["agents"].mkdir(parents=True, exist_ok=True)
    paths["inbox"].mkdir(parents=True, exist_ok=True)
    paths["logs"].mkdir(parents=True, exist_ok=True)
    for agent in cfg.agents:
        (paths["inbox"] / agent).mkdir(parents=True, exist_ok=True)
    return paths


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def append_jsonl(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        for line in handle:
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                rows.append(json.loads(line))
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if limit is not None:
        return rows[-limit:]
    return rows


def parse_iso8601(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def iso_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def iso_after(seconds: int) -> str:
    return (iso_now_dt() + timedelta(seconds=seconds)).isoformat()


def inbox_files(cfg: RuntimeConfig, agent: str) -> list[Path]:
    return sorted(
        path
        for path in (runtime_dirs(cfg)["inbox"] / agent).glob("*.json")
        if not path.name.endswith(".corrupt.json")
    )


def agent_target(cfg: RuntimeConfig, agent: str) -> str:
    return f"{cfg.session_name}:{agent}"


def ensure_runtime_layout(cfg: RuntimeConfig) -> None:
    paths = runtime_dirs(cfg)
    state = read_json(paths["state"], {})
    if not state:
        state = {
            "session_name": cfg.session_name,
            "config_path": str(cfg.config_path),
            "workdir": str(cfg.workdir),
            "runtime_root": str(cfg.runtime_root),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "agents": {},
        }
    for agent in cfg.agents:
        state["agents"].setdefault(
            agent,
            {
                "name": agent,
                "target": agent_target(cfg, agent),
                "status": "offline",
                "last_seen_at": "",
                "last_prompt_at": "",
                "last_message_at": "",
            },
        )
        agent_path = paths["agents"] / f"{agent}.json"
        if not agent_path.exists():
            write_json(
                agent_path,
                {
                    "name": agent,
                    "target": agent_target(cfg, agent),
                    "status": "offline",
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "last_event": "",
                },
            )
    state["updated_at"] = now_iso()
    write_json(paths["state"], state)
    if not paths["tasks"].exists():
        write_json(paths["tasks"], {"tasks": [], "updated_at": now_iso()})


def require_tmux() -> None:
    if not shutil.which("tmux"):
        raise SystemExit("tmux is not installed")


def require_command(cmd: str) -> None:
    if not shutil.which(cmd):
        raise SystemExit(f"command not found on PATH: {cmd}")


def tmux_run(args: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["tmux", *args], text=True, capture_output=capture)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "tmux command failed"
        raise RuntimeError(detail)
    return result


def session_exists(cfg: RuntimeConfig) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", cfg.session_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def agent_bootstrap_prompt(cfg: RuntimeConfig, agent: str) -> str:
    cli_cmd = f"python -m research_mvp.runtime_cli --config {cfg.config_path}"
    agents_md = cfg.repo_root / "AGENTS.md"
    skill_md = cfg.repo_root / "research_mvp" / "skills" / "runtime-communication" / "SKILL.md"
    identity_md = cfg.repo_root / "research_mvp" / "identities" / f"{agent}.md"
    shared = f"""You are the {agent} agent in a three-agent ML engineering runtime.

Runtime rules:
- You are running inside tmux session `{cfg.session_name}`.
- Stay alive in this terminal. Do not exit unless explicitly told.
- Keep replies concise and operational.
- Repository root: {cfg.repo_root}
- Working directory: {cfg.workdir}
- Shared runtime directory: {cfg.runtime_root}
- Shared thread log: {cfg.runtime_root / "thread.jsonl"}
- Your inbox directory: {cfg.runtime_root / "inbox" / agent}
- Your state file: {cfg.runtime_root / "agents" / f"{agent}.json"}
- Runtime CLI command: {cli_cmd}
- Treat the shared runtime directory as control-plane state only. Do not write experiment outputs, checkpoints, caches, reports, or training artifacts there.
- Default experiment outputs should go under `{cfg.workdir / "output"}` with per-version subdirectories like `output/baseline_v11/`.
- Read these files before acting:
  - {agents_md}
  - {skill_md}
  - {identity_md}
- If the human request is to start a task under `recipe/<name>/`, first read `recipe/<name>/data.md`, `recipe/<name>/overview.md`, and `recipe/<name>/start_prompt.md`.
- Treat `recipe/<name>/` tasks as Kaggle-style competition tasks by default unless the recipe clearly says otherwise.
- For a new `recipe/<name>/` task, do EDA first. Put EDA scripts, notes, and charts under `eda/`, then only begin baseline and training iteration after the competition setup, metric, submission format, and main risks are well understood.
- Do not hand-edit `thread.jsonl`.
- If you need one specific agent to receive a message, use `{cli_cmd} delegate --from <sender> --to <recipient> "..."` so the message lands in both the shared thread and the target inbox.
- Use shared-thread updates for visibility and `all` broadcasts, not as a substitute for directed inbox delivery.
- When you complete meaningful work, send the update through the runtime CLI rather than by manually appending JSON.
- If blocked, report the blocker through the runtime CLI instead of going silent.
"""
    role_specific = {
        "leader": """Role:
- Act as the orchestrator.
- Read human messages from the shared thread and your inbox.
- Check researcher and trainer progress regularly.
- Decide who should act next and communicate through the shared thread or inbox files.
- You are responsible for keeping the system moving without waiting for manual nudges.
- Before planning, re-check the role boundaries in the three identity files so you delegate according to each agent’s scope.
- Treat the team as a machine-learning baseline team. Default iteration should move through repository-style versions such as `baseline_v10`, `baseline_v11`, `baseline_v12`...
- If the human starts a `recipe/<name>/` task, make the first phase about recipe understanding and EDA rather than immediate model iteration.
- When planning a new version, prefer `2-3` experiment variants under one versioned baseline package such as `baseline/experiments_v11/` rather than a single isolated run.
- Every 5 baseline versions, such as `baseline_v5`, `baseline_v10`, or `baseline_v15`, pause for a deliberate comparison between the team’s current path and reference solutions or newly researched alternatives.
- Use the working-directory layout consistently: code in `src/baseline/`, experiment scripts and configs in `baseline/`, data in `data/`, outputs in `output/`.
- Use `docs/` for experiment design notes and result summaries.
- If training is required, first get a versioned package from researcher, typically `baseline/experiments_v11/` plus a matching formal runner like `baseline/run_experiments_v11.sh` and output target `output/baseline_v11/`.
- Prefer GPU training whenever a GPU is available. Training assumptions should be GPU-first, with CPU as a fallback only when the environment truly has no usable GPU.
- Expect each version to contain one formal runner under `baseline/` that fans out into multiple experiments by calling `python baseline/run_baseline.py --config ...`, which then executes `python -m src.baseline.train`.
- After submitting a training job, wait at least 1 second before querying queue or status again.
- By default, expect training code to emit intermediate logs. Unless the human explicitly asks for denser logging, require at least one meaningful progress log per epoch before approving a training package.
- Also require a clear startup log from `src/baseline/train.py` so humans and agents can detect that training actually began.
- Trainer is not allowed to run full training in tmux, and should not own dry runs by default. Researcher should perform the minimal dry run first, then trainer handles queue submission.
- Default behavior is continuous iteration. Finishing one experiment version, writing a result summary, or making a git commit does not mean the overall task is done.
- After each version closeout, immediately choose the next action: delegate the next experiment version, request a targeted follow-up, or ask the human a blocking decision. Do not stop on a bare summary.
- On every 5-version boundary, explicitly summarize what differs from reference solutions, what might be worth borrowing, and which missing ideas should be tested next.
- On every 5-version boundary, turn the most credible borrowable ideas into concrete next experiments instead of leaving them as abstract observations.
- Only announce full task completion when the human explicitly asked for a single-version stop, or when acceptance criteria are fully satisfied and you have clearly stated why further iteration is unnecessary.

Delegation protocol:
- Do not rely only on `leader -> all` when you want work to happen.
- When assigning work, send one direct inbox message per target agent with the runtime CLI.
- Use this exact pattern for delegation:
  `<runtime-cli> delegate --from leader --to researcher "..."`,
  `<runtime-cli> delegate --from leader --to trainer "..."`,
- After queueing direct messages, add one shared thread summary for humans and other agents.
- Shared thread summaries are required for visibility, but they are not a substitute for direct inbox delegation.
- When one experiment version is complete and worth preserving, make a git commit covering the relevant `src/` and `scripts/` changes.

Control-plane restrictions:
- Do not run `<runtime-cli> up`, `<runtime-cli> attach`, or `<runtime-cli> supervise` from inside the runtime.
- Do not use `<runtime-cli> status` for routine planning; it may be stale or sandbox-blocked.
- Do not try to repair tmux or restart the runtime unless the human explicitly asks.
""",
        "researcher": """Role:
- Produce plans, code changes, training configs, scripts, experiment designs, implementation guidance, and minimal dry-run validation.
- For `recipe/<name>/` tasks, begin with recipe reading and EDA before proposing baseline iterations.
- Report results back for leader review.

Inbox behavior:
- Treat direct inbox messages as executable assignments.
- Organize training work by experiment version, e.g. `baseline_v11`, `baseline_v12`, while keeping the workspace layout clean: code in `src/baseline/`, scripts/configs in `baseline/`, data in `data/`, outputs in `output/`.
- Prefer GPU-first training assumptions. If a GPU is available, training code and configs should use it by default, and CPU should only be the fallback path.
- Versioned experiment configs should usually live under `baseline/experiments_v11/`, with matching outputs under `output/baseline_v11/`.
- Keep one formal version runner script per version under `baseline/`; it should run multiple experiments by calling `python baseline/run_baseline.py --config ...` multiple times.
- Put experiment outputs under the working directory, typically `output/baseline_v11/`, not under the shared runtime directory.
- Make training implementations observable by default. `train.py` should emit intermediate logs; unless the human explicitly asks for denser logging, at least one meaningful progress log per epoch is the default minimum.
- Ensure `src/baseline/train.py` emits a clear startup log before the training loop so the system can detect that training truly started.
- Own the minimal dry run for new training code. That dry run should validate startup and wiring without drifting into real training.
- After designing a version, write the design note to `docs/` using the repository’s existing baseline pattern, such as `docs/baseline_v11_1_exp.md`.
- After finishing a meaningful chunk, report back to leader by default with `<runtime-cli> delegate --from researcher --to leader "..."`. Use `all` only for shared milestones.
- Do not perform runtime control-plane operations unless the human explicitly asks.
""",
        "trainer": """Role:
- Submit training scripts to train_service and handle returned results.
- Submit formal training jobs to an external train_service instead of keeping long-running jobs inside tmux.
- Prefer queueing GPU-backed training jobs when the environment supports them. If the workload can use GPU, do not default to CPU without a reason.
- Record metrics, failures, artifacts, and returned job results clearly.
- Do not submit training while a `recipe/<name>/` task is still in the recipe-reading or EDA phase.
- After queueing a formal training job, do not draft or publish the final report until the result callback has actually arrived.

Inbox behavior:
- Treat direct inbox messages as executable assignments.
- After finishing a meaningful chunk, report back to leader by default. Use `all` only for shared milestones.
- Do not modify researcher-owned training code, configs, or scripts. If they are wrong, report the issue to leader and let leader send the fix back to researcher.
- Default formal submission target is a real script file under `baseline/`, typically `baseline/run_experiments_v11.sh`; it may call `python baseline/run_baseline.py --config ...` multiple times for different yaml configs.
- Training outputs should land under the working directory, typically `output/baseline_v11/`, not in the shared runtime directory.
- Do not run local dry runs by default. Expect researcher to complete the minimal dry run and hand you a queue-ready package.
- If the package is queue-ready, submit the formal run script to train_service unless the leader explicitly told you not to.
- After results come back from train_service, write the version result summary to `docs/` using the matching result-note pattern, such as `docs/baseline_v11_1_exp_result.md`.
- When writing the result summary, follow the general style of `docs/baseline_v11_1_exp_result.md`: lead with a one-line conclusion, then use Markdown tables for key result comparisons instead of only prose.
- If multiple experiments, folds, or configs are involved, include a compact result table, but choose the columns based on the current task instead of hard-coding one project’s schema.
- Even for a single experiment, include at least one small Markdown table for key metrics or fold results.
- After each completed `baseline_v*` version, also generate a historical trend PNG for humans that tracks the top 3 experiments of each baseline version across versions.
- Save that figure under `docs/` with a filename like `docs/baseline_v08_to_v11_top3_trend.png`.
- If multiple baseline versions are covered, use line plots to connect versions. Mention the PNG path and the key takeaway in the written result summary back to leader.
- Before claiming train_service is down, first verify it with a concrete request such as `curl --noproxy '*' -sS http://127.0.0.1:8100/queue`.
- For localhost endpoints like `127.0.0.1:8100` and `127.0.0.1:8090`, bypass proxy settings explicitly. Prefer `curl --noproxy '*' ...` or `NO_PROXY=127.0.0.1,localhost curl ...`.
- When submitting `POST /jobs`, replace all placeholder paths with real existing `script_path` and `workdir` values.
- If the HTTP call fails, do not vaguely say “127.0.0.1:8100/8090 returned 502”. Report the exact URL, the exact command, the HTTP status code, and the raw response body back to leader.
- After successful submission, report the returned `train_task_id` plus script path, technical focus, args, and workdir back to leader with `<runtime-cli> delegate --from trainer --to leader "..."`.
- If you submit a formal external training job, report the submission to leader and wait for the result callback instead of idling silently.
- Do not perform runtime control-plane operations unless the human explicitly asks.
""",
    }
    prompt = shared + "\n" + role_specific.get(agent, "Role:\n- Follow leader instructions and keep the shared thread updated.\n")
    return prompt.replace("<runtime-cli>", cli_cmd)


def send_text_to_target(
    cfg: RuntimeConfig,
    target: str,
    content: str,
    *,
    buffer_name: str,
    submit: bool = True,
) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="research-mvp-") as handle:
        handle.write(content)
        tmp_path = handle.name
    try:
        tmux_run(["load-buffer", "-b", buffer_name, tmp_path])
        tmux_run(["paste-buffer", "-b", buffer_name, "-t", target])
        if submit:
            if cfg.submit_delay_ms > 0:
                time.sleep(cfg.submit_delay_ms / 1000)
            for key in cfg.submit_keys:
                tmux_key = "Enter" if key.lower() in {"enter", "return", "c-m", "c-j"} else key
                tmux_run(["send-keys", "-t", target, tmux_key])
                if cfg.submit_delay_ms > 0:
                    time.sleep(cfg.submit_delay_ms / 1000)
    finally:
        subprocess.run(["tmux", "delete-buffer", "-b", buffer_name], capture_output=True, text=True)
        Path(tmp_path).unlink(missing_ok=True)


def capture_target_output(target: str, lines: int = 120) -> str:
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", target, "-S", f"-{lines}"],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def mark_agent_status(cfg: RuntimeConfig, agent: str, status: str, last_event: str) -> None:
    paths = runtime_dirs(cfg)
    state = read_json(paths["state"], {})
    agent_state = state.get("agents", {}).get(agent, {})
    agent_state.update(
        {
            "name": agent,
            "target": agent_target(cfg, agent),
            "status": status,
            "last_seen_at": now_iso(),
            "last_prompt_at": now_iso() if "Bootstrapped" in last_event else agent_state.get("last_prompt_at", ""),
            "last_event": last_event,
        }
    )
    state.setdefault("agents", {})[agent] = agent_state
    state["updated_at"] = now_iso()
    write_json(paths["state"], state)

    agent_file = paths["agents"] / f"{agent}.json"
    payload = read_json(agent_file, {})
    if not isinstance(payload, dict):
        payload = {}
    payload.update(
        {
            "name": agent,
            "target": agent_target(cfg, agent),
            "status": status,
            "updated_at": now_iso(),
            "last_event": last_event,
        }
    )
    write_json(agent_file, payload)


def launch_agent(cfg: RuntimeConfig, agent: str) -> None:
    target = agent_target(cfg, agent)
    env = {
        "RESEARCH_MVP_AGENT": agent,
        "RESEARCH_MVP_RUNTIME_DIR": str(cfg.runtime_root),
        **cfg.env,
        **cfg.agent_env.get(agent, {}),
    }
    export_str = "; ".join(f"export {key}={shlex.quote(value)}" for key, value in env.items())
    cmd_str = " ".join(shlex.quote(part) for part in cfg.codex_command)
    full_cmd = f"{export_str}; cd {shlex.quote(str(cfg.workdir))} && {cmd_str}"
    if not session_exists(cfg):
        tmux_run(["new-session", "-d", "-s", cfg.session_name, "-n", agent, full_cmd])
        tmux_run(["set-option", "-t", cfg.session_name, "remain-on-exit", "on"])
    else:
        window_check = subprocess.run(
            ["tmux", "list-windows", "-t", cfg.session_name, "-F", "#{window_name}"],
            text=True,
            capture_output=True,
        )
        names = window_check.stdout.splitlines() if window_check.returncode == 0 else []
        if agent in names:
            return
        tmux_run(["new-window", "-t", cfg.session_name, "-n", agent, full_cmd])
        tmux_run(["set-window-option", "-t", target, "remain-on-exit", "on"])
    time.sleep(0.6)
    if not check_agent_alive(cfg, agent):
        error_text = capture_target_output(target)
        mark_agent_status(cfg, agent, "offline", "agent process exited during startup")
        detail = f"agent '{agent}' exited during startup"
        if error_text:
            detail += f"\n\nLast log output:\n{error_text}"
        raise RuntimeError(detail)
    prompt = agent_bootstrap_prompt(cfg, agent)
    debug_print(f"bootstrap prompt for {agent}:\n{prompt}\n---")
    send_text_to_target(cfg, target, prompt, buffer_name=f"bootstrap-{agent}", submit=False)
    time.sleep(0.4)
    if not check_agent_alive(cfg, agent):
        error_text = capture_target_output(target)
        mark_agent_status(cfg, agent, "offline", "agent process exited after bootstrap prompt")
        detail = f"agent '{agent}' exited after bootstrap prompt"
        if error_text:
            detail += f"\n\nLast log output:\n{error_text}"
        raise RuntimeError(detail)
    mark_agent_status(cfg, agent, "online", f"Bootstrapped in {target}")


def check_agent_alive(cfg: RuntimeConfig, agent: str) -> bool:
    result = subprocess.run(
        ["tmux", "list-panes", "-t", agent_target(cfg, agent), "-F", "#{pane_dead}"],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False
    return any(line.strip() == "0" for line in result.stdout.splitlines())


def refresh_status(cfg: RuntimeConfig) -> dict[str, object]:
    ensure_runtime_layout(cfg)
    for agent in cfg.agents:
        alive = session_exists(cfg) and check_agent_alive(cfg, agent)
        mark_agent_status(cfg, agent, "online" if alive else "offline", "tmux pane reachable" if alive else "tmux pane missing")
    return read_json(runtime_dirs(cfg)["state"], {})


def cmd_init_config(args: argparse.Namespace) -> int:
    path = Path(args.config).expanduser().resolve()
    if path.exists() and not args.force:
        raise SystemExit(f"config already exists: {path}\nuse --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(), encoding="utf-8")
    print(path)
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    require_tmux()
    require_command(cfg.codex_command[0])
    ensure_runtime_layout(cfg)
    try:
        for agent in cfg.agents:
            launch_agent(cfg, agent)
    except RuntimeError as exc:
        raise SystemExit(f"runtime startup failed:\n{exc}")
    print(f"config={cfg.config_path}")
    print(f"session={cfg.session_name}")
    print(f"workdir={cfg.workdir}")
    for agent in cfg.agents:
        print(f"{agent}: {agent_target(cfg, agent)}")
    if args.no_supervise:
        return 0
    print(f"entering supervisor loop interval={args.interval}s")
    return run_supervisor(cfg, once=False, interval=args.interval)


def run_supervisor(cfg: RuntimeConfig, *, once: bool, interval: float) -> int:
    require_tmux()
    ensure_runtime_layout(cfg)
    if once:
        events = supervise_once(cfg)
        for event in events:
            print(event)
        if not events:
            print("no pending inbox messages delivered")
        return 0

    print(f"supervising session={cfg.session_name} interval={interval}s")
    try:
        while True:
            events = supervise_once(cfg)
            for event in events:
                print(f"{now_iso()} {event}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("supervisor stopped")
        return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    require_tmux()
    state = refresh_status(cfg)
    print(f"config={cfg.config_path}")
    print(f"session={state.get('session_name', cfg.session_name)}")
    print(f"workdir={cfg.workdir}")
    agents = state.get("agents", {})
    for agent in cfg.agents:
        info = agents.get(agent, {})
        print(
            f"{agent:10s} status={info.get('status', 'unknown'):7s} "
            f"target={info.get('target', agent_target(cfg, agent))} "
            f"event={info.get('last_event', '')}"
        )
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    ensure_runtime_layout(cfg)
    if session_exists(cfg):
        tmux_run(["kill-session", "-t", cfg.session_name])
    for agent in cfg.agents:
        mark_agent_status(cfg, agent, "offline", "runtime stopped by operator")
    print(f"stopped session={cfg.session_name}")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    require_tmux()
    ensure_runtime_layout(cfg)
    target_agent = args.agent
    if target_agent not in cfg.agents:
        raise SystemExit(f"unknown agent: {target_agent}")
    if not session_exists(cfg) or not check_agent_alive(cfg, target_agent):
        raise SystemExit(f"target not running: {target_agent}")
    content = args.message.strip()
    if not content:
        raise SystemExit("message is empty")
    queue_message(
        cfg,
        "human",
        target_agent,
        content,
    )
    send_text_to_target(cfg, agent_target(cfg, target_agent), content, buffer_name=f"send-{target_agent}")
    mark_agent_status(cfg, target_agent, "online", "received human message")
    print(f"sent to {target_agent}")
    return 0


def cmd_thread_tail(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    ensure_runtime_layout(cfg)
    rows = sorted_thread_messages(cfg)[-args.lines:]
    for row in rows:
        ts = str(row.get("timestamp", ""))
        sender = str(row.get("from", "?"))
        recipient = str(row.get("to", ""))
        content = str(row.get("content", ""))
        print(f"[{ts}] {sender} -> {recipient}: {content}")
    return 0


def cmd_thread_send(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    ensure_runtime_layout(cfg)
    sender = args.sender
    recipient = args.to
    if sender not in cfg.agents and sender != "human":
        raise SystemExit(f"unknown sender: {sender}")
    if recipient != "all" and recipient not in cfg.agents:
        raise SystemExit(f"unknown agent: {recipient}")
    content = args.message.strip()
    if not content:
        raise SystemExit("message is empty")
    queue_message(
        cfg,
        sender,
        recipient,
        content,
    )
    print(f"thread message queued for {sender} -> {recipient}")
    return 0


def cmd_delegate(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    ensure_runtime_layout(cfg)
    sender = args.sender
    recipient = args.to
    if sender not in cfg.agents and sender != "human":
        raise SystemExit(f"unknown sender: {sender}")
    if recipient not in cfg.agents:
        raise SystemExit(f"unknown recipient: {recipient}")
    content = args.message.strip()
    if not content:
        raise SystemExit("message is empty")
    queue_message(
        cfg,
        sender,
        recipient,
        content,
    )
    print(f"delegated {sender} -> {recipient}")
    return 0


def cmd_inbox_list(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    ensure_runtime_layout(cfg)
    agent = args.agent
    if agent not in cfg.agents:
        raise SystemExit(f"unknown agent: {agent}")
    files = inbox_files(cfg, agent)
    for path in files[-args.limit:]:
        payload = read_json(path, {})
        if not isinstance(payload, dict):
            payload = {}
        print(f"{path.name} {payload.get('timestamp', '')} {payload.get('from', '?')} -> {payload.get('to', '')}")
    return 0


def cmd_inbox_read(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    ensure_runtime_layout(cfg)
    agent = args.agent
    if agent not in cfg.agents:
        raise SystemExit(f"unknown agent: {agent}")
    path = runtime_dirs(cfg)["inbox"] / agent / args.message_id
    if not path.exists():
        raise SystemExit(f"message not found: {path.name}")
    print(json.dumps(read_json(path, {}), indent=2, ensure_ascii=False))
    return 0


def deliver_inbox_message(cfg: RuntimeConfig, agent: str, path: Path) -> tuple[bool, str]:
    try:
        payload = read_json(path, {})
    except json.JSONDecodeError as exc:
        corrupt_path = path.with_name(f"{path.stem}.corrupt.json")
        path.replace(corrupt_path)
        return False, f"corrupt inbox payload moved to {corrupt_path.name}: {exc}"
    if not isinstance(payload, dict):
        return False, "invalid inbox payload"
    if payload.get("delivered_at"):
        return False, "already delivered"
    if not session_exists(cfg) or not check_agent_alive(cfg, agent):
        return False, "target not running"

    sender = str(payload.get("from", "human"))
    timestamp = str(payload.get("timestamp", ""))
    content = str(payload.get("content", "")).strip()
    debug_print(
        f"inbox delivery candidate path={path.name} from={sender} to={agent} "
        f"delivered={bool(payload.get('delivered_at'))}"
    )
    if not content:
        payload["delivered_at"] = now_iso()
        payload["delivery_status"] = "empty"
        write_json(path, payload)
        return False, "empty content"

    envelope_parts = [
        f"New queued message from {sender} at {timestamp}.",
        "Read it, act on it, and update the shared thread if needed.",
    ]
    envelope = "\n".join(envelope_parts) + f"\n\n{content}"
    send_text_to_target(cfg, agent_target(cfg, agent), envelope, buffer_name=f"deliver-{agent}")
    payload["delivered_at"] = now_iso()
    payload["delivery_status"] = "delivered"
    write_json(path, payload)
    mark_agent_status(cfg, agent, "online", f"delivered inbox message {path.name}")
    detail = f"delivered {sender} -> {agent} msg={path.name}"
    return True, detail


def workflow_state_path(cfg: RuntimeConfig) -> Path:
    return runtime_dirs(cfg)["root"] / "workflow_state.json"


def tasks_path(cfg: RuntimeConfig) -> Path:
    return runtime_dirs(cfg)["tasks"]


def load_task_store(cfg: RuntimeConfig) -> dict[str, object]:
    data = read_json(tasks_path(cfg), {"tasks": [], "updated_at": now_iso()})
    if not isinstance(data, dict):
        return {"tasks": [], "updated_at": now_iso()}
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        data["tasks"] = []
    return data


def save_task_store(cfg: RuntimeConfig, store: dict[str, object]) -> None:
    store["updated_at"] = now_iso()
    write_json(tasks_path(cfg), store)


def workflow_state(cfg: RuntimeConfig) -> dict[str, object]:
    data = read_json(workflow_state_path(cfg), {})
    return data if isinstance(data, dict) else {}


def save_workflow_state(cfg: RuntimeConfig, payload: dict[str, object]) -> None:
    write_json(workflow_state_path(cfg), payload)


def sorted_thread_messages(cfg: RuntimeConfig) -> list[dict[str, object]]:
    rows = read_jsonl(runtime_dirs(cfg)["thread"])
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = dict(row)
        if "content" not in normalized and "message" in normalized:
            normalized["content"] = normalized.get("message", "")
        normalized_rows.append(normalized)
    return sorted(normalized_rows, key=lambda row: str(row.get("timestamp", "")))


def _message_contains(row: dict[str, object], *patterns: str) -> bool:
    content = str(row.get("content", "")).lower()
    return any(pattern.lower() in content for pattern in patterns)


def extract_task_ids(text: str) -> list[str]:
    return re.findall(r"\btask-[0-9a-f]{10}\b", text.lower())


def task_title_for_message(content: str, recipient: str) -> str:
    text = " ".join(content.split())
    if len(text) > 96:
        text = text[:95] + "…"
    return f"{recipient}: {text}"


def current_task_marker(rows: list[dict[str, object]]) -> str:
    for row in reversed(rows):
        if str(row.get("from")) == "human":
            return str(row.get("timestamp", ""))
    return ""


def active_task_marker(cfg: RuntimeConfig) -> str:
    return current_task_marker(sorted_thread_messages(cfg))


def completion_signal(text: str) -> bool:
    lowered = text.lower()
    patterns = (
        "done",
        "complete",
        "completed",
        "finished",
        "final review",
        "final report",
        "task complete",
    )
    return any(pattern in lowered for pattern in patterns)


def blocker_signal(text: str) -> bool:
    lowered = text.lower()
    patterns = ("blocked", "blocker", "stuck", "cannot continue", "need input", "need approval", "requires")
    return any(pattern in lowered for pattern in patterns)


def create_task(
    cfg: RuntimeConfig,
    *,
    task_id: str,
    sender: str,
    recipient: str,
    content: str,
    message_id: str,
    parent_task_id: str = "",
    task_marker: str = "",
) -> str:
    store = load_task_store(cfg)
    tasks = store.setdefault("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
        store["tasks"] = tasks
    task = {
        "id": task_id,
        "kind": "delegation" if sender != "human" else "human_request",
        "title": task_title_for_message(content, recipient),
        "content": content,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": sender,
        "owner": recipient,
        "status": "assigned",
        "task_marker": task_marker or active_task_marker(cfg),
        "source_message_id": message_id,
        "parent_task_id": parent_task_id,
        "assigned_at": now_iso(),
        "due_at": iso_after(cfg.stall_timeout_seconds),
        "last_progress_at": "",
        "last_nudge_at": "",
        "stall_count": 0,
        "completion_message_at": "",
        "blocked_message_at": "",
    }
    tasks.append(task)
    save_task_store(cfg, store)
    return task_id


def queue_message(
    cfg: RuntimeConfig,
    sender: str,
    recipient: str,
    content: str,
    *,
    create_task_record: bool = False,
    linked_task_id: str = "",
    parent_task_id: str = "",
    task_marker: str = "",
) -> tuple[str, str]:
    event_id = f"evt-{uuid.uuid4().hex[:12]}"
    event = {
        "timestamp": now_iso(),
        "from": sender,
        "to": recipient,
        "type": "message",
        "content": content,
        "event_id": event_id,
    }
    paths = runtime_dirs(cfg)
    message_id = event_id
    if recipient != "all":
        inbox_path = paths["inbox"] / recipient / f"msg-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.json"
        write_json(inbox_path, event)
        message_id = inbox_path.name
    append_jsonl(paths["thread"], event)
    return message_id, ""


def sync_task_progress(cfg: RuntimeConfig) -> list[str]:
    rows = sorted_thread_messages(cfg)
    store = load_task_store(cfg)
    tasks = store.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    events: list[str] = []
    changed = False
    tasks_by_id = {
        str(task.get("id")): task
        for task in tasks
        if isinstance(task, dict) and str(task.get("id", ""))
    }

    for row in rows:
        sender = str(row.get("from", ""))
        content = str(row.get("content", ""))
        latest_ts = str(row.get("timestamp", ""))
        for task_id in extract_task_ids(content):
            task = tasks_by_id.get(task_id)
            if task is None or str(task.get("owner", "")) != sender:
                continue
            previous_status = str(task.get("status", "assigned"))
            task["last_progress_at"] = latest_ts
            task["updated_at"] = now_iso()
            task["due_at"] = iso_after(cfg.stall_timeout_seconds)
            if blocker_signal(content):
                task["status"] = "blocked"
                task["blocked_message_at"] = latest_ts
            elif completion_signal(content):
                task["status"] = "completed"
                task["completion_message_at"] = latest_ts
            else:
                task["status"] = "in_progress"
            if previous_status != task.get("status"):
                events.append(f"task:{task_id}->{task.get('status')}")
                debug_print(
                    f"sync_task_progress explicit task_id={task_id} owner={sender} "
                    f"status {previous_status} -> {task.get('status')}"
                )
            changed = True

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("completion_message_at", "")):
            continue
        if str(task.get("last_progress_at", "")):
            continue
        owner = str(task.get("owner", ""))
        assigned_at = parse_iso8601(str(task.get("assigned_at", "")))
        if not owner or assigned_at is None:
            continue
        relevant = []
        for row in rows:
            row_time = parse_iso8601(str(row.get("timestamp", "")))
            if row_time is None or row_time < assigned_at:
                continue
            if str(row.get("from", "")) != owner:
                continue
            relevant.append(row)
        if not relevant:
            continue
        latest = relevant[-1]
        latest_ts = str(latest.get("timestamp", ""))
        latest_content = str(latest.get("content", ""))
        previous_status = str(task.get("status", "assigned"))
        task["last_progress_at"] = latest_ts
        task["updated_at"] = now_iso()
        task["due_at"] = iso_after(cfg.stall_timeout_seconds)
        if blocker_signal(latest_content):
            task["status"] = "blocked"
            task["blocked_message_at"] = latest_ts
        elif completion_signal(latest_content):
            task["status"] = "completed"
            task["completion_message_at"] = latest_ts
        elif previous_status in {"assigned", "stalled"}:
            task["status"] = "in_progress"
        if previous_status != task.get("status"):
            events.append(f"task:{task.get('id')}->{task.get('status')}")
            debug_print(
                f"sync_task_progress fallback task={task.get('id')} owner={owner} "
                f"status {previous_status} -> {task.get('status')}"
            )
        changed = True
    if changed:
        save_task_store(cfg, store)
    return events


def detect_stalled_tasks(cfg: RuntimeConfig) -> list[str]:
    store = load_task_store(cfg)
    tasks = store.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    now = iso_now_dt()
    events: list[str] = []
    changed = False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status", ""))
        owner = str(task.get("owner", ""))
        if status not in {"assigned", "in_progress", "blocked", "stalled"} or not owner:
            continue
        if str(task.get("completion_message_at", "")):
            continue
        reference = (
            parse_iso8601(str(task.get("last_progress_at", "")))
            or parse_iso8601(str(task.get("assigned_at", "")))
            or parse_iso8601(str(task.get("created_at", "")))
        )
        if reference is None:
            debug_print(f"stall_check task={task.get('id')} skipped: no valid reference timestamp")
            continue
        age_seconds = (now - reference).total_seconds()
        if age_seconds < cfg.stall_timeout_seconds:
            debug_print(
                f"stall_check task={task.get('id')} owner={owner} status={status} "
                f"age={int(age_seconds)}s < timeout={cfg.stall_timeout_seconds}s"
            )
            continue
        last_nudge = parse_iso8601(str(task.get("last_nudge_at", "")))
        if last_nudge is not None and (now - last_nudge).total_seconds() < cfg.nudge_cooldown_seconds:
            debug_print(
                f"stall_check task={task.get('id')} owner={owner} skipped: "
                f"cooldown active age_since_nudge={int((now - last_nudge).total_seconds())}s"
            )
            continue

        task["status"] = "stalled"
        task["updated_at"] = now_iso()
        task["last_nudge_at"] = now_iso()
        task["stall_count"] = int(task.get("stall_count", 0) or 0) + 1
        task["due_at"] = iso_after(cfg.stall_timeout_seconds)
        changed = True

        message = (
            f"Task {task.get('id')} appears stalled.\n"
            f"Title: {task.get('title')}\n"
            f"Owner: {owner}\n"
            "Resume work if you can. If blocked, report the blocker and the next required actor to leader."
        )
        msg_id, _ = queue_message(
            cfg,
            "system",
            owner,
            message,
            linked_task_id=str(task.get("id", "")),
            task_marker=str(task.get("task_marker", "")),
        )
        events.append(f"stall:nudged owner {owner} via {msg_id} task={task.get('id')}")
        debug_print(
            f"stall_check task={task.get('id')} owner={owner} -> stalled "
            f"age={int(age_seconds)}s stall_count={task.get('stall_count')}"
        )

        if owner != "leader":
            leader_msg, _ = queue_message(
                cfg,
                "system",
                "leader",
                (
                    f"Task {task.get('id')} owned by {owner} appears stalled.\n"
                    f"Title: {task.get('title')}\n"
                    "Check the worker status, unblock it, or reassign the work."
                ),
                linked_task_id=str(task.get("id", "")),
                task_marker=str(task.get("task_marker", "")),
            )
            events.append(f"stall:escalated to leader via {leader_msg} task={task.get('id')}")
    if changed:
        save_task_store(cfg, store)
    return events


def summarize_tasks(cfg: RuntimeConfig) -> dict[str, object]:
    return {
        "updated_at": now_iso(),
        "current_task_marker": "",
        "counts": {},
        "tasks": [],
    }


def train_queue_empty(cfg: RuntimeConfig) -> bool:
    jobs_path = cfg.repo_root / ".research-mvp-data" / "train-service" / "jobs.json"
    data = read_json(jobs_path, {})
    if not isinstance(data, dict):
        return True
    jobs = data.get("jobs", [])
    if not isinstance(jobs, list):
        return True
    for job in jobs:
        if isinstance(job, dict) and str(job.get("status", "")) in {"queued", "running"}:
            return False
    return True


def pending_inbox_count(cfg: RuntimeConfig) -> int:
    total = 0
    for agent in cfg.agents:
        for path in inbox_files(cfg, agent):
            payload = read_json(path, {})
            if isinstance(payload, dict) and not payload.get("delivered_at"):
                total += 1
    return total


def remind_leader_if_idle(cfg: RuntimeConfig) -> list[str]:
    rows = sorted_thread_messages(cfg)
    if not any(str(row.get("from", "")) == "human" for row in rows):
        debug_print("idle_monitor skipped: no human message yet")
        return []
    if pending_inbox_count(cfg) > 0:
        debug_print("idle_monitor skipped: undelivered inbox messages exist")
        return []
    latest_row = rows[-1] if rows else {}
    latest_ts = parse_iso8601(str(latest_row.get("timestamp", "")))
    if latest_ts is None:
        debug_print("idle_monitor skipped: invalid latest thread timestamp")
        return []
    latest_sender = str(latest_row.get("from", "unknown"))
    latest_content = str(latest_row.get("content", "")).strip()
    state = workflow_state(cfg)
    idle_seconds = (iso_now_dt() - latest_ts).total_seconds()
    if not train_queue_empty(cfg):
        if idle_seconds < cfg.train_queue_idle_reminder_seconds:
            debug_print(
                "train_queue_idle skipped: "
                f"idle_seconds={int(idle_seconds)} < timeout={cfg.train_queue_idle_reminder_seconds}"
            )
            return []
        last_train_queue_reminder = parse_iso8601(str(state.get("leader_train_queue_idle_reminded_at", "")))
        if (
            last_train_queue_reminder is not None
            and (iso_now_dt() - last_train_queue_reminder).total_seconds() < cfg.train_queue_idle_reminder_seconds
        ):
            debug_print("train_queue_idle skipped: reminder cooldown active")
            return []
        msg_id, _ = queue_message(
            cfg,
            "system",
            "leader",
            (
                "train_service is still running jobs, and the runtime has been quiet for a long time.\n"
                f"Last thread sender: {latest_sender}\n"
                f"Last thread content: {latest_content or '-'}\n"
                "Keep the work moving instead of waiting passively for training to finish:\n"
                "1. Ask trainer to verify that the current training is progressing normally and that logs, queue state, and artifact paths look healthy.\n"
                "2. Ask researcher to continue task-relevant research, but not by directly editing experiment code or scripts; instead, look for stronger methods, recent approaches, or stronger baselines and summarize the findings under docs/."
            ),
        )
        state["leader_train_queue_idle_reminded_at"] = now_iso()
        save_workflow_state(cfg, state)
        return [f"idle:reminded leader during active train queue via {msg_id}"]
    if idle_seconds < cfg.stall_timeout_seconds:
        debug_print(
            f"idle_monitor skipped: idle_seconds={int(idle_seconds)} < timeout={cfg.stall_timeout_seconds}"
        )
        return []
    last_reminder = parse_iso8601(str(state.get("leader_idle_reminded_at", "")))
    if last_reminder is not None and (iso_now_dt() - last_reminder).total_seconds() < cfg.nudge_cooldown_seconds:
        debug_print("idle_monitor skipped: reminder cooldown active")
        return []
    msg_id, _ = queue_message(
        cfg,
        "system",
        "leader",
        (
            "Human task is active, the training queue is empty, and the runtime appears idle.\n"
            f"Last thread sender: {latest_sender}\n"
            f"Last thread content: {latest_content or '-'}\n"
            "Review the thread, check worker progress, and decide the next delegation or shared update.\n"
            "If the last activity was a version summary, result note, or commit announcement, do not stop there: immediately delegate the next experiment version or ask the human a concrete blocking question."
        ),
    )
    state["leader_idle_reminded_at"] = now_iso()
    save_workflow_state(cfg, state)
    return [f"idle:reminded leader via {msg_id}"]


def supervise_once(cfg: RuntimeConfig) -> list[str]:
    ensure_runtime_layout(cfg)
    events: list[str] = []
    for agent in cfg.agents:
        for path in inbox_files(cfg, agent):
            delivered, detail = deliver_inbox_message(cfg, agent, path)
            if delivered:
                events.append(detail)
            elif detail.startswith("corrupt inbox payload"):
                events.append(f"{agent}:{detail}")
    events.extend(remind_leader_if_idle(cfg))
    return events


def cmd_supervise(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    return run_supervisor(cfg, once=args.once, interval=args.interval)


def cmd_attach(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config).expanduser().resolve())
    require_tmux()
    subprocess.run(["tmux", "attach-session", "-t", cfg.session_name])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rt", description="Research runtime CLI")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to runtime config TOML (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print bootstrap prompts and detailed supervisor/state diagnostics",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_config = sub.add_parser("init-config", help="Write a default runtime config TOML")
    init_config.add_argument("--force", action="store_true", help="Overwrite existing config")
    init_config.set_defaults(func=cmd_init_config)

    up = sub.add_parser("up", help="Start the configured tmux runtime and enter supervise by default")
    up.add_argument("--no-supervise", action="store_true", help="Start runtime without entering the supervisor loop")
    up.add_argument("--interval", type=float, default=3.0, help="Supervisor polling interval in seconds")
    up.set_defaults(func=cmd_up)

    status = sub.add_parser("status", help="Show tmux/runtime status")
    status.set_defaults(func=cmd_status)

    down = sub.add_parser("down", help="Stop the configured tmux runtime session")
    down.set_defaults(func=cmd_down)

    send = sub.add_parser("send", help="Send a message to an agent")
    send.add_argument("agent")
    send.add_argument("message")
    send.set_defaults(func=cmd_send)

    thread = sub.add_parser("thread", help="Inspect or append shared thread messages")
    thread_sub = thread.add_subparsers(dest="thread_command", required=True)

    thread_tail = thread_sub.add_parser("tail", help="Print the latest shared thread messages")
    thread_tail.add_argument("-n", "--lines", type=int, default=20)
    thread_tail.set_defaults(func=cmd_thread_tail)

    thread_send = thread_sub.add_parser("send", help="Append a message to the shared thread and target inbox")
    thread_send.add_argument("--from", dest="sender", default="human", help="Sender name, default: human")
    thread_send.add_argument("--to", required=True, help="Recipient agent")
    thread_send.add_argument("message")
    thread_send.set_defaults(func=cmd_thread_send)

    delegate = sub.add_parser("delegate", help="Queue a directed message from one actor to a target agent")
    delegate.add_argument("--from", dest="sender", required=True, help="Sender name, e.g. leader")
    delegate.add_argument("--to", required=True, help="Recipient agent")
    delegate.add_argument("message")
    delegate.set_defaults(func=cmd_delegate)

    inbox = sub.add_parser("inbox", help="Inspect per-agent inbox messages")
    inbox_sub = inbox.add_subparsers(dest="inbox_command", required=True)

    inbox_list = inbox_sub.add_parser("list", help="List inbox messages for an agent")
    inbox_list.add_argument("agent")
    inbox_list.add_argument("--limit", type=int, default=20)
    inbox_list.set_defaults(func=cmd_inbox_list)

    inbox_read = inbox_sub.add_parser("read", help="Read one inbox message file")
    inbox_read.add_argument("agent")
    inbox_read.add_argument("message_id")
    inbox_read.set_defaults(func=cmd_inbox_read)

    supervise = sub.add_parser("supervise", help="Deliver queued inbox messages into tmux agents")
    supervise.add_argument("--once", action="store_true", help="Run one delivery pass and exit")
    supervise.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds")
    supervise.set_defaults(func=cmd_supervise)

    attach = sub.add_parser("attach", help="Attach to the tmux session")
    attach.set_defaults(func=cmd_attach)

    return parser


def main(argv: list[str] | None = None) -> int:
    global RUNTIME_DEBUG
    parser = build_parser()
    args = parser.parse_args(argv)
    RUNTIME_DEBUG = bool(getattr(args, "debug", False))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
