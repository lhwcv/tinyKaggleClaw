#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/task_common.sh"

clean_task() {
  for dir in "${TASK_DIRS[@]}"; do
    [[ -d "$dir" ]] && find "$dir" -mindepth 1 -delete
  done
  echo "Cleaned all task outputs."
}

usage() {
  cat <<'EOF'
Usage:
  ./clean.sh                # delete all task outputs
  ./clean.sh clean          # same as above
  ./clean.sh archive        # move all task outputs to resume/YYMMDD-HHMM/

Examples:
  ./clean.sh archive        # -> resume/260403-1520/
  ./clean.sh clean
EOF
}

cmd="${1:-clean}"
case "$cmd" in
  clean)
    clean_task
    ;;
  archive)
    archive_task
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage
    exit 1
    ;;
esac
