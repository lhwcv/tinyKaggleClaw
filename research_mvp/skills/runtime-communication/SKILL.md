---
name: runtime-communication
description: "Use this skill when working inside the research_mvp tmux runtime with fixed agents (leader, researcher, trainer) and you need to read shared thread messages, inspect per-agent inboxes, delegate tasks between agents, or follow the repository's runtime communication contract. Specifically for the file-backed runtime CLI under research_mvp/runtime_cli.py."
user-invocable: true
triggers:
  - runtime communication
  - read the shared thread
  - delegate to researcher
  - send to trainer
  - check agent inbox
  - runtime_cli
  - leader to researcher message
---

# Runtime Communication

Use this skill only for the local `research_mvp` runtime.

## Files To Read First

- `AGENTS.md`
- `research_mvp/runtime.toml`

## Commands

Use the configured runtime CLI:

```bash
python -m research_mvp.runtime_cli --config research_mvp/runtime.toml status
python -m research_mvp.runtime_cli --config research_mvp/runtime.toml thread tail -n 50
python -m research_mvp.runtime_cli --config research_mvp/runtime.toml inbox list leader
```

## Messaging Rules

- Shared thread is for summaries, planning context, progress reporting, and visibility.
- Direct agent work must go through targeted inbox delegation.
- If you need one specific agent to receive a message, use `delegate` or `thread send` through `runtime_cli`. Do not hand-edit `thread.jsonl`, because that does not create an inbox delivery.
- Formal long-running training should be submitted to an external `train_service`, not left running inside the `trainer` tmux pane.
- If the human request is to start a task under `recipe/<name>/`, first read `recipe/<name>/data.md`, `recipe/<name>/overview.md`, and `recipe/<name>/start_prompt.md`.
- Treat `recipe/<name>/` tasks as Kaggle-style competition tasks by default unless the recipe explicitly says otherwise.
- For a new `recipe/<name>/` task, do EDA before baseline iteration. Put EDA scripts, notes, and charts under `<workdir>/eda/`.
- This runtime is a machine-learning baseline team. Default iteration should follow the repository's existing baseline naming, such as `baseline_v10`, `baseline_v11`, `baseline_v12`.
- Each version should usually contain multiple experiments, managed by yaml configs under `baseline/experiments_v*/`.
- Default layout:
  - experiment scripts, yaml configs, and helpers in `<workdir>/baseline/`
  - code in `<workdir>/src/baseline/`
  - data in `<workdir>/data/`
  - outputs, checkpoints, metrics, and logs in `<workdir>/output/`
  - version design and result docs in `<workdir>/docs/`
  - versioned experiment configs typically under `<workdir>/baseline/experiments_v11/`
  - versioned formal runners typically under `<workdir>/baseline/run_experiments_v11.sh`
  - versioned outputs typically under `<workdir>/output/baseline_v11/`
- For each version, keep one formal version runner script in `baseline/`, typically `baseline/run_experiments_v11.sh`. That runner should call `python baseline/run_baseline.py --config baseline/experiments_v11/<config>.yaml` multiple times.
- `runtime_root` is only for runtime state, inboxes, and thread data. Do not use it for checkpoints, artifacts, caches, or reports.
- Default training behavior should be observable: unless the human explicitly asks for denser logging, training code should emit at least one meaningful progress log per epoch.
- Good coordination uses both:
  - direct inbox delegation for execution
  - shared thread updates for human visibility and cross-agent context
- Runtime agents should not use control-plane commands like `up`, `attach`, or `supervise`.
- Avoid relying on `status` from inside a runtime agent. Use thread, inbox, artifacts, and direct delegation instead.
- Prefer:

```bash
python -m research_mvp.runtime_cli --config research_mvp/runtime.toml delegate --from leader --to researcher "..."
```

instead of only writing:

```text
leader -> all: researcher should do ...
```

## Leader Workflow

For each new task:

