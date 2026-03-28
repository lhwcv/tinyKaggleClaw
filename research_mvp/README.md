# Research MVP

Minimal autonomous ML research board built with:

- Python 3.12
- FastAPI
- a lightweight single-page frontend
- an internal local runtime for team members, tasks, event logs, and tmux-backed Codex sessions

## Features

- Three board stages: `TODO`, `Agent Working`, `Human Review`
- Fixed agent roles: `leader`, `researcher`, `trainer`
- Background leader loop that advances pending subtasks
- Idle detection: if a running agent stops heartbeating, leader intervenes
- Live discussion stream over SSE
- Task and document views for each project

## Run

```bash
cd /Users/lihaowei/Documents/lhw/lihaoweicv/kaggle/KaggleMLClaw_birdclef
python -m uvicorn research_mvp.app:app --port 8090
```

Open:

```bash
http://127.0.0.1:8090/
```

## Runtime CLI

Initialize or overwrite the runtime config:

```bash
python -m research_mvp.runtime_cli init-config --force
```

Edit `research_mvp/runtime.toml` to set the working directory, runtime root, tmux session name, Codex command, per-agent env, and idle reminder thresholds.

Start the configured three-agent tmux runtime:

```bash
python -m research_mvp.runtime_cli up
```

`up` now starts the tmux runtime and enters the supervisor loop by default.
Use `python -m research_mvp.runtime_cli up --no-supervise` only if you explicitly want to skip the control loop.

Check runtime status:

```bash
python -m research_mvp.runtime_cli status
```

Stop the runtime:

```bash
python -m research_mvp.runtime_cli down
```

Send a message to the leader:

```bash
python -m research_mvp.runtime_cli send leader "Review the thread and decide the next task."
```

Attach to the tmux session:

```bash
python -m research_mvp.runtime_cli attach
```

## Train Service

`train_service` 现在作为 `research_mvp` 的子目录和子系统存在，位置是 `research_mvp/train_service/`。

Run the training service:

```bash
python -m uvicorn research_mvp.train_service.app:app --port 8100
```

Open:

```text
http://127.0.0.1:8100/
```

This subservice provides:

- `POST /jobs`
- `GET /jobs`
- a simple queue worker
- a file-backed queue in `.research-mvp-data/train-service/jobs.json`
- demo `hello` and `delay_echo` scripts
- callback delivery to `research_mvp` at `/api/runtime/training-callback`
- restart recovery for unfinished jobs

## Notes

- App data is stored under `./.research-mvp-data/`
- Runtime metadata lives under `./.research-mvp-data/runtime/`
- Runtime metadata is control-plane state only; experiment outputs should go under `<workdir>/output/baseline_v*/`
- `train_queue_idle_reminder_seconds` controls how long the runtime can stay quiet while `train_service` still has queued/running jobs before leader gets a reminder to keep parallel work moving
- Default workspace layout under `<workdir>` is:
  - `baseline/` for experiment configs, runner scripts, and baseline utilities
  - `src/baseline/` for code
  - `data/` for datasets
  - `output/` for checkpoints, metrics, and logs
  - `docs/` for experiment design notes and result summaries
- Each experiment version should usually map to `baseline/experiments_v*/`, a matching runner like `baseline/run_experiments_v*.sh`, and an output directory like `output/baseline_v*/`
- Formal runners should normally call `python baseline/run_baseline.py --config baseline/experiments_v*/...yaml`, which then executes `python -m src.baseline.train`
- `researcher` should write version design notes to `docs/` using the existing baseline naming pattern, such as `docs/baseline_v11_1_exp.md`
- `trainer` should write result summaries to `docs/` using the matching result-note pattern, such as `docs/baseline_v11_1_exp_result.md`
- This MVP no longer depends on `ClawTeam-main/`
- The board still uses UI/API-driven heartbeats and task completion for the researcher/trainer loop
- Leader chat is started as a real tmux-backed Codex session from the web UI
