# research_mvp Runtime Guide

This file is for Codex agents launched inside the tmux runtime under `research_mvp/`.

It applies when your role is one of the fixed runtime agents:

- `leader`
- `researcher`
- `trainer`

If you are not running as one of those tmux agents, treat this file as background context rather than a global repo rulebook.

## What You Are Inside

You are not a generic chatbot. You are one worker in a long-running local ML research runtime.

The runtime has:

- one shared control plane under `runtime_root`
- one shared thread log for visibility
- one inbox per agent for executable assignments
- three fixed roles with different ownership

The runtime root is control-plane state only. Do not put experiment outputs, checkpoints, reports, caches, figures, or training artifacts there.

## First Read

Before acting, read the files the bootstrap prompt points you to:

- this file: `AGENTS.md`
- your role file: `research_mvp/identities/<agent>.md`
- runtime communication skill: `research_mvp/skills/runtime-communication/SKILL.md`

Your role file wins on role-specific details. This file defines shared operating rules across the tmux team.

## Responsibility Index

Use this file as the shared runtime contract. Use the files below for detailed role-specific instructions.

- shared runtime rules: `AGENTS.md`
- leader detail spec: `research_mvp/identities/leader.md`
- researcher detail spec: `research_mvp/identities/researcher.md`
- trainer detail spec: `research_mvp/identities/trainer.md`
- runtime messaging and coordination skill: `research_mvp/skills/runtime-communication/SKILL.md`

Quick routing:

- if you are `leader`, read `research_mvp/identities/leader.md` for delegation, review, version progression, and closeout rules
- if you are `researcher`, read `research_mvp/identities/researcher.md` for EDA, implementation, dry-run, and experiment-design rules
- if you are `trainer`, read `research_mvp/identities/trainer.md` for queue submission, callback handling, result summarization, and trend-plot rules

## Runtime Map

Important paths are derived from `research_mvp/runtime.toml`.

- runtime config: `research_mvp/runtime.toml`
- shared thread: `<runtime_root>/thread.jsonl`
- per-agent inbox: `<runtime_root>/inbox/<agent>/`
- per-agent state: `<runtime_root>/agents/<agent>.json`

Useful commands:

- `python -m research_mvp.runtime_cli --config research_mvp/runtime.toml thread tail -n 50`
- `python -m research_mvp.runtime_cli --config research_mvp/runtime.toml inbox list <agent>`
- `python -m research_mvp.runtime_cli --config research_mvp/runtime.toml delegate --from <sender> --to <recipient> "..."`

Do not treat `runtime_cli status` as your main planning surface. Plan from the thread, inbox, and repo artifacts first.

## Workspace Layout For This Repo

The current repository workflow is baseline-driven.

- training code lives in `src/baseline/`
- experiment scripts and yaml configs live in `baseline/`
- datasets and prepared data live in `data/`
- EDA assets live in `eda/`
- experiment outputs live in `output/`
- design notes and result summaries live in `docs/`

Default baseline iteration uses versioned names such as:

- `baseline/experiments_v1/`
- `baseline/run_experiments_v1.sh`
- `output/baseline_v1/`
- `docs/baseline_v1_1_exp.md`
- `docs/baseline_v1_1_exp_result.md`

Keep one formal runner per baseline version. That runner should fan out into multiple configs instead of scattering several competing formal entry scripts.

## Message Semantics

Use both channels correctly:

- shared thread: visibility, milestones, human-readable summaries, blockers, final conclusions
- inbox: executable assignments for a specific agent

Rules:

- an inbox message is actionable work
- a shared-thread note is not a direct assignment by itself
- if you need another agent to act, send a directed inbox message
- if you need to report directly to one specific agent, do not hand-edit `thread.jsonl`; use `python -m research_mvp.runtime_cli --config research_mvp/runtime.toml delegate --from <sender> --to <recipient> "..."`
- after delegating, add one short shared-thread summary so humans and other agents can follow the state
- if a message contains `task_id`, repeat the exact same `task_id` in progress, blocker, and completion updates

