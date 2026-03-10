#!/usr/bin/env bash
set -euo pipefail

PATH="/home/linuxbrew/.linuxbrew/bin:/home/moltbot/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

MCPORTER_BIN="${MCPORTER_BIN:-mcporter}"
TIMEOUT_SEC="${TIMEOUT_SEC:-90}"
RETRY_BACKOFF_BASE="${RETRY_BACKOFF_BASE:-2}"
CLOUDSYNC_CONNECTION_ID="${CLOUDSYNC_CONNECTION_ID:-20}"
DEBUG_LOG_DIR="${DEBUG_LOG_DIR:-$HOME/.openclaw/cron/state/synology-mcp}"
CLOUDSYNC_DEBUG_LOG="${CLOUDSYNC_DEBUG_LOG:-$DEBUG_LOG_DIR/cloudsync_connection.log}"
STORAGE_DEBUG_LOG="${STORAGE_DEBUG_LOG:-$DEBUG_LOG_DIR/storage.log}"
HEALTH_DASHBOARD_DEBUG_LOG="${HEALTH_DASHBOARD_DEBUG_LOG:-$DEBUG_LOG_DIR/health_dashboard.log}"
UTILIZATION_DEBUG_LOG="${UTILIZATION_DEBUG_LOG:-$DEBUG_LOG_DIR/utilization.log}"

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

short_excerpt() {
  local text
  text="$(compact_payload "$1")"
  printf '%s\n' "${text:0:240}"
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

is_number() {
  [[ "$1" =~ ^-?[0-9]+([.][0-9]+)?$ ]]
}

is_percentage() {
  local value="$1"

  is_number "$value" || return 1
  awk -v value="$value" 'BEGIN { exit !((value + 0) >= 0 && (value + 0) <= 100) }'
}

debug_log_path_for_check() {
  local check="$1"
  case "$check" in
    cloudsync_connection) printf '%s\n' "$CLOUDSYNC_DEBUG_LOG" ;;
    storage) printf '%s\n' "$STORAGE_DEBUG_LOG" ;;
    health_dashboard) printf '%s\n' "$HEALTH_DASHBOARD_DEBUG_LOG" ;;
    utilization) printf '%s\n' "$UTILIZATION_DEBUG_LOG" ;;
    *) return 1 ;;
  esac
}

log_check_debug() {
  local check="$1"
  local event="$2"
  local attempt="$3"
  local payload="$4"
  local log_file compact

  if ! log_file="$(debug_log_path_for_check "$check")"; then
    return 0
  fi

  mkdir -p "$DEBUG_LOG_DIR" 2>/dev/null || true
  compact="$(compact_payload "$payload")"
  printf '%s\tevent=%s\tattempt=%s\tpayload=%s\n' "$(date -Is)" "$event" "$attempt" "$compact" >> "$log_file"
}

strip_mcporter_trailer() {
  printf '%s\n' "$1" | sed '/^\[mcporter\] /,$d'
}

json_error_message() {
  local out="$1"
  local fallback="${2:-unknown error}"
  local msg detail suggestion

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
  detail="$(jq -r '
    [
      .details,
      .detail,
      .details.reason,
      .details.error,
      .error.details
    ]
    | map(
        if type == "string" then .
        elif type == "number" then tostring
        else empty
        end
      )
    | map(select(length > 0))
    | .[0] // empty
  ' <<<"$out" 2>/dev/null || true)"
  suggestion="$(jq -r '
    [
      .suggestion,
      .details.suggestion
    ]
    | map(select(type == "string" and length > 0))
    | .[0] // empty
  ' <<<"$out" 2>/dev/null || true)"

  if [[ -n "$msg" ]]; then
    if [[ "$msg" =~ :[[:space:]]*$ ]]; then
      if [[ -n "$detail" ]]; then
        printf '%s%s\n' "$msg" "$detail"
        return 0
      fi
      printf '%sunknown error\n' "$msg"
      return 0
    fi
    printf '%s\n' "$msg"
    return 0
  fi
  if [[ -n "$detail" ]]; then
    printf '%s\n' "$detail"
    return 0
  fi
  if [[ -n "$suggestion" ]]; then
    printf '%s (suggestion: %s)\n' "$fallback" "$suggestion"
    return 0
  fi
  printf '%s\n' "$fallback"
}

