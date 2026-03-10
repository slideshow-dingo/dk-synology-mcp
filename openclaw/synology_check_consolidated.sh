#!/usr/bin/env bash
# Consolidated Synology health check - combines network + service_api_probe
# Runs both checks in a single cron invocation to reduce agent overhead
set -euo pipefail

PATH="/home/linuxbrew/.linuxbrew/bin:/home/moltbot/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

MCPORTER_BIN="${MCPORTER_BIN:-mcporter}"
TIMEOUT_SEC="${TIMEOUT_SEC:-90}"
DEBUG_LOG_DIR="${DEBUG_LOG_DIR:-$HOME/.openclaw/cron/state/synology-mcp}"
CONSOLIDATED_DEBUG_LOG="${CONSOLIDATED_DEBUG_LOG:-$DEBUG_LOG_DIR/consolidated.log}"

call_tool() {
  local tool="$1"
  local args="$2"
  timeout "${TIMEOUT_SEC}s" "$MCPORTER_BIN" call "$tool" --args "$args" --output json
}

emit() {
  local level="$1"
  local check="$2"
  local message="$3"
  jq -nc --arg level "$level" --arg check "$check" --arg message "$message" '{level:$level,check:$check,message:$message}'
}

ok() {
  emit "ok" "$1" "$2"
  exit 0
}

warn() {
  emit "warn" "$1" "$2"
  exit 0
}

crit() {
  emit "crit" "$1" "$2" >&2
  exit 2
}

is_json() {
  jq -e . >/dev/null 2>&1 <<<"$1"
}

compact_payload() {
  jq -c . <<<"$1" 2>/dev/null || printf '%s' "$1" | tr '\n\t' '  '
}

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
  local out="$1"
  local fallback="${2:-unknown error}"
  local msg
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

strip_mcporter_trailer() {
  printf '%s\n' "$1" | sed '/^\[mcporter\] /,$d'
}

call_json() {
  local check="$1"
  local tool="$2"
  local args="$3"
  local raw out

  if ! raw="$(call_tool "$tool" "$args" 2>&1)"; then
    crit "$check" "tool call failed: $tool"
  fi

  out="$(strip_mcporter_trailer "$raw")"
  if ! is_json "$out"; then
    crit "$check" "non-JSON response from $tool"
  fi

  if jq -e '.isError == true' >/dev/null <<<"$out"; then
    local msg
    msg="$(json_error_message "$out" "tool error")"
    crit "$check" "$msg"
  fi

  printf '%s\n' "$out"
}

log_debug() {
  local event="$1"
  local payload="$2"
  mkdir -p "$DEBUG_LOG_DIR" 2>/dev/null || true
  printf '%s\tevent=%s\tpayload=%s\n' "$(date -Is)" "$event" "$(compact_payload "$payload")" >> "$CONSOLIDATED_DEBUG_LOG"
}

check_network() {
  local check="network"
  local out gw dns

  out="$(call_json "$check" "synology.synology_network_info" '{"params":{}}')"

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "network info error"' <<<"$out")"
  fi

  gw="$(jq -r '.gateway // empty' <<<"$out")"
  dns="$(jq -r '.dns // empty' <<<"$out")"

  [[ -n "$gw" && -n "$dns" ]] || crit "$check" "missing gateway/dns"
  echo "network:ok:gateway=${gw}:dns=${dns}"
}

check_service_api_probe() {
  local check="service_api_probe"
  local out msg known=0 summary=""

  out="$(call_json "$check" "synology.synology_docker_list_containers" '{"params":{}}')"
  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    msg="$(jq -r '.message // ""' <<<"$out")"
    if [[ "$msg" == *"SYNO.Docker.Container"* ]]; then
      known=1
      summary+="docker_api_missing;"
    else
      crit "$check" "docker unexpected error: $msg"
    fi
  fi

  out="$(call_json "$check" "synology.synology_list_downloads" '{"params":{"offset":0,"limit":10}}')"
  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    msg="$(jq -r '.message // ""' <<<"$out")"
    if [[ "$msg" == *"get_list_of_tasks"* ]]; then
      known=1
      summary+="downloadstation_api_mismatch;"
    else
      crit "$check" "downloadstation unexpected error: $msg"
    fi
  fi

  out="$(call_json "$check" "synology.synology_backup_list" '{"params":{}}')"
  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    msg="$(jq -r '.message // ""' <<<"$out")"
    if [[ "$msg" == *"SYNO.Backup.Task"* ]]; then
      known=1
      summary+="hyperbackup_api_missing;"
    else
      crit "$check" "backup unexpected error: $msg"
    fi
  fi

  out="$(call_json "$check" "synology.synology_scheduled_tasks_list" '{"params":{}}')"
  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    msg="$(jq -r '.message // ""' <<<"$out")"
    if [[ "$msg" == *"List scheduled tasks failed"* ]]; then
      known=1
      summary+="task_scheduler_api_failure;"
    else
      crit "$check" "task scheduler unexpected error: $msg"
    fi
  fi

  if (( known == 1 )); then
    echo "service_api_probe:warn:${summary}"
    return 0
  fi

  echo "service_api_probe:ok:all_apis_healthy"
}

main() {
  local network_result api_result
  local network_status api_status
  local network_details api_details

  # Run both checks
  network_result="$(check_network)" || {
    local level msg
    level="$(echo "$network_result" | jq -r '.level')"
    msg="$(echo "$network_result" | jq -r '.message')"
    [[ "$level" == "crit" ]] && crit "consolidated" "$msg"
    [[ "$level" == "warn" ]] && warn "consolidated" "$msg"
  }

  api_result="$(check_service_api_probe)" || {
    local level msg
    level="$(echo "$api_result" | jq -r '.level')"
    msg="$(echo "$api_result" | jq -r '.message')"
    [[ "$level" == "crit" ]] && crit "consolidated" "$msg"
    [[ "$level" == "warn" ]] && warn "consolidated" "$msg"
  }

  # Parse results
  network_status="$(echo "$network_result" | cut -d: -f2)"
  network_details="$(echo "$network_result" | cut -d: -f3-)"
  api_status="$(echo "$api_result" | cut -d: -f2)"
  api_details="$(echo "$api_result" | cut -d: -f3-)"

  # Determine overall status
  if [[ "$network_status" == "ok" && "$api_status" == "ok" ]]; then
    ok "consolidated" "network=${network_details} | api=${api_details}"
  elif [[ "$network_status" == "warn" || "$api_status" == "warn" ]]; then
    warn "consolidated" "network=${network_details} | api=${api_details}"
  else
    crit "consolidated" "network=${network_details} | api=${api_details}"
  fi
}

main "$@"
