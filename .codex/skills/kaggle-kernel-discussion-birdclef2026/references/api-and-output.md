# API And Output

## Discussion API sequence

BirdCLEF 2026 discussion pulling currently depends on this sequence:

1. Resolve competition metadata:

```text
GET https://www.kaggle.com/api/i/competitions.CompetitionService/GetCompetition?competitionName=birdclef-2026
```

2. Resolve forum metadata from the returned `forumId`:

```text
GET https://www.kaggle.com/api/i/discussions.DiscussionsService/GetForum?forumId=<forum_id>
```

3. Paginate topic index:

```text
GET https://www.kaggle.com/api/i/discussions.DiscussionsService/GetTopicListByForumId?forumId=<forum_id>&page=<page>
```

4. Pull full topic payload with comments:

```text
GET https://www.kaggle.com/api/i/discussions.DiscussionsService/GetForumTopicById?forumTopicId=<topic_id>&includeComments=true
```

## Fields worth preserving

From topic index rows:

- `id`
- `title`
- `topicUrl`
- `authorUser`
- `postDate`
- `lastCommentPostDate`
- `commentCount`
- `votes`

From topic detail:

- `topic.id`
- `topic.name`
- `topic.url`
- `topic.firstMessage.rawMarkdown`
- `topic.firstMessage.content`
- `topic.comments`

From each comment:

- `id`
- `postDate`
- `rawMarkdown`
- `content`
- `author`
- `votes`
- `replies`

## Output roles

Use this output split:

- normalized JSON for downstream analysis
- raw JSON for schema debugging
- markdown export for direct reading

Expected layout:

```text
kaggle_info/discussions/
  latest/
    competition.json
    forum.json
    index.csv
    summary.md
    run_info.json
    threads/
    raw_threads/
    markdown_threads/
  snapshots/<timestamp>/
    ...
```

## Quick validation checklist

After a refresh:

- `summary.md` exists
- `index.csv` row count matches topic count in `summary.md`
- every topic in `index.csv` has a matching file in `threads/`
- every topic in `threads/` has a matching file in `raw_threads/`
- `firstMessage.rawMarkdown` is present in thread payloads

## Fallback note

If this API path breaks, the fallback is Playwright with a logged-in browser context. That is a recovery path, not the default path.

## Notebook CLI sequence

Notebook pulling currently depends on the official Kaggle CLI.

Typical calls:

```text
kaggle kernels list --competition birdclef-2026 --page-size 100 --sort-by scoreDescending -v
kaggle kernels list --competition birdclef-2026 --page-size 100 --sort-by voteCount -v
kaggle kernels pull <owner>/<slug> -p <target_dir> -m
```

## Notebook fields worth preserving

From CLI CSV rows:

- `ref`
- `title`
- `totalVotes` or `total_votes`
- any column containing `score`
- last run time field if present

Normalized fields worth keeping:

- `ref`
- `owner`
- `slug`
- `notebook_url`
- `score_value`
- `score_source_column`
- `sort_by`
- `page`
- `fetched_at`

## Notebook output roles

Expected layout:

```text
kaggle_info/notebooks/
  latest/
    kernels_normalized.csv
    summary.md
    run_info.json
  snapshots/<timestamp>/
    raw/
    kernels_raw_combined.csv
    kernels_normalized.csv
  pulled/<owner>/<slug>/
    ...
```

## Notebook quick validation checklist

After a refresh:

- `kaggle_info/notebooks/latest/kernels_normalized.csv` exists
- `summary.md` exists
- `score_value` is populated when the CLI exposed a score field
- pulled notebooks land under `pulled/` when `--pull-top-n` was used
