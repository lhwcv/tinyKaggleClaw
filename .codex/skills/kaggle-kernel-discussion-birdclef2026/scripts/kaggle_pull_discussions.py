from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_COMPETITION = "birdclef-2026"
DEFAULT_OUTPUT_ROOT = Path("kaggle_info/discussions")
BASE_URL = "https://www.kaggle.com"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def content_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class KaggleDiscussionsClient:
    def __init__(self, timeout: int = 30) -> None:
        self.session = requests.Session()
        self.timeout = timeout

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        if not resp.text.strip():
            raise ValueError(f"Empty response from {url} with params={params}")
        return resp.json()

    def get_competition(self, competition_name: str) -> dict[str, Any]:
        return self.get_json(
            "/api/i/competitions.CompetitionService/GetCompetition",
            params={"competitionName": competition_name},
        )

    def get_forum(self, forum_id: int) -> dict[str, Any]:
        return self.get_json(
            "/api/i/discussions.DiscussionsService/GetForum",
            params={"forumId": forum_id},
        )

    def get_topics(self, forum_id: int, page: int) -> dict[str, Any]:
        return self.get_json(
            "/api/i/discussions.DiscussionsService/GetTopicListByForumId",
            params={"forumId": forum_id, "page": page},
        )

    def get_topic_detail(self, topic_id: int, include_comments: bool = True) -> dict[str, Any]:
        return self.get_json(
            "/api/i/discussions.DiscussionsService/GetForumTopicById",
            params={"forumTopicId": topic_id, "includeComments": str(include_comments).lower()},
        )


def normalize_topic_index_row(topic: dict[str, Any], fetched_at: str, competition: dict[str, Any]) -> dict[str, Any]:
    author = topic.get("authorUser", {}) or {}
    return {
        "topic_id": topic.get("id"),
        "forum_id": competition.get("forumId"),
        "competition_name": competition.get("competitionName"),
        "competition_title": competition.get("title"),
        "title": topic.get("title"),
        "topic_url": f"{BASE_URL}{topic.get('topicUrl', '')}" if topic.get("topicUrl") else "",
        "author_display_name": author.get("displayName", ""),
        "author_url": f"{BASE_URL}{author.get('url', '')}" if author.get("url") else "",
        "author_tier": author.get("tier", ""),
        "author_id": author.get("id", ""),
        "author_type": topic.get("authorType", ""),
        "post_date": topic.get("postDate", ""),
        "last_comment_post_date": topic.get("lastCommentPostDate", ""),
        "last_commenter_name": topic.get("lastCommenterName", ""),
        "last_commenter_url": (
            f"{BASE_URL}{topic.get('lastCommenterUrl', '')}" if topic.get("lastCommenterUrl") else ""
        ),
        "comment_count": topic.get("commentCount", 0),
        "votes": topic.get("votes", 0),
        "is_sticky": topic.get("isSticky", False),
        "first_forum_message_id": topic.get("firstForumMessageId", ""),
        "parent_name": topic.get("parentName", ""),
        "parent_url": f"{BASE_URL}{topic.get('parentUrl', '')}" if topic.get("parentUrl") else "",
        "fetched_at": fetched_at,
    }


def flatten_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []

    def visit(comment: dict[str, Any], parent_id: int | None, depth: int) -> None:
        author = comment.get("author", {}) or {}
        votes = comment.get("votes", {}) or {}
        flat.append(
            {
                "comment_id": comment.get("id"),
                "parent_comment_id": parent_id,
                "depth": depth,
                "post_date": comment.get("postDate", ""),
                "raw_markdown": comment.get("rawMarkdown", ""),
                "content_html": comment.get("content", ""),
                "author_display_name": author.get("displayName", ""),
                "author_url": f"{BASE_URL}{author.get('url', '')}" if author.get("url") else "",
                "author_tier": author.get("tier", ""),
                "author_id": author.get("id", ""),
                "author_type": comment.get("authorType", ""),
                "total_votes": votes.get("totalVotes", 0),
                "total_upvotes": votes.get("totalUpvotes", 0),
                "competition_ranking": comment.get("competitionRanking", None),
                "is_thank_you": comment.get("isThankYou", False),
            }
        )
        for reply in comment.get("replies", []) or []:
            visit(reply, comment.get("id"), depth + 1)

    for comment in comments:
        visit(comment, None, 0)
    return flat


