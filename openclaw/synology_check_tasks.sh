#!/usr/bin/env bash
# Synology Task Scheduler API health check - runs independently
set -euo pipefail

PATH="/home/linuxbrew/.linuxbrew/bin:/home/moltbot/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
MCPORTER_BIN="${MCPORTER_BIN:-mcporter}"
TIMEOUT_SEC="${TIMEOUT_SEC:-90}"

call_tool() {
  local tool="$1" args="$2"
  timeout "${TIMEOUT_SEC}s" "$MCPORTER_BIN" call "$tool" --args "$args" --output json
}

emit() {
  local level="$1" check="$2" message="$3"
  jq -nc --arg level "$level" --arg check "$check" --arg message "$message" '{level:$level,check:$check,message:$message}'
}

ok() { emit "ok" "$1" "$2"; exit 0; }
warn() { emit "warn" "$1" "$2"; exit 0; }
crit() { emit "crit" "$1" "$2" >&2; exit 2; }

is_json() { jq -e . >/dev/null 2>&1 <<<"$1"; }
strip_mcporter_trailer() { printf '%s\n' "$1" | sed '/^\[mcporter\] /,$d'; }

call_json() {
  local check="$1" tool="$2" args="$3" raw out
  if ! raw="$(call_tool "$tool" "$args" 2>&1)"; then
    crit "$check" "tool call failed: $tool"
  fi
  out="$(strip_mcporter_trailer "$raw")"
  if ! is_json "$out"; then
    crit "$check" "non-JSON response from $tool"
  fi
  if jq -e '.isError == true' >/dev/null <<<"$out"; then
    local msg; msg="$(jq -r '.message // .error_message // .error.message // "tool error"' <<<"$out")"
    # Known expected error: List scheduled tasks failed
    if [[ "$msg" == *"List scheduled tasks failed"* ]]; then
      warn "$check" "task_scheduler_api_failure"
    else
      crit "$check" "$msg"
    fi
  fi
  ok "$check" "task_scheduler_api_healthy"
}

check_tasks() {
  local check="task_scheduler"
  call_json "$check" "synology.synology_scheduled_tasks_list" '{"params":{}}'
}

check_tasks