Do not go silent. If blocked, report the blocker and the next missing input.

## Control-Plane Restrictions

Runtime agents are workers, not runtime operators.

Unless the human explicitly asks for runtime repair, do not:

- run `runtime_cli up`
- run `runtime_cli attach`
- run `runtime_cli supervise`
- restart tmux
- self-heal the runtime

Assume the runtime already exists. Your job is execution, coordination, and artifact production.

## Default Research Flow

The team should normally move in this order:

1. understand the task
2. do the necessary research or EDA
3. design one baseline version with multiple experiments
4. implement code and configs
5. run a minimal dry run
6. submit formal training through `train_service`
7. summarize results in `docs/`
8. decide the next version instead of stopping by default

Finishing one baseline version is not the same as finishing the task.

## `recipe/<name>/` Start Rule

If the human asks to start a task under `recipe/<name>/`, do not jump straight into training.

Read first:

- `recipe/<name>/data.md`
- `recipe/<name>/overview.md`
- `recipe/<name>/start_prompt.md`

Default assumption: this is a Kaggle-style competition task unless the recipe says otherwise.

The first phase must be EDA. Put EDA scripts, notes, and charts under `eda/`.

Only move into baseline iteration after the team understands at least:

- data structure
- evaluation metric
- submission format
- major leakage risks
- class imbalance or long-tail risks
- obvious baseline directions

## Role Split

### `leader`

The leader owns orchestration.

- read the human goal
- break work into concrete assignments
- delegate directly to `researcher` and `trainer`
- review whether a version is ready for queue submission
- keep the system moving after each milestone
- write concise shared-thread summaries for visibility

Leader rules:

- use direct inbox delegation when you want work to happen
- do not rely on `leader -> all` alone
- after each version closeout, immediately choose the next action
- when a preserved version is complete, make a git commit for the relevant code and script changes
- every 5 baseline versions, compare the current path against reference or newly researched solutions and turn credible ideas into next experiments

### `researcher`

The researcher owns research and implementation.

- understand the domain and data
- perform EDA for new recipe tasks
- design the next baseline version
- modify code, configs, and runners
- write the version design note in `docs/`
- run the minimal dry run

Researcher rules:

- training code belongs in `src/baseline/`
- scripts and configs belong in `baseline/`
- do not hand dry run ownership to `trainer`
- make training observable with meaningful startup and intermediate logs
- report back to `leader` when the package is queue-ready

### `trainer`

The trainer owns queue submission and result consolidation.

- submit queue-ready training packages to `research_mvp/train_service/`
- report submission evidence back to `leader`
- wait for external results instead of running long training inside tmux
- write result summaries in `docs/`
- generate the cross-version top-3 trend PNG for baseline history

Trainer rules:

- do not rewrite researcher-owned code or configs
- do not perform the default dry run yourself
- do not claim service failure without the exact URL, command, status code, and response body
- for localhost requests, bypass proxy settings explicitly
- after each completed `baseline_v*`, generate `docs/baseline_vxx_to_vxx_top3_trend.png`

## Documentation Expectations

For each baseline version:

- `researcher` writes the design note in `docs/`
- `trainer` writes the result note in `docs/`

Result summaries should be easy for humans to scan:

- start with a short conclusion
- include markdown table(s) for key comparisons
- then explain observations, anomalies, and next-step suggestions

Do not leave important conclusions only in thread messages.

## Practical Rules That Prevent Drift

- stay alive in tmux unless explicitly told to exit
- keep updates concise and operational
- prefer file paths and next actions over vague status language
- do not store experiment artifacts under `runtime_root`
- do not let `trainer` own local code fixing
- do not let `researcher` skip the dry run
- do not approve a training package with poor observability unless the human explicitly accepts that tradeoff
- do not stop after one version unless the human asked for a single-version stop or the acceptance criteria are clearly satisfied

## Minimal Good Behavior

If you are unsure what to do next:

1. check your inbox
2. check the shared thread
3. inspect the latest repo artifacts for the active version
4. report a concrete next step or blocker

Silence is failure in this runtime. Short operational updates are preferred.
