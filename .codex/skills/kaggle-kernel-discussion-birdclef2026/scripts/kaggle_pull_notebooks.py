from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_COMPETITION = "birdclef-2026"
DEFAULT_OUTPUT_ROOT = Path("kaggle_info/notebooks")
DEFAULT_SORTS = ("scoreDescending", "voteCount", "dateRun", "hotness")
DEFAULT_KAGGLE_BIN = str(Path.home() / ".local" / "bin" / "kaggle")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _snake_case(value: str) -> str:
    value = value.strip()
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    return value.strip("_").lower()


def _resolve_kaggle_bin(explicit_bin: str) -> str:
    if explicit_bin:
        if Path(explicit_bin).expanduser().exists():
            return str(Path(explicit_bin).expanduser())
        found = shutil.which(explicit_bin)
        if found:
            return found
    found = shutil.which("kaggle")
    if found:
        return found
    if Path(DEFAULT_KAGGLE_BIN).exists():
        return DEFAULT_KAGGLE_BIN
    raise SystemExit(
        "Missing `kaggle` CLI. Install it first, then configure authentication.\n"
        "Docs: https://github.com/Kaggle/kaggle-api"
    )


def _require_kaggle_cli(kaggle_bin: str) -> None:
    if not Path(kaggle_bin).expanduser().exists() and shutil.which(kaggle_bin) is None:
        raise SystemExit(
            "Missing `kaggle` CLI. Install it first, then configure authentication.\n"
            "Docs: https://github.com/Kaggle/kaggle-api"
        )


def _run_csv_command(cmd: list[str]) -> list[dict[str, str]]:
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    text = result.stdout.strip()
    if not text:
        return []
    reader = csv.DictReader(text.splitlines())
    return [dict(row) for row in reader]


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_row(
    row: dict[str, str],
    competition: str,
    sort_by: str,
    page: int,
    fetched_at: str,
) -> dict[str, object]:
    normalized = {_snake_case(key): value for key, value in row.items()}
    ref = str(row.get("ref", "")).strip()
    owner = ref.split("/", 1)[0] if "/" in ref else ""
    slug = ref.split("/", 1)[1] if "/" in ref else ref
    normalized["ref"] = ref
    normalized["owner"] = owner
    normalized["slug"] = slug
    normalized["notebook_url"] = f"https://www.kaggle.com/code/{ref}" if ref else ""
    normalized["competition"] = competition
    normalized["sort_by"] = sort_by
    normalized["page"] = page
    normalized["fetched_at"] = fetched_at
    normalized["score_value"] = _extract_score_value(normalized)
    normalized["score_source_column"] = _extract_score_column(normalized)
    return normalized


def _extract_score_column(row: dict[str, object]) -> str:
    preferred = [
        "score",
        "best_score",
        "public_score",
        "private_score",
        "leaderboard_score",
        "best_public_score",
        "best_private_score",
    ]
    for key in preferred:
        if key in row and str(row.get(key, "")).strip():
            return key
    for key, value in row.items():
        if "score" in key and str(value).strip():
            return key
    return ""


def _extract_score_value(row: dict[str, object]) -> str:
    key = _extract_score_column(row)
    return str(row.get(key, "")).strip() if key else ""


def _dedupe_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_ref: OrderedDict[str, dict[str, object]] = OrderedDict()
    for row in rows:
        ref = str(row.get("ref", "")).strip()
        if not ref:
            continue
        current = by_ref.get(ref)
        if current is None:
            by_ref[ref] = row
            continue
        if _row_priority(row) > _row_priority(current):
            by_ref[ref] = row
    return list(by_ref.values())


def _safe_float(value: object) -> float:
    text = str(value).strip()
    if not text:
        return float("-inf")
    try:
        return float(text)
    except ValueError:
        return float("-inf")


def _safe_int(value: object) -> int:
    text = str(value).strip()
    if not text:
        return -1
    try:
        return int(float(text))
    except ValueError:
        return -1


def _row_priority(row: dict[str, object]) -> tuple[float, int, int]:
    return (
        _safe_float(row.get("score_value", "")),
        _safe_int(row.get("total_votes", row.get("totalvotes", ""))),
        -_safe_int(row.get("page", "")),
    )