def render_thread_raw_markdown(topic: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# {topic.get('name', '')}")
    lines.append("")
    lines.append(f"- topic_id: `{topic.get('id', '')}`")
    lines.append(f"- forum_id: `{topic.get('forumId', '')}`")
    lines.append(f"- url: `{BASE_URL}{topic.get('url', '')}`")
    lines.append(f"- post_date: `{topic.get('postDate', '')}`")
    lines.append(f"- total_votes: `{topic.get('totalVotes', 0)}`")
    lines.append(f"- total_messages: `{topic.get('totalMessages', 0)}`")
    lines.append("")
    first_message = topic.get("firstMessage", {}) or {}
    lines.append("## Original Post")
    lines.append("")
    lines.append(str(first_message.get("rawMarkdown", "")).strip())
    lines.append("")
    lines.append("## Comments")
    lines.append("")

    def visit(comment: dict[str, Any], depth: int) -> None:
        author = (comment.get("author") or {}).get("displayName", "")
        prefix = "#" * min(6, 3 + depth)
        lines.append(f"{prefix} Comment {comment.get('id', '')}")
        lines.append("")
        lines.append(f"- author: `{author}`")
        lines.append(f"- post_date: `{comment.get('postDate', '')}`")
        lines.append("")
        lines.append(str(comment.get("rawMarkdown", "")).strip())
        lines.append("")
        for reply in comment.get("replies", []) or []:
            visit(reply, depth + 1)

    for comment in topic.get("comments", []) or []:
        visit(comment, 0)
    return "\n".join(lines).strip() + "\n"


def fetch_topic_index(
    client: KaggleDiscussionsClient,
    competition: dict[str, Any],
    max_pages: int,
    fetched_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    forum_id = int(competition["forumId"])
    page_rows: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for page in range(1, max_pages + 1):
        payload = client.get_topics(forum_id=forum_id, page=page)
        topics = payload.get("topics", []) or []
        if not topics:
            break
        for topic in topics:
            topic = dict(topic)
            topic["page"] = page
            page_rows.append(topic)
            topic_id = int(topic["id"])
            if topic_id in seen_ids:
                continue
            seen_ids.add(topic_id)
            normalized_rows.append(normalize_topic_index_row(topic, fetched_at=fetched_at, competition=competition))
    return page_rows, normalized_rows


def render_summary(competition: dict[str, Any], rows: list[dict[str, Any]], fetched_at: str) -> str:
    sorted_rows = sorted(rows, key=lambda row: (int(row["is_sticky"]), int(row["votes"]), int(row["comment_count"])), reverse=True)
    lines = [
        "# Discussion Summary",
        "",
        f"- competition: `{competition.get('competitionName')}`",
        f"- title: `{competition.get('title')}`",
        f"- competition_id: `{competition.get('id')}`",
        f"- forum_id: `{competition.get('forumId')}`",
        f"- fetched_at: `{fetched_at}`",
        f"- topics: `{len(rows)}`",
        "",
        "## Topics",
        "",
        "| id | title | comments | votes | sticky | author | url |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted_rows:
        title = str(row["title"]).replace("|", "/")
        lines.append(
            f"| `{row['topic_id']}` | {title} | `{row['comment_count']}` | `{row['votes']}` | `{row['is_sticky']}` | {row['author_display_name']} | {row['topic_url']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull Kaggle competition discussion topics and thread details.")
    parser.add_argument("--competition", default=DEFAULT_COMPETITION)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--skip-topic-details", action="store_true")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    snapshot_dir = output_root / "snapshots" / utc_timestamp()
    latest_dir = output_root / "latest"
    ensure_dir(snapshot_dir)
    ensure_dir(latest_dir)

    fetched_at = utc_now_iso()
    client = KaggleDiscussionsClient()

    competition = client.get_competition(args.competition)
    forum = client.get_forum(int(competition["forumId"]))
    raw_topics, index_rows = fetch_topic_index(
        client=client,
        competition=competition,
        max_pages=args.max_pages,
        fetched_at=fetched_at,
    )

    write_json(snapshot_dir / "competition.json", competition)
    write_json(snapshot_dir / "forum.json", forum)
    write_json(snapshot_dir / "raw_topics.json", raw_topics)

    index_fieldnames = [
        "topic_id",
        "forum_id",
        "competition_name",
        "competition_title",
        "title",
        "topic_url",
        "author_display_name",
        "author_url",
        "author_tier",
        "author_id",
        "author_type",
        "post_date",
        "last_comment_post_date",
        "last_commenter_name",
        "last_commenter_url",
        "comment_count",
        "votes",
        "is_sticky",
        "first_forum_message_id",
        "parent_name",
        "parent_url",
        "fetched_at",
    ]
    write_csv(snapshot_dir / "index.csv", index_rows, index_fieldnames)
    (snapshot_dir / "summary.md").write_text(render_summary(competition, index_rows, fetched_at), encoding="utf-8")

    if not args.skip_topic_details:
        threads_dir = snapshot_dir / "threads"
        raw_threads_dir = snapshot_dir / "raw_threads"
        markdown_threads_dir = snapshot_dir / "markdown_threads"
        ensure_dir(threads_dir)
        ensure_dir(raw_threads_dir)
        ensure_dir(markdown_threads_dir)
        for row in index_rows:
            topic_id = int(row["topic_id"])
            detail = client.get_topic_detail(topic_id=topic_id, include_comments=True)
            forum_topic = detail.get("forumTopic", {}) or {}
            comments = forum_topic.get("comments", []) or []
            payload = {
                "topic": forum_topic,
                "comments_flat": flatten_comments(comments),
                "fetched_at": fetched_at,
                "topic_id": topic_id,
                "content_hash": content_hash(
                    {
                        "topic_id": topic_id,
                        "name": forum_topic.get("name", ""),
                        "comments": comments,
                        "totalVotes": forum_topic.get("totalVotes", 0),
                        "totalMessages": forum_topic.get("totalMessages", 0),
                    }
                ),
            }
            write_json(raw_threads_dir / f"{topic_id}.json", detail)
            write_json(threads_dir / f"{topic_id}.json", payload)
            write_text(markdown_threads_dir / f"{topic_id}.md", render_thread_raw_markdown(forum_topic))

    run_info = {
        "competition": args.competition,
        "competition_id": competition.get("id"),
        "forum_id": competition.get("forumId"),
        "fetched_at": fetched_at,
        "max_pages": args.max_pages,
        "topics": len(index_rows),
        "skip_topic_details": args.skip_topic_details,
    }
    write_json(snapshot_dir / "run_info.json", run_info)

    for src_name, dst_name in [
        ("competition.json", "competition.json"),
        ("forum.json", "forum.json"),
        ("index.csv", "index.csv"),
        ("summary.md", "summary.md"),
        ("run_info.json", "run_info.json"),
    ]:
        latest_dir.joinpath(dst_name).write_bytes(snapshot_dir.joinpath(src_name).read_bytes())

    if not args.skip_topic_details:
        latest_threads_dir = latest_dir / "threads"
        latest_raw_threads_dir = latest_dir / "raw_threads"
        latest_markdown_threads_dir = latest_dir / "markdown_threads"
        ensure_dir(latest_threads_dir)
        ensure_dir(latest_raw_threads_dir)
        ensure_dir(latest_markdown_threads_dir)
        for thread_file in (snapshot_dir / "threads").glob("*.json"):
            latest_threads_dir.joinpath(thread_file.name).write_bytes(thread_file.read_bytes())
        for thread_file in (snapshot_dir / "raw_threads").glob("*.json"):
            latest_raw_threads_dir.joinpath(thread_file.name).write_bytes(thread_file.read_bytes())
        for thread_file in (snapshot_dir / "markdown_threads").glob("*.md"):
            latest_markdown_threads_dir.joinpath(thread_file.name).write_bytes(thread_file.read_bytes())

    print(json.dumps(run_info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
