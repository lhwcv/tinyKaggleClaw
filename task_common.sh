#!/usr/bin/env bash
# Shared constants and helpers for clean.sh / restart.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
cd "${SCRIPT_DIR}"

TASK_DIRS=(.research-mvp-data src output eda logs docs baseline)
RESUME_DIR="${SCRIPT_DIR}/resume"

has_task_content() {
  for dir in "${TASK_DIRS[@]}"; do
    if [[ -d "$dir" ]] && [[ -n "$(ls -A "$dir" 2>/dev/null)" ]]; then
      return 0
    fi
  done
  return 1
}

archive_task() {
  local dest="${RESUME_DIR}/$(date +'%y%m%d-%H%M')"

  if [[ -d "$dest" ]]; then
    echo "Error: '$dest' already exists, wait a minute or remove it." >&2
    exit 1
  fi

  mkdir -p "$dest"

  local moved=0
  for dir in "${TASK_DIRS[@]}"; do
    if [[ -d "$dir" ]] && [[ -n "$(ls -A "$dir" 2>/dev/null)" ]]; then
      mv "$dir" "$dest/"
      mkdir -p "$dir"
      echo "  archived: $dir -> $dest/$dir"
      moved=$((moved + 1))
    fi
  done

  if (( moved == 0 )); then
    rmdir "$dest"
    echo "Nothing to archive — all task directories are empty."
  else
    echo "Archived $moved dir(s) to $dest"
  fi
}