def _render_summary(rows: list[dict[str, object]], competition: str, fetched_at: str) -> str:
    lines = [
        f"# Notebook Tracking Summary",
        "",
        f"- competition: `{competition}`",
        f"- fetched_at: `{fetched_at}`",
        f"- unique_notebooks: `{len(rows)}`",
        "",
        "## Top notebooks by score",
        "",
        "| ref | title | score | votes | last_run | url |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    ranked = sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("score_value", "")),
            _safe_int(row.get("total_votes", row.get("totalvotes", ""))),
        ),
        reverse=True,
    )
    shown = 0
    for row in ranked:
        if shown >= 30:
            break
        ref = str(row.get("ref", ""))
        title = str(row.get("title", "")).replace("|", "/")
        score = str(row.get("score_value", ""))
        votes = str(row.get("total_votes", row.get("totalvotes", "")))
        last_run = str(row.get("last_run_time", row.get("lastruntime", "")))
        url = str(row.get("notebook_url", ""))
        lines.append(f"| `{ref}` | {title} | `{score}` | `{votes}` | `{last_run}` | {url} |")
        shown += 1
    if shown == 0:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `score_value` is extracted from any Kaggle CLI field containing `score`.",
            "- If Kaggle CLI does not expose a score field for a notebook, the score is left blank.",
            "- Raw Kaggle CSV pages are preserved under `snapshots/<timestamp>/raw/`.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _pull_notebook(ref: str, pull_dir: Path) -> None:
    pull_dir.mkdir(parents=True, exist_ok=True)
    cmd = [KAGGLE_BIN, "kernels", "pull", ref, "-p", str(pull_dir), "-m"]
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull Kaggle competition notebooks and track score-related metadata.")
    parser.add_argument("--competition", default=DEFAULT_COMPETITION)
    parser.add_argument("--kaggle-bin", default=DEFAULT_KAGGLE_BIN)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--sort-by", nargs="*", default=list(DEFAULT_SORTS))
    parser.add_argument("--kernel-type", default="notebook", choices=["all", "script", "notebook"])
    parser.add_argument("--language", default="all")
    parser.add_argument("--pull-top-n", type=int, default=0)
    parser.add_argument("--pull-sort", default="score")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    global KAGGLE_BIN
    KAGGLE_BIN = _resolve_kaggle_bin(args.kaggle_bin)
    _require_kaggle_cli(KAGGLE_BIN)

    output_root = Path(args.output_root)
    fetched_at = _utc_timestamp()
    snapshot_dir = output_root / "snapshots" / fetched_at
    raw_dir = snapshot_dir / "raw"
    pulled_dir = output_root / "pulled"

    all_raw_rows: list[dict[str, object]] = []
    all_normalized_rows: list[dict[str, object]] = []

    for sort_by in args.sort_by:
        for page in range(1, args.max_pages + 1):
            cmd = [
                KAGGLE_BIN,
                "kernels",
                "list",
                "--competition",
                args.competition,
                "--page-size",
                str(args.page_size),
                "--page",
                str(page),
                "--sort-by",
                sort_by,
                "--language",
                args.language,
                "--kernel-type",
                args.kernel_type,
                "--csv",
            ]
            rows = _run_csv_command(cmd)
            if not rows:
                break
            raw_fieldnames = sorted({key for row in rows for key in row.keys()} | {"sort_by", "page", "fetched_at"})
            raw_rows = []
            for row in rows:
                enriched = dict(row)
                enriched["sort_by"] = sort_by
                enriched["page"] = page
                enriched["fetched_at"] = fetched_at
                raw_rows.append(enriched)
                all_raw_rows.append(enriched)
                all_normalized_rows.append(
                    _normalize_row(
                        row,
                        competition=args.competition,
                        sort_by=sort_by,
                        page=page,
                        fetched_at=fetched_at,
                    )
                )
            _write_csv(raw_dir / f"kernels_list_{_slugify(sort_by)}_page_{page}.csv", raw_rows, raw_fieldnames)
            if len(rows) < args.page_size:
                break

    deduped_rows = _dedupe_rows(all_normalized_rows)
    normalized_fieldnames = sorted({key for row in deduped_rows for key in row.keys()})
    raw_fieldnames = sorted({key for row in all_raw_rows for key in row.keys()})

    _write_csv(snapshot_dir / "kernels_raw_combined.csv", all_raw_rows, raw_fieldnames)
    _write_csv(snapshot_dir / "kernels_normalized.csv", deduped_rows, normalized_fieldnames)
    _write_json(
        snapshot_dir / "run_info.json",
        {
            "competition": args.competition,
            "fetched_at": fetched_at,
            "page_size": args.page_size,
            "max_pages": args.max_pages,
            "sort_by": args.sort_by,
            "kernel_type": args.kernel_type,
            "language": args.language,
            "raw_rows": len(all_raw_rows),
            "unique_refs": len(deduped_rows),
        },
    )
    (snapshot_dir / "summary.md").write_text(
        _render_summary(deduped_rows, competition=args.competition, fetched_at=fetched_at),
        encoding="utf-8",
    )

    latest_dir = output_root / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot_dir / "kernels_raw_combined.csv", latest_dir / "kernels_raw_combined.csv")
    shutil.copy2(snapshot_dir / "kernels_normalized.csv", latest_dir / "kernels_normalized.csv")
    shutil.copy2(snapshot_dir / "summary.md", latest_dir / "summary.md")
    shutil.copy2(snapshot_dir / "run_info.json", latest_dir / "run_info.json")

    if args.pull_top_n > 0 and not args.dry_run:
        if args.pull_sort == "score":
            ranked = sorted(
                deduped_rows,
                key=lambda row: (
                    _safe_float(row.get("score_value", "")),
                    _safe_int(row.get("total_votes", row.get("totalvotes", ""))),
                ),
                reverse=True,
            )
        else:
            ranked = sorted(
                deduped_rows,
                key=lambda row: _safe_int(row.get("total_votes", row.get("totalvotes", ""))),
                reverse=True,
            )
        selected = [row for row in ranked if str(row.get("ref", "")).strip()][: args.pull_top_n]
        for row in selected:
            ref = str(row["ref"])
            owner = str(row.get("owner", "unknown")) or "unknown"
            slug = str(row.get("slug", "unknown")) or "unknown"
            pull_path = pulled_dir / owner / slug
            _pull_notebook(ref, pull_path)

    print(
        json.dumps(
            {
                "status": "ok",
                "competition": args.competition,
                "output_root": str(output_root),
                "snapshot_dir": str(snapshot_dir),
                "unique_refs": len(deduped_rows),
                "pull_top_n": args.pull_top_n,
                "dry_run": args.dry_run,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