1. Read latest shared thread and relevant inboxes.
2. Break the task into direct assignments.
3. If the human starts a `recipe/<name>/` task, first assign recipe reading and EDA. Do not jump straight to model iteration.
4. If training is needed, first ask `researcher` for a versioned package that follows the repository layout: code in `src/baseline/`, configs in `baseline/experiments_v*/`, a formal runner such as `baseline/run_experiments_v11.sh`, outputs under `output/baseline_v*/`, and a design note in `docs/` using the existing `baseline_v*_exp*.md` pattern.
5. Expect exactly one formal version runner script per version under `baseline/`; it should fan out to multiple experiments via repeated `python baseline/run_baseline.py --config ...` calls.
6. Review the training package before queue submission. This includes checking that `src/baseline/train.py` and related scripts provide enough intermediate logs to observe training progress, plus a clear startup log that confirms training has actually begun.
7. Ask `researcher` to complete the minimal dry run; it should validate startup and configuration without drifting into real training.
8. Only after that hand the package to `trainer` for queue submission.
9. Delegate to each target agent with `delegate`.
10. Write one concise `leader -> all` summary to the shared thread.
11. After a version is completed and worth preserving, make a git commit covering the relevant `src/baseline/` and `baseline/` changes.
12. Every 5 baseline versions, stop and compare the current team path against reference solutions or newly researched alternatives. Explicitly note the main gaps and the most promising ideas to borrow.
13. Convert the most credible borrowable ideas from that review into concrete next experiments or follow-up tasks.
14. Re-check inbox/thread before deciding the next action.
15. Do not stop at a version summary, result note, or commit. After each version closes, immediately delegate the next version or ask one concrete blocking question to the human.

Do not:

- restart the runtime on your own
- treat tmux/socket repair as part of the normal task
- spend cycles checking infrastructure health unless the human explicitly asks for runtime repair

## Worker Workflow

- Treat inbox messages as executable tasks.
- Report progress, completion, and blockers back to `leader` by default.
- If the recipient is specifically `leader`, prefer `python -m research_mvp.runtime_cli --config research_mvp/runtime.toml delegate --from <worker> --to leader "..."` so the message lands in both the thread and `leader` inbox.
- Use shared-thread updates for milestone visibility, artifact announcements, and high-value cross-agent context.
- If blocked, say what you need and who should act next.

Additional trainer-specific rule:

- `trainer` should only do job submission and result triage inside the runtime.
- Once a formal training job is submitted, treat the task as waiting on an external service.
- When a callback arrives from the training service, inspect the result and report back to `leader`.
- After submitting a training job, wait at least 1 second before querying status or queue state again.
- Do not draft or publish the final training report until the result callback has actually arrived.
- `trainer` should not run local dry runs by default; dry runs belong to `researcher`.
- Once `researcher` has confirmed the minimal dry run passed, submission to `train_service` should normally follow immediately rather than waiting for another manual nudge.
- When reporting the submission, include `train_task_id`, `script_path`, `technical_focus`, `script_args`, and `workdir`.
- Default dry run should use `python baseline/run_baseline.py --config <yaml> --dry-run --fold 0`.
- Default formal submission should use a real script file under `<workdir>/baseline/`, typically `baseline/run_experiments_v11.sh`, or another queue-ready shell wrapper created for that version.
- Before saying `train_service` is unavailable, first verify it with a concrete request such as `curl -sS http://127.0.0.1:8100/queue`.
- For localhost endpoints like `127.0.0.1:8100` and `127.0.0.1:8090`, bypass shell proxy settings. Prefer `curl --noproxy '*' ...` or `NO_PROXY=127.0.0.1,localhost curl ...`.
- When calling `POST /jobs`, use real existing paths for `script_path` and `workdir`; do not reuse placeholder values like `/abs/path/to/train.sh`.
- If an HTTP call fails, report the exact URL, command, status code, and response body to `leader` instead of a vague statement like “127.0.0.1:8100/8090 returned 502”.

Additional researcher-specific rule:

- `researcher` owns the minimal dry run for newly written training code and scripts.
- For `recipe/<name>/` tasks, `researcher` should begin by reading the three recipe docs and producing EDA assets under `eda/` before proposing iterative model work.
- That dry run should validate startup, config parsing, data path resolution, and dependency wiring without drifting into real training.
- `src/baseline/train.py` should emit a clear startup log before training begins so humans and agents can tell that the job truly started.
- After designing each experiment version, `researcher` should write the design note to `docs/` using the existing pattern, such as `docs/baseline_v11_1_exp.md`.

Additional trainer-specific documentation rule:

- After results come back from `train_service`, `trainer` should write a result summary to `docs/` using the matching result-note pattern, such as `docs/baseline_v11_1_exp_result.md`.
- That result summary should default to the same general style as `docs/baseline_v11_1_exp_result.md`: one-line conclusion first, then Markdown tables for the key comparisons.
- If multiple experiments, folds, or configs are involved, prefer a compact table, but choose columns according to the current task rather than a fixed project-specific schema.
- Even for a single run, include at least one compact Markdown table for metrics instead of only prose.
- After each completed `baseline_v*` version, `trainer` should also generate a historical PNG trend chart under `docs/` that tracks the best top 3 experiments of each baseline version across versions.
- Use a filename like `docs/baseline_v08_to_v11_top3_trend.png`.
- When multiple baseline versions are included, connect versions with line plots so humans can visually track the trend over time.
- Mention the generated PNG path and the high-level takeaway in the corresponding result summary.
