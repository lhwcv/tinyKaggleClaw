---
name: kaggle-kernel-discussion-birdclef2026
description: Use this skill when you need to pull, refresh, inspect, or summarize BirdCLEF 2026 Kaggle discussions or public notebooks into the repository. It covers the current Kaggle discussion API path, the Kaggle CLI notebook workflow, the expected output layout under kaggle_info, and fallback guidance when the access path changes.
---

# Kaggle Kernel And Discussion BirdCLEF 2026

Use this skill when the task is specifically about BirdCLEF 2026 Kaggle public tracking:

- pull all public discussion threads
- refresh the topic index
- inspect raw thread payloads
- summarize new discussion content
- list competition notebooks
- pull top notebooks
- track notebook scores or vote performance
- debug why the discussion pull stopped working
- debug why the notebook pull stopped working

Discussion and notebook tracking use different access paths and should stay separated in implementation even though this skill covers both.

## Current methods

### Discussions

The primary path is Kaggle's public internal JSON API, not DOM scraping.

Use these endpoints in order:

1. `GET /api/i/competitions.CompetitionService/GetCompetition?competitionName=birdclef-2026`
2. `GET /api/i/discussions.DiscussionsService/GetForum?forumId=<forum_id>`
3. `GET /api/i/discussions.DiscussionsService/GetTopicListByForumId?forumId=<forum_id>&page=<page>`
4. `GET /api/i/discussions.DiscussionsService/GetForumTopicById?forumTopicId=<topic_id>&includeComments=true`

Important fields:

- `competition.forumId`
- `topics[].id`
- `topics[].topicUrl`
- `topic.firstMessage.rawMarkdown`
- `topic.comments`
- `comment.rawMarkdown`
- `comment.replies`

For the current BirdCLEF 2026 forum, this path has worked anonymously.

### Notebooks

The primary path is the official Kaggle CLI.

Use:

- `kaggle kernels list --competition birdclef-2026`
- `kaggle kernels pull <owner>/<slug> -m`

Notebook pulling requires:

- a working `kaggle` CLI install
- `~/.config/kaggle/kaggle.json`

The bundled notebook script queries multiple sorts and normalizes any score-like field into `score_value`.

## Bundled files

Read these first. These relative links are internal to the skill package:

- [scripts/kaggle_pull_discussions.py](scripts/kaggle_pull_discussions.py)
- [scripts/kaggle_pull_notebooks.py](scripts/kaggle_pull_notebooks.py)

If you need example payload shape or output expectations, read:

- [references/api-and-output.md](references/api-and-output.md)

## Standard workflow

### Refresh discussions

Prefer the bundled script:

```bash
python /.codex/skills/kaggle-kernel-discussion-birdclef2026/scripts/kaggle_pull_discussions.py
```

For index-only refresh:

```bash
python /.codex/skills/kaggle-kernel-discussion-birdclef2026/scripts/kaggle_pull_discussions.py --skip-topic-details
```

After running, inspect:

- `kaggle_info/discussions/latest/summary.md`
- `kaggle_info/discussions/latest/index.csv`
- `kaggle_info/discussions/latest/threads/`
- `kaggle_info/discussions/latest/raw_threads/`
- `kaggle_info/discussions/latest/markdown_threads/`

### Refresh notebooks

Prefer the bundled script:

```bash
python /.codex/skills/kaggle-kernel-discussion-birdclef2026/scripts/kaggle_pull_notebooks.py
```

To also pull top notebooks:

```bash
python /.codex/skills/kaggle-kernel-discussion-birdclef2026/scripts/kaggle_pull_notebooks.py --pull-top-n 20
```

After running, inspect:

- `kaggle_info/notebooks/latest/summary.md`
- `kaggle_info/notebooks/latest/kernels_normalized.csv`
- `kaggle_info/notebooks/pulled/`

### Summarize discussions or notebooks

Use `markdown_threads/` when reading for content. Use `raw_threads/` when debugging missing fields or schema drift.

Prefer producing:

- a digest of high-value threads
- a repo-action note tied to training or validation decisions
- a notebook leaderboard or method table tied to score, votes, and author

Keep the raw data untouched. Write summaries into `kaggle_info/discussions/` or `docs/` depending on whether the output is tracking data or durable project documentation.

## Decision rules

- Prefer the JSON API over Playwright.
- Prefer the Kaggle CLI over ad hoc notebook HTML scraping.
- Prefer the skill-bundled scripts when portability matters.
- Preserve raw Kaggle responses before normalizing or summarizing.
- Assume the API schema can drift.
- Avoid aggressive request rates.
- Do not rely on HTML discussion pages as the primary source of truth.

## Failure handling

If the current API path stops working:

1. verify `GetCompetition` still resolves `birdclef-2026`
2. verify `forumId` has not changed
3. inspect `raw_threads/` and `competition.json` from the latest successful run
4. check whether endpoint names or payload keys changed
5. only then fall back to Playwright

If notebook pulling stops working:

1. verify `kaggle` CLI is installed
2. verify `~/.config/kaggle/kaggle.json` exists and is valid
3. inspect the raw CSV snapshots under `kaggle_info/notebooks/snapshots/`
4. check whether the CLI output column names changed
5. keep raw notebook index pages before changing the parser

Use Playwright as fallback when:

- the JSON endpoints start returning auth or anti-bot failures
- thread detail payloads lose `firstMessage` or comments
- the forum listing endpoint stops returning topics

## What not to do

- Do not mix notebook and discussion logic into one crawler.
- Do not treat old Playwright-only notes as the current primary method.
- Do not delete old snapshots when debugging parser changes.
- Do not summarize from partial HTML if the JSON pull is available.
- Do not hardcode a single notebook score column name.

## Expected outputs

The discussion pipeline should leave these artifacts:

- `competition.json`
- `forum.json`
- `index.csv`
- `summary.md`
- `run_info.json`
- `threads/<topic_id>.json`
- `raw_threads/<topic_id>.json`
- `markdown_threads/<topic_id>.md`

If these are missing, treat the run as incomplete.

The notebook pipeline should leave these artifacts:

- `latest/kernels_normalized.csv`
- `latest/summary.md`
- `latest/run_info.json`
- `snapshots/<timestamp>/raw/*.csv`
- `snapshots/<timestamp>/kernels_raw_combined.csv`
- `snapshots/<timestamp>/kernels_normalized.csv`
- `pulled/<owner>/<slug>/` when notebook source is fetched

If these are missing, treat the run as incomplete.