normalize_tool_response() {
  local check="$1"
  local tool="$2"
  local out="$3"
  local text parsed

  text="$(first_content_text "$out")"

  if [[ -n "$text" ]] && is_json "$text"; then
    parsed="$(jq -c . <<<"$text" 2>/dev/null || printf '%s\n' "$text")"
    if jq -e '.isError == true' >/dev/null <<<"$out"; then
      log_check_debug "$check" "wrapped_error_json" "1" "$out"
    fi
    printf '%s\n' "$parsed"
    return 0
  fi

  if jq -e '.isError == true' >/dev/null <<<"$out"; then
    [[ -n "$text" ]] || text="$(json_error_message "$out" "tool error")"
    log_check_debug "$check" "mcp_error_envelope" "1" "$out"
    jq -nc --arg tool "$tool" --arg message "$text" '{
      status: "error",
      message: $message,
      source: "mcporter",
      tool: $tool
    }'
    return 0
  fi

  printf '%s\n' "$out"
}

call_json() {
  local check="$1"
  local tool="$2"
  local args="$3"
  local raw out excerpt log_file message

  if ! raw="$(call_tool "$tool" "$args" 2>&1)"; then
    log_check_debug "$check" "tool_call_failed" "1" "$raw"
    excerpt="$(short_excerpt "$raw")"
    message="tool call failed: $tool"
    [[ -n "$excerpt" ]] && message="${message} (${excerpt})"
    if log_file="$(debug_log_path_for_check "$check" 2>/dev/null)"; then
      message="${message}; debug log: ${log_file}"
    fi
    crit "$check" "$message"
  fi

  # mcporter appends MCP server stderr after the JSON payload.
  out="$(strip_mcporter_trailer "$raw")"
  if ! is_json "$out"; then
    log_check_debug "$check" "non_json_response" "1" "$raw"
    excerpt="$(short_excerpt "$raw")"
    message="non-JSON response from $tool"
    [[ -n "$excerpt" ]] && message="${message} (${excerpt})"
    if log_file="$(debug_log_path_for_check "$check" 2>/dev/null)"; then
      message="${message}; debug log: ${log_file}"
    fi
    crit "$check" "$message"
  fi

  out="$(normalize_tool_response "$check" "$tool" "$out")"
  printf '%s\n' "$out"
}

is_transient_cloudsync_error() {
  local out="$1"
  local msg

  msg="$(jq -r '.message // ""' <<<"$out")"
  [[ "$msg" == "List Cloud Sync failed: " || "$msg" == "List Cloud Sync failed:" ]]
}

is_transient_storage_error() {
  local out="$1"
  local msg

  msg="$(jq -r '.message // ""' <<<"$out")"
  [[ "$msg" == "Storage info failed: " || "$msg" == "Storage info failed:" ]]
}

log_cloudsync_debug() {
  log_check_debug "cloudsync_connection" "$1" "$2" "$3"
}

log_storage_debug() {
  log_check_debug "storage" "$1" "$2" "$3"
}

log_health_dashboard_debug() {
  log_check_debug "health_dashboard" "$1" "$2" "$3"
}

log_utilization_debug() {
  log_check_debug "utilization" "$1" "$2" "$3"
}

