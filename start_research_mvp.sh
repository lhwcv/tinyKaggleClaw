#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

LOG_DIR="${SCRIPT_DIR}/logs"
PID_DIR="${LOG_DIR}/pids"
RUNTIME_CONFIG="${SCRIPT_DIR}/research_mvp/runtime.toml"

APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8090}"
TRAIN_SERVICE_HOST="${TRAIN_SERVICE_HOST:-0.0.0.0}"
TRAIN_SERVICE_PORT="${TRAIN_SERVICE_PORT:-8100}"

mkdir -p "${LOG_DIR}" "${PID_DIR}"

runtime_pid_file="${PID_DIR}/research_mvp_runtime.pid"
app_pid_file="${PID_DIR}/research_mvp_app.pid"
train_service_pid_file="${PID_DIR}/research_mvp_train_service.pid"

runtime_log="${LOG_DIR}/research_mvp_runtime.log"
app_log="${LOG_DIR}/research_mvp_app.log"
train_service_log="${LOG_DIR}/research_mvp_train_service.log"

is_pid_alive() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

read_pid() {
  local pid_file="$1"
  if [[ -f "${pid_file}" ]]; then
    tr -d '[:space:]' < "${pid_file}"
  fi
}

cleanup_pid_file_if_dead() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "${pid_file}")"
  if [[ -n "${pid}" ]] && ! is_pid_alive "${pid}"; then
    rm -f "${pid_file}"
  fi
}

start_bg() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  cleanup_pid_file_if_dead "${pid_file}"
  local existing_pid
  existing_pid="$(read_pid "${pid_file}")"
  if [[ -n "${existing_pid}" ]] && is_pid_alive "${existing_pid}"; then
    echo "${name} already running, pid=${existing_pid}"
    return 0
  fi

  echo "Starting ${name} ..."
  nohup "$@" >> "${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" > "${pid_file}"
  sleep 1

  if is_pid_alive "${pid}"; then
    echo "${name} started, pid=${pid}, log=${log_file}"
    return 0
  fi

  echo "${name} failed to start, check log=${log_file}" >&2
  rm -f "${pid_file}"
  return 1
}

stop_bg() {
  local name="$1"
  local pid_file="$2"

  cleanup_pid_file_if_dead "${pid_file}"
  local pid
  pid="$(read_pid "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    echo "${name} not running"
    return 0
  fi

  if ! is_pid_alive "${pid}"; then
    rm -f "${pid_file}"
    echo "${name} already stopped"
    return 0
  fi

  echo "Stopping ${name}, pid=${pid} ..."
  kill "${pid}" 2>/dev/null || true
  for _ in {1..10}; do
    if ! is_pid_alive "${pid}"; then
      rm -f "${pid_file}"
      echo "${name} stopped"
      return 0
    fi
    sleep 1
  done

  echo "${name} did not exit in time, sending SIGKILL"
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
}

start_runtime() {
  start_bg \
    "runtime_cli up" \
    "${runtime_pid_file}" \
    "${runtime_log}" \
    python -m research_mvp.runtime_cli --config "${RUNTIME_CONFIG}" up
}

stop_runtime() {
  echo "Stopping runtime tmux session ..."
  python -m research_mvp.runtime_cli --config "${RUNTIME_CONFIG}" down >> "${runtime_log}" 2>&1 || true
  sleep 1
  if tmux has-session -t research-runtime 2>/dev/null; then
    echo "runtime session still exists after down, retrying once ..."
    python -m research_mvp.runtime_cli --config "${RUNTIME_CONFIG}" down >> "${runtime_log}" 2>&1 || true
    sleep 1
  fi
  stop_bg "runtime supervisor" "${runtime_pid_file}"
}

start_app() {
  start_bg \
    "research_mvp app" \
    "${app_pid_file}" \
    "${app_log}" \
    env \
    NO_PROXY="127.0.0.1,localhost" \
    no_proxy="127.0.0.1,localhost" \
    HTTP_PROXY="" \
    HTTPS_PROXY="" \
    ALL_PROXY="" \
    http_proxy="" \
    https_proxy="" \
    all_proxy="" \
    python -m uvicorn research_mvp.app:app --host "${APP_HOST}" --port "${APP_PORT}"
}

stop_app() {
  stop_bg "research_mvp app" "${app_pid_file}"
}

start_train_service() {
  start_bg \
    "train_service" \
    "${train_service_pid_file}" \
    "${train_service_log}" \
    env \
    NO_PROXY="127.0.0.1,localhost" \
    no_proxy="127.0.0.1,localhost" \
    HTTP_PROXY="" \
    HTTPS_PROXY="" \
    ALL_PROXY="" \
    http_proxy="" \
    https_proxy="" \
    all_proxy="" \
    python -m uvicorn research_mvp.train_service.app:app --host "${TRAIN_SERVICE_HOST}" --port "${TRAIN_SERVICE_PORT}"
}

stop_train_service() {
  stop_bg "train_service" "${train_service_pid_file}"
}

print_status_item() {
  local name="$1"
  local pid_file="$2"
  cleanup_pid_file_if_dead "${pid_file}"
  local pid
  pid="$(read_pid "${pid_file}")"
  if [[ -n "${pid}" ]] && is_pid_alive "${pid}"; then
    echo "${name}: running (pid=${pid})"
  else
    echo "${name}: stopped"
  fi
}

status_all() {
  print_status_item "runtime supervisor" "${runtime_pid_file}"
  print_status_item "research_mvp app" "${app_pid_file}"
  print_status_item "train_service" "${train_service_pid_file}"
  echo "Logs:"
  echo "  ${runtime_log}"
  echo "  ${app_log}"
  echo "  ${train_service_log}"
}

start_all() {
  start_runtime
  start_app
  start_train_service
  local runtime_board_url="http://${APP_HOST}:${APP_PORT}/runtime"
  local train_service_url="http://${TRAIN_SERVICE_HOST}:${TRAIN_SERVICE_PORT}/"
  echo "Research MVP started."
  echo "App: http://${APP_HOST}:${APP_PORT}/"
  echo "Train service: ${train_service_url}"
  echo
  echo "Open these pages:"
  echo "  Runtime board (talk to AI agents): ${runtime_board_url}"
  echo "  Training queue board: ${train_service_url}"
  echo
  echo "Tmux:"
  echo "  Attach runtime session: python -m research_mvp.runtime_cli --config ${RUNTIME_CONFIG} attach"
}

stop_all() {
  stop_runtime
  stop_app
  stop_train_service
  echo "Research MVP stopped."
}

usage() {
  cat <<'EOF'
Usage:
  ./start_research_mvp.sh start
  ./start_research_mvp.sh stop
  ./start_research_mvp.sh restart
  ./start_research_mvp.sh status

Optional env:
  APP_HOST=0.0.0.0
  APP_PORT=8090
  TRAIN_SERVICE_HOST=0.0.0.0
  TRAIN_SERVICE_PORT=8100
EOF
}

cmd="${1:-start}"

case "${cmd}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  *)
    usage
    exit 1
    ;;
esac
