#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/task_common.sh"

list_snapshots() {
  if [[ ! -d "$RESUME_DIR" ]] || [[ -z "$(ls -A "$RESUME_DIR" 2>/dev/null)" ]]; then
    echo "No snapshots in $RESUME_DIR"
    return 1
  fi
  echo "Available snapshots:"
  for d in "$RESUME_DIR"/*/; do
    [[ -d "$d" ]] && echo "  $(basename "$d")"
  done
}

restore_task() {
  local name="$1"
  local src="${RESUME_DIR}/${name}"

  if [[ ! -d "$src" ]]; then
    echo "Error: snapshot '$name' not found." >&2
    list_snapshots >&2
    exit 1
  fi

  if has_task_content; then
    echo "Current task dirs have content, archiving first..."
    archive_task
    echo
  fi

  echo "Restoring snapshot '$name'..."
  for dir in "${TASK_DIRS[@]}"; do
    if [[ -d "$src/$dir" ]]; then
      [[ -d "$dir" ]] && rmdir "$dir" 2>/dev/null || true
      mv "$src/$dir" "$dir"
      echo "  restored: $dir"
    fi
  done

  rmdir "$src" 2>/dev/null && echo "Removed empty snapshot dir '$name'" || true
  echo "Done."
}

usage() {
  cat <<'EOF'
Usage:
  ./restart.sh              # list available snapshots
  ./restart.sh <snapshot>   # restore a snapshot (archive current state first if non-empty)

Examples:
  ./restart.sh              # list
  ./restart.sh 260403-1126  # restore
EOF
}

if [[ -z "${1:-}" ]]; then
  list_snapshots
  exit 0
fi

case "$1" in
  -h|--help|help)
    usage
    ;;
  *)
    restore_task "$1"
    ;;
esac