check_health_dashboard() {
  local check="health_dashboard"
  local dsm_out storage_out payload status used temp vol_total vol_bad
  local dsm_error storage_error attempt attempts_used max_attempts anomaly_seen

  max_attempts=3
  attempts_used=0
  anomaly_seen=0

  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    attempts_used="$attempt"
    # Use the canonical DSM/storage tools here. The aggregated dashboard tool
    # is intentionally best-effort and can omit fields that monitoring needs.
    dsm_out="$(call_json "$check" "synology.synology_dsm_info" '{"params":{}}')"
    storage_out="$(call_json "$check" "synology.synology_storage_info" '{"params":{}}')"
    payload="$(jq -nc --argjson dsm "$dsm_out" --argjson storage "$storage_out" '{dsm:$dsm,storage:$storage}')"

    dsm_error="$(jq -r 'if .status == "error" then (.message // "DSM info error") else empty end' <<<"$dsm_out")"
    storage_error="$(jq -r 'if .status == "error" then (.message // "storage info error") else empty end' <<<"$storage_out")"

    if [[ -n "$dsm_error" || -n "$storage_error" ]]; then
      anomaly_seen=1
      log_health_dashboard_debug "tool_error" "$attempt" "$payload"
      if (( attempt < max_attempts )); then
        sleep "$RETRY_SLEEP_SEC"
        continue
      fi
      [[ -n "$dsm_error" ]] && crit "$check" "${dsm_error} after ${attempts_used} attempt(s); debug log: ${HEALTH_DASHBOARD_DEBUG_LOG}"
      crit "$check" "${storage_error} after ${attempts_used} attempt(s); debug log: ${HEALTH_DASHBOARD_DEBUG_LOG}"
    fi

    status="$(jq -r 'first(.volumes[]? | .status | select(. != null and . != "")) // empty' <<<"$storage_out")"
    used="$(jq -r 'first(.volumes[]? | (.percent_used // .used_percent) | select(. != null)) // empty' <<<"$storage_out")"
    temp="$(jq -r '
      [
        .temperature,
        .temperature_c,
        .system.temperature_c,
        .system.temperature
      ]
      | map(
          if type == "number" then tostring
          elif type == "string" then (capture("(?<value>-?[0-9]+(\\.[0-9]+)?)")?.value // empty)
          else empty
          end
        )
      | map(select(length > 0))
      | .[0] // empty
    ' <<<"$dsm_out")"
    vol_total="$(jq '[.volumes[]?] | length' <<<"$storage_out")"
    vol_bad="$(jq '[.volumes[]? | select((.status != "normal") or (((.percent_used // .used_percent) // 0) >= 85))] | length' <<<"$storage_out")"

    if [[ -n "$status" && -n "$used" && -n "$temp" && "$vol_total" -gt 0 ]]; then
      if (( anomaly_seen == 1 )); then
        log_health_dashboard_debug "recovered" "$attempt" "$payload"
      fi
      break
    fi

    anomaly_seen=1
    log_health_dashboard_debug "missing_fields" "$attempt" "$payload"
    if (( attempt < max_attempts )); then
      sleep "$RETRY_SLEEP_SEC"
    fi
  done

  [[ -n "$status" && -n "$used" && -n "$temp" && "$vol_total" -gt 0 ]] || crit "$check" "missing dashboard fields after ${attempts_used} attempt(s); debug log: ${HEALTH_DASHBOARD_DEBUG_LOG}"
  (( vol_bad == 0 )) || crit "$check" "one or more volumes unhealthy or >85%"

  awk "BEGIN{exit !($temp < 60)}" || crit "$check" "system temperature high: ${temp}C"

  ok "$check" "volume=${used}% temp=${temp}C"
}

check_utilization() {
  local check="utilization"
  local out cpu mem msg attempt attempts_used max_attempts anomaly_seen malformed

  max_attempts=3
  attempts_used=0
  anomaly_seen=0
  cpu=""
  mem=""

  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    attempts_used="$attempt"
    out="$(call_json "$check" "synology.synology_utilization" '{"params":{}}')"

    if jq -e '.status == "error"' >/dev/null <<<"$out"; then
      msg="$(json_error_message "$out" "utilization error")"
      anomaly_seen=1
      log_utilization_debug "tool_error" "$attempt" "$out"

      if (( attempt < max_attempts )); then
        sleep $((RETRY_BACKOFF_BASE * (2 ** (attempt - 1))))
        continue
      fi

      if [[ "$msg" == *"Could not retrieve utilization data"* ]]; then
        log_utilization_debug "final_known_error" "$attempts_used" "$out"
        warn "$check" "telemetry unavailable after ${attempts_used} attempt(s); debug log: ${UTILIZATION_DEBUG_LOG}"
      fi

      log_utilization_debug "final_error" "$attempts_used" "$out"
      crit "$check" "${msg} after ${attempts_used} attempt(s); debug log: ${UTILIZATION_DEBUG_LOG}"
    fi

    cpu="$(jq -r '
      [
        .cpu.total_load,
        .cpu.cpu_other_load,
        .cpu.other_load,
        (
          if (.cpu.user_load != null or .cpu.system_load != null)
          then ((.cpu.user_load // 0) + (.cpu.system_load // 0))
          else empty
          end
        ),
        .data.cpu.total_load,
        .data.cpu.cpu_other_load,
        .data.cpu.other_load,
        (
          if (.data.cpu.user_load != null or .data.cpu.system_load != null)
          then ((.data.cpu.user_load // 0) + (.data.cpu.system_load // 0))
          else empty
          end
        ),
        .cpu_load_percent,
        .data.cpu_load_percent,
        .utilization.cpu,
        .utilization.cpu_percent,
        .data.utilization.cpu,
        .data.utilization.cpu_percent
      ]
      | map(
          if type == "number" then tostring
          elif type == "string" then (capture("(?<value>-?[0-9]+(\\.[0-9]+)?)")?.value // empty)
          else empty
          end
        )
      | map(select(length > 0))
      | .[0] // empty
    ' <<<"$out")"
    mem="$(jq -r '
      [
        .memory.percent_used,
        .memory.real_usage,
        .memory.memory_usage,
        .memory.percent,
        .data.memory.percent_used,
        .data.memory.real_usage,
        .data.memory.memory_usage,
        .data.memory.percent,
        .memory_percent,
        .data.memory_percent,
        .utilization.memory,
        .utilization.memory_percent,
        .data.utilization.memory,
        .data.utilization.memory_percent
      ]
      | map(
          if type == "number" then tostring
          elif type == "string" then (capture("(?<value>-?[0-9]+(\\.[0-9]+)?)")?.value // empty)
          else empty
          end
        )
      | map(select(length > 0))
      | .[0] // empty
    ' <<<"$out")"

    malformed=0
    if [[ -n "$cpu" ]] && ! is_percentage "$cpu"; then
      cpu=""
      malformed=1
    fi
    if [[ -n "$mem" ]] && ! is_percentage "$mem"; then
      mem=""
      malformed=1
    fi

    if [[ -n "$cpu" && -n "$mem" ]]; then
      if (( anomaly_seen == 1 )); then
        log_utilization_debug "recovered" "$attempt" "$out"
      fi
      break
    fi

    anomaly_seen=1
    if (( malformed == 1 )); then
      log_utilization_debug "malformed_fields" "$attempt" "$out"
    else
      log_utilization_debug "missing_fields" "$attempt" "$out"
    fi
    if (( attempt < max_attempts )); then
      sleep "$RETRY_SLEEP_SEC"
    fi
  done

  [[ -n "$cpu" && -n "$mem" ]] || warn "$check" "missing or malformed cpu/memory fields after ${attempts_used} attempt(s); debug log: ${UTILIZATION_DEBUG_LOG}"

  awk "BEGIN{exit !($cpu < 85)}" || crit "$check" "cpu high: ${cpu}%"
  awk "BEGIN{exit !($mem < 99)}" || crit "$check" "memory high: ${mem}%"

  ok "$check" "cpu=${cpu}% mem=${mem}%"
}

check_storage() {
  local check="storage"
  local out vol_bad disk_bad attempt attempts_used max_attempts transient_seen

  max_attempts=3
  attempts_used=0
  transient_seen=0
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    attempts_used="$attempt"
    out="$(call_json "$check" "synology.synology_storage_info" '{"params":{}}')"

    if ! jq -e '.status == "error"' >/dev/null <<<"$out"; then
      if (( transient_seen == 1 )); then
        log_storage_debug "recovered" "$attempt" "$out"
      fi
      break
    fi

    if ! is_transient_storage_error "$out"; then
      log_storage_debug "non_transient_error" "$attempt" "$out"
      break
    fi

    transient_seen=1
    log_storage_debug "transient_error" "$attempt" "$out"

    if (( attempt < max_attempts )); then
        sleep "$RETRY_SLEEP_SEC"
    fi
  done

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    log_storage_debug "final_error" "$attempts_used" "$out"
    crit "$check" "$(jq -r '.message // "storage error"' <<<"$out") after ${attempts_used} attempt(s); debug log: ${STORAGE_DEBUG_LOG}"
  fi

  vol_bad="$(jq '[.volumes[]? | select((.status != "normal") or ((.percent_used // 0) >= 85))] | length' <<<"$out")"
  disk_bad="$(jq '[.disks[]? | select((.status != "normal") or ((.temp // 0) >= 55))] | length' <<<"$out")"

  (( vol_bad == 0 )) || crit "$check" "one or more volumes unhealthy or >85%"
  (( disk_bad == 0 )) || crit "$check" "one or more disks unhealthy or >=55C"

  ok "$check" "volumes and disks normal"
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
  ok "$check" "gateway=${gw} dns=${dns}"
}

check_cloudsync_connection() {
  local check="cloudsync_connection"
  local out total bad attempt attempts_used max_attempts transient_seen

  max_attempts=3
  attempts_used=0
  transient_seen=0
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    attempts_used="$attempt"
    out="$(call_json "$check" "synology.synology_cloudsync_list" '{"params":{}}')"

    if ! jq -e '.status == "error"' >/dev/null <<<"$out"; then
      if (( transient_seen == 1 )); then
        log_cloudsync_debug "recovered" "$attempt" "$out"
      fi
      break
    fi

    if ! is_transient_cloudsync_error "$out"; then
      log_cloudsync_debug "non_transient_error" "$attempt" "$out"
      break
    fi

    transient_seen=1
    log_cloudsync_debug "transient_error" "$attempt" "$out"

    if (( attempt < max_attempts )); then
      sleep "$RETRY_SLEEP_SEC"
    fi
  done

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    log_cloudsync_debug "final_error" "$attempts_used" "$out"
    crit "$check" "$(jq -r '.message // "cloudsync list error"' <<<"$out") after ${attempts_used} attempt(s); debug log: ${CLOUDSYNC_DEBUG_LOG}"
  fi

  total="$(jq -r '.count // 0' <<<"$out")"
  bad="$(jq '[.connections[]? | select(((.status // "") | ascii_downcase) != "uptodate")] | length' <<<"$out")"

  (( total > 0 )) || warn "$check" "no cloud sync connections"
  (( bad == 0 )) || crit "$check" "${bad} cloud sync connection(s) not uptodate"

  ok "$check" "${total} connection(s) uptodate"
}

check_cloudsync_logs() {
  local check="cloudsync_logs"
  local out errs

  out="$(call_json "$check" "synology.synology_cloudsync_logs" "{\"params\":{\"connection_id\":${CLOUDSYNC_CONNECTION_ID},\"offset\":0,\"limit\":100}}")"

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "cloudsync logs error"' <<<"$out")"
  fi

  errs="$(jq '[.items[]? | select((.error_code // 0) != 0)] | length' <<<"$out")"
  (( errs == 0 )) || crit "$check" "${errs} cloud sync log entries with error_code != 0"

  ok "$check" "no cloud sync errors in latest window"
}

check_filesystem_liveness() {
  local check="filesystem_liveness"
  local paths p out

  paths=("/homes" "/proxmox_backups" "/photo" "/video" "/garage_arts")
  for p in "${paths[@]}"; do
    out="$(call_json "$check" "synology.synology_list_files" "{\"params\":{\"path\":\"$p\",\"offset\":0,\"limit\":1}}")"

    if jq -e '.status == "error"' >/dev/null <<<"$out"; then
      crit "$check" "cannot list ${p}: $(jq -r '.message // "unknown"' <<<"$out")"
    fi

    jq -e '.count >= 0' >/dev/null <<<"$out" || crit "$check" "invalid count for ${p}"
  done

  ok "$check" "critical directories accessible"
}

check_package_drift() {
  local check="package_drift"
  local out legacy

  out="$(call_json "$check" "synology.synology_package_list" '{"params":{}}')"

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "package list error"' <<<"$out")"
  fi

  # required packages check
  for req in CloudSync FileStation SMBService; do
    jq -e --arg req "$req" '[.packages[]?.id] | index($req) != null' >/dev/null <<<"$out" || crit "$check" "required package missing: $req"
  done

  legacy="$(jq '[.packages[]? | select(.id == "Node.js_v12" or .id == "Python2")] | length' <<<"$out")"
  (( legacy == 0 )) || warn "$check" "legacy runtime package(s) present (Node.js_v12/Python2)"

  ok "$check" "required package baseline intact"
}

check_security_baseline() {
  local check="security_baseline"
  local users groups links admin_count guest_count link_count

  users="$(call_json "$check" "synology.synology_list_users" '{"params":{}}')"
  groups="$(call_json "$check" "synology.synology_list_groups" '{"params":{}}')"
  links="$(call_json "$check" "synology.synology_list_share_links" '{"params":{"offset":0,"limit":200}}')"

  if jq -e '.status == "error"' >/dev/null <<<"$users"; then
    crit "$check" "$(jq -r '.message // "list users error"' <<<"$users")"
  fi
  if jq -e '.status == "error"' >/dev/null <<<"$groups"; then
    crit "$check" "$(jq -r '.message // "list groups error"' <<<"$groups")"
  fi
  if jq -e '.status == "error"' >/dev/null <<<"$links"; then
    crit "$check" "$(jq -r '.message // "list share links error"' <<<"$links")"
  fi

  admin_count="$(jq '[.users[]? | select(.name == "admin")] | length' <<<"$users")"
  guest_count="$(jq '[.users[]? | select(.name == "guest")] | length' <<<"$users")"
  link_count="$(jq -r '.total // .count // 0' <<<"$links")"

  (( admin_count > 0 )) || crit "$check" "admin account missing from user list"

  if (( link_count > 0 )); then
    warn "$check" "${link_count} active external share link(s)"
  fi

  if (( guest_count > 0 )); then
    warn "$check" "guest user exists (verify disabled in DSM)"
  fi

  ok "$check" "users/groups/links baseline clean"
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
    warn "$check" "known API/package issues: ${summary}"
  fi

  ok "$check" "all probed service APIs healthy"
}

usage() {
  cat <<USAGE
Usage: $0 <check_name>

Checks:
  health_dashboard
  utilization
  storage
  network
  cloudsync_connection
  cloudsync_logs
  filesystem_liveness
  package_drift
  security_baseline
  service_api_probe
USAGE
}

main() {
  local check="${1:-}"
  case "$check" in
    health_dashboard) check_health_dashboard ;;
    utilization) check_utilization ;;
    storage) check_storage ;;
    network) check_network ;;
    cloudsync_connection) check_cloudsync_connection ;;
    cloudsync_logs) check_cloudsync_logs ;;
    filesystem_liveness) check_filesystem_liveness ;;
    package_drift) check_package_drift ;;
    security_baseline) check_security_baseline ;;
    service_api_probe) check_service_api_probe ;;
    *) usage; exit 64 ;;
  esac
}

main "$@"
