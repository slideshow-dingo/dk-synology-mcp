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

first_content_text() {
  jq -r '
    [
      if (.content | type) == "array" then
        .content[]
        | if type == "object" then .text
          elif type == "string" then .
          else empty
          end
      else
        empty
      end
    ]
    | map(select(type == "string" and length > 0))
    | .[0] // empty
  ' <<<"$1" 2>/dev/null || true
}

json_error_message() {
  local out="$1" fallback="${2:-unknown error}" msg
  msg="$(jq -r '
    [
      .message,
      .error_message,
      .error.message,
      (if (.error | type) == "string" then .error else empty end),
      .details.message
    ]
    | map(select(type == "string" and length > 0))
    | .[0] // empty
  ' <<<"$out" 2>/dev/null || true)"
  if [[ -z "$msg" ]]; then
    msg="$(first_content_text "$out")"
  fi
  [[ -n "$msg" ]] && printf '%s\n' "$msg" && return 0
  printf '%s\n' "$fallback"
}

is_known_task_scheduler_api_issue() {
  local msg="$1"
  [[ "$msg" == *"API method unavailable"* ]] \
    || [[ "$msg" == *"requested method does not exist"* ]] \
    || [[ "$msg" == *"requested version does not support the functionality"* ]] \
    || [[ "$msg" == *"Task Scheduler API is not available"* ]]
}

call_json() {
  local check="$1" tool="$2" args="$3" raw out msg

  if ! raw="$(call_tool "$tool" "$args" 2>&1)"; then
    crit "$check" "tool call failed: $tool"
  fi

  out="$(strip_mcporter_trailer "$raw")"
  if ! is_json "$out"; then
    crit "$check" "non-JSON response from $tool"
  fi

  if jq -e '.isError == true or .status == "error"' >/dev/null <<<"$out"; then
    msg="$(json_error_message "$out" "tool error")"
    if is_known_task_scheduler_api_issue "$msg"; then
      warn "$check" "$msg"
    fi
    crit "$check" "$msg"
  fi

  printf '%s\n' "$out"
}

check_tasks() {
  local check="task_scheduler"
  call_json "$check" "synology.synology_scheduled_tasks_list" '{"params":{}}'
  ok "$check" "task_scheduler_api_healthy"
}

check_tasks
