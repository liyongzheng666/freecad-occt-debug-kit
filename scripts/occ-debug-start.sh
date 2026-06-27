#!/usr/bin/env bash
# =====================================================================
# occ-debug-start — orchestrate an OCC debug session's producer side and manage
# the occ-mesh-daemon lifecycle (docs/occ-mesh-daemon-plan.md §2/§5 N7).
#
# Readiness order (the "F5" entry): ensure the mesher is built -> ensure the
# session dir -> start the daemon in the background with a PID file + health
# check -> (optionally) seed a baseline / hand off to lldb.
#
# N7 (daemon lifecycle): the daemon runs detached; its PID is recorded so a
# crash is VISIBLE (status reports dead + shows the log tail) and it is cleanly
# restartable. Bridge/viewer are started separately (they never call kit bins).
#
#   Usage:
#     scripts/occ-debug-start.sh [start|stop|restart|status] [options]
#       start (default)  build-if-needed, ensure session, launch daemon, verify
#       stop             SIGTERM the recorded daemon, wait, clean the PID file
#       restart          stop then start
#       status           report daemon alive/dead, PID, and event count
#
#   Options:
#     --session DIR   session dir (default: $OCC_DEBUG_SESSION or .occ-debug/sessions/dev)
#     --interval S    daemon poll interval seconds (default: 0.2)
#     --with-uv       pass --with-uv to the daemon (fold geom UV into updates)
#     --baseline      seed a fake baseline+debug scene (offline demo, no lldb)
#
#   Files (under <session>/):
#     .occ-mesh-daemon.pid   the running daemon's PID
#     occ-mesh-daemon.log    the daemon's stdout/stderr
# =====================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SESSION="${OCC_DEBUG_SESSION:-.occ-debug/sessions/dev}"
INTERVAL="0.2"
UV_FLAG=""
DO_BASELINE=0
CMD="start"

while [[ $# -gt 0 ]]; do
  case "$1" in
    start|stop|restart|status) CMD="$1"; shift ;;
    --session) SESSION="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --with-uv) UV_FLAG="--with-uv"; shift ;;
    --baseline) DO_BASELINE=1; shift ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "[occ-debug-start] unknown arg: $1" >&2; exit 2 ;;
  esac
done

DAEMON="$ROOT/scripts/occ-mesh-daemon.py"
MESHER="${OCC_DEBUG_MESH_BIN:-$ROOT/tools/occ-debug-mesh/build/occ-debug-mesh}"
PID_FILE="$SESSION/.occ-mesh-daemon.pid"
LOG_FILE="$SESSION/occ-mesh-daemon.log"

daemon_pid() { [[ -f "$PID_FILE" ]] && cat "$PID_FILE" || true; }
daemon_alive() {
  local pid; pid="$(daemon_pid)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

ensure_mesher() {
  if [[ ! -x "$MESHER" ]]; then
    echo "[occ-debug-start] mesher missing; building…"
    scripts/build-occ-debug-mesh.sh
  fi
}

start() {
  ensure_mesher
  mkdir -p "$SESSION/assets"
  if daemon_alive; then
    echo "[occ-debug-start] already running (pid $(daemon_pid))  session=$SESSION"
    return 0
  fi
  rm -f "$PID_FILE"  # stale PID from a previous crash

  if [[ "$DO_BASELINE" == 1 ]]; then
    echo "[occ-debug-start] seeding baseline scene…"
    scripts/fake-occ-session.py --session "$SESSION" --once >/dev/null
  fi

  echo "[occ-debug-start] launching daemon…" >>"$LOG_FILE"
  nohup "$DAEMON" --session "$SESSION" --interval "$INTERVAL" $UV_FLAG >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"

  # Health check: a daemon that can't find the mesher (or crashes on startup)
  # exits within a moment — surface it instead of leaving a dead PID file (N7).
  sleep 0.5
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "[occ-debug-start] daemon FAILED to start — log tail:" >&2
    tail -n 20 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    return 1
  fi
  echo "[occ-debug-start] daemon up (pid $pid)  session=$SESSION  log=$LOG_FILE"
  echo "[occ-debug-start] next: tools/Print/bridge/bridge.py --session $SESSION --port 7341  +  (cd tools/Print && npm run dev)"
}

stop() {
  local pid; pid="$(daemon_pid)"
  if [[ -z "$pid" ]]; then
    echo "[occ-debug-start] no PID file; nothing to stop"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "[occ-debug-start] daemon $pid did not exit on SIGTERM; sending SIGKILL" >&2
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "[occ-debug-start] stopped daemon (pid $pid)"
  else
    echo "[occ-debug-start] daemon (pid $pid) was not running (stale PID file)"
  fi
  rm -f "$PID_FILE"
}

status() {
  local pid; pid="$(daemon_pid)"
  local events="$SESSION/events.ndjson"
  local n=0
  [[ -f "$events" ]] && n="$(grep -c . "$events" 2>/dev/null || echo 0)"
  if daemon_alive; then
    echo "[occ-debug-start] RUNNING  pid=$pid  session=$SESSION  events=$n  log=$LOG_FILE"
  elif [[ -n "$pid" ]]; then
    echo "[occ-debug-start] DEAD  (stale pid=$pid)  session=$SESSION  events=$n" >&2
    [[ -f "$LOG_FILE" ]] && { echo "--- log tail ---" >&2; tail -n 10 "$LOG_FILE" >&2; }
    return 1
  else
    echo "[occ-debug-start] STOPPED  session=$SESSION  events=$n"
  fi
}

case "$CMD" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status ;;
esac
