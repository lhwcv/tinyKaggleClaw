#!/usr/bin/env python3
"""Monitor runtime thread activity and nudge the leader after prolonged idle periods."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MESSAGE = "Keep iterating and continue improving from here."
ACTIVE_SENDERS = {"leader", "researcher", "trainer"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_thread_rows(thread_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not thread_path.exists():
        return rows
    for line in thread_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    rows.sort(key=lambda row: str(row.get("timestamp", "")))
    return rows


def latest_activity_at(rows: list[dict[str, Any]]) -> datetime | None:
    for row in reversed(rows):
        sender = str(row.get("from", ""))
        if sender not in ACTIVE_SENDERS:
            continue
        ts = parse_ts(str(row.get("timestamp", "")))
        if ts is not None:
            return ts
    return None


def should_notify(
    rows: list[dict[str, Any]],
    idle_seconds: int,
    cooldown_seconds: int,
    message: str,
    state: dict[str, Any],
) -> bool:
    last_activity = latest_activity_at(rows)
    if last_activity is None:
        return False

    idle_for = (datetime.now(timezone.utc) - last_activity).total_seconds()
    if idle_for < idle_seconds:
        return False

    last_sent = parse_ts(str(state.get("last_sent_at", "")))
    if last_sent is not None:
        if (datetime.now(timezone.utc) - last_sent).total_seconds() < cooldown_seconds:
            return False

    last_sent_activity = str(state.get("last_activity_at", ""))
    if last_sent_activity == last_activity.isoformat():
        return False

    for row in reversed(rows):
        sender = str(row.get("from", ""))
        recipient = str(row.get("to", ""))
        content = str(row.get("content", ""))
        ts = parse_ts(str(row.get("timestamp", "")))
        if ts is None:
            continue
        if sender == "human" and recipient == "leader" and content.strip() == message.strip():
            if (datetime.now(timezone.utc) - ts).total_seconds() < cooldown_seconds:
                return False
            break

    return True


def send_nudge(config_path: Path, message: str) -> None:
    cmd = [
        "python",
        "-m",
        "research_mvp.runtime_cli",
        "--config",
        str(config_path),
        "thread",
        "send",
        "--from",
        "system",
        "--to",
        "leader",
        message,
    ]
    subprocess.run(cmd, check=True)


def run_monitor(
    config_path: Path,
    thread_path: Path,
    state_path: Path,
    idle_seconds: int,
    cooldown_seconds: int,
    poll_seconds: int,
    message: str,
) -> int:
    while True:
        rows = read_thread_rows(thread_path)
        state = load_json(state_path, default={})
        last_activity = latest_activity_at(rows)

        if should_notify(rows, idle_seconds, cooldown_seconds, message, state):
            send_nudge(config_path, message)
            state["last_sent_at"] = now_iso()
            if last_activity is not None:
                state["last_activity_at"] = last_activity.isoformat()
            state["last_message"] = message
            save_json(state_path, state)
        else:
            if last_activity is not None and state.get("observed_activity_at") != last_activity.isoformat():
                state["observed_activity_at"] = last_activity.isoformat()
                save_json(state_path, state)

        time.sleep(poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor runtime idleness and nudge leader.")
    parser.add_argument("--config", required=True, help="Path to runtime.toml")
    parser.add_argument("--thread", required=True, help="Path to runtime thread.jsonl")
    parser.add_argument("--state", required=True, help="Path to monitor state json")
    parser.add_argument("--idle-seconds", type=int, default=900, help="Idle threshold before nudging leader.")
    parser.add_argument("--cooldown-seconds", type=int, default=1800, help="Minimum gap between nudges.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Polling interval.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="Message to send to leader.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_monitor(
        config_path=Path(args.config).expanduser().resolve(),
        thread_path=Path(args.thread).expanduser().resolve(),
        state_path=Path(args.state).expanduser().resolve(),
        idle_seconds=args.idle_seconds,
        cooldown_seconds=args.cooldown_seconds,
        poll_seconds=args.poll_seconds,
        message=args.message,
    )


if __name__ == "__main__":
    raise SystemExit(main())
