#!/usr/bin/env bash
set -euo pipefail

PATH="/home/linuxbrew/.linuxbrew/bin:/home/moltbot/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

MCPORTER_BIN="${MCPORTER_BIN:-mcporter}"
TIMEOUT_SEC="${TIMEOUT_SEC:-60}"
CLOUDSYNC_CONNECTION_ID="${CLOUDSYNC_CONNECTION_ID:-20}"

call_tool() {
  local tool="$1"
  local args="$2"
  timeout "${TIMEOUT_SEC}s" "$MCPORTER_BIN" call "$tool" --args "$args" --output json
}

emit() {
  local level="$1"
  local check="$2"
  local message="$3"
  printf '{"level":"%s","check":"%s","message":"%s"}\n' "$level" "$check" "$message"
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

call_json() {
  local check="$1"
  local tool="$2"
  local args="$3"
  local raw out

  if ! raw="$(call_tool "$tool" "$args" 2>/dev/null)"; then
    crit "$check" "tool call failed: $tool"
  fi
  # mcporter appends MCP server stderr after the JSON payload.
  out="$(printf '%s\n' "$raw" | sed '/^\[mcporter\] /,$d')"
  if ! is_json "$out"; then
    crit "$check" "non-JSON response from $tool"
  fi
  printf '%s\n' "$out"
}

check_health_dashboard() {
  local check="health_dashboard"
  local out status used temp

  out="$(call_json "$check" "synology.synology_health_dashboard" '{"params":{}}')"

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "health dashboard error"' <<<"$out")"
  fi

  status="$(jq -r '.volumes[0].status // empty' <<<"$out")"
  used="$(jq -r '.volumes[0].used_percent // empty' <<<"$out")"
  temp="$(jq -r '.system.temperature_c // empty' <<<"$out")"

  [[ -n "$status" && -n "$used" && -n "$temp" ]] || crit "$check" "missing dashboard fields"
  [[ "$status" == "normal" ]] || crit "$check" "volume status is '$status'"

  awk "BEGIN{exit !($used < 85)}" || crit "$check" "volume usage high: ${used}%"
  awk "BEGIN{exit !($temp < 60)}" || crit "$check" "system temperature high: ${temp}C"

  ok "$check" "volume=${used}% temp=${temp}C"
}

check_utilization() {
  local check="utilization"
  local out cpu mem

  out="$(call_json "$check" "synology.synology_utilization" '{"params":{}}')"

  if jq -e '.status == "error" and ((.message // "") | contains("Could not retrieve utilization data"))' >/dev/null <<<"$out"; then
    warn "$check" "telemetry unavailable (suppressed known issue)"
  fi

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "utilization error"' <<<"$out")"
  fi

  cpu="$(jq -r '.cpu.total_load // .cpu.cpu_other_load // .cpu.user_load // empty' <<<"$out")"
  mem="$(jq -r '.memory.real_usage // .memory.memory_usage // empty' <<<"$out")"

  [[ -n "$cpu" && -n "$mem" ]] || warn "$check" "schema changed; no cpu/memory fields"

  awk "BEGIN{exit !($cpu < 85)}" || crit "$check" "cpu high: ${cpu}%"
  awk "BEGIN{exit !($mem < 90)}" || crit "$check" "memory high: ${mem}%"

  ok "$check" "cpu=${cpu}% mem=${mem}%"
}

check_storage() {
  local check="storage"
  local out vol_bad disk_bad

  out="$(call_json "$check" "synology.synology_storage_info" '{"params":{}}')"

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "storage error"' <<<"$out")"
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
  local out total bad

  out="$(call_json "$check" "synology.synology_cloudsync_list" '{"params":{}}')"

  if jq -e '.status == "error"' >/dev/null <<<"$out"; then
    crit "$check" "$(jq -r '.message // "cloudsync list error"' <<<"$out")"
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
