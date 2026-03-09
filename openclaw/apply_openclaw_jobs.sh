#!/usr/bin/env bash
set -euo pipefail

PATH="/home/linuxbrew/.linuxbrew/bin:/home/moltbot/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"
MANIFEST_PATH="${MANIFEST_PATH:-/home/moltbot/repositories/dk-synology-mcp/openclaw/openclaw_jobs_manifest.json}"
LOCAL_JOBS_FILE="${LOCAL_JOBS_FILE:-$HOME/.openclaw/cron/jobs.json}"
RUNNER_PATH="${RUNNER_PATH:-/home/moltbot/repositories/dk-synology-mcp/openclaw/synology_check.sh}"
SLACK_TARGET_OVERRIDE="${SLACK_TARGET_OVERRIDE:-}"

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

log() {
  printf '[openclaw-jobs] %s\n' "$*"
}

die() {
  printf '[openclaw-jobs][ERROR] %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command missing: $1"
}

load_existing_jobs() {
  if [[ -f "$LOCAL_JOBS_FILE" ]]; then
    cat "$LOCAL_JOBS_FILE"
  else
    printf '{"jobs":[]}'
  fi
}

job_id_by_name() {
  local jobs_json="$1"
  local name="$2"
  jq -r --arg name "$name" '.jobs[]? | select(.name == $name) | .id' <<<"$jobs_json" | head -n1
}

build_message() {
  local job_name="$1"
  local check_name="$2"
  local slack_target="$3"

  cat <<MSG
CRON TASK (strict):
1) Execute exactly once via exec tool:
bash $RUNNER_PATH $check_name

2) Evaluate the command outcome from exit code and JSON output.
Expected JSON shape:
{"level":"ok|warn|crit","check":"$check_name","message":"..."}

3) Decision rules:
- If exit code is non-zero, OR level == "crit":
  send Slack message using message tool with:
  action=send, channel=slack, target=$slack_target
  Message MUST start with: [$job_name]
  Include the raw checker output and a one-line incident summary.
  Then reply EXACTLY NO_REPLY.
- If level == "warn":
  DO NOT send Slack. Reply EXACTLY NO_REPLY.
- If level == "ok":
  Reply EXACTLY NO_REPLY.

Hard constraints:
- Do NOT skip command execution.
- Do NOT send progress updates or status chatter.
- Only valid final reply text is: NO_REPLY.
MSG
}

run_cmd() {
  if (( APPLY == 1 )); then
    "$@"
  else
    printf 'DRY_RUN: '
    printf '%q ' "$@"
    printf '\n'
  fi
}

require_cmd jq
require_cmd "$OPENCLAW_BIN"
[[ -f "$MANIFEST_PATH" ]] || die "manifest not found: $MANIFEST_PATH"
[[ -x "$RUNNER_PATH" ]] || die "runner script not executable: $RUNNER_PATH"

if (( APPLY == 1 )); then
  if ! "$OPENCLAW_BIN" cron status >/dev/null 2>&1; then
    die "openclaw gateway/scheduler unavailable. Start gateway, then rerun with --apply."
  fi
fi

def_tz="$(jq -r '.defaults.timezone' "$MANIFEST_PATH")"
def_agent="$(jq -r '.defaults.agent' "$MANIFEST_PATH")"
def_session="$(jq -r '.defaults.session' "$MANIFEST_PATH")"
def_wake="$(jq -r '.defaults.wake' "$MANIFEST_PATH")"
def_model="$(jq -r '.defaults.model' "$MANIFEST_PATH")"
def_thinking="$(jq -r '.defaults.thinking' "$MANIFEST_PATH")"
def_light_context="$(jq -r '.defaults.light_context' "$MANIFEST_PATH")"
def_timeout_ms="$(jq -r '.defaults.timeout_ms' "$MANIFEST_PATH")"
def_alert_enabled="$(jq -r '.defaults.failure_alert.enabled' "$MANIFEST_PATH")"
def_alert_after="$(jq -r '.defaults.failure_alert.after' "$MANIFEST_PATH")"
def_alert_channel="$(jq -r '.defaults.failure_alert.channel' "$MANIFEST_PATH")"
def_alert_to="$(jq -r '.defaults.failure_alert.to' "$MANIFEST_PATH")"
def_alert_cooldown="$(jq -r '.defaults.failure_alert.cooldown' "$MANIFEST_PATH")"

if [[ -n "$SLACK_TARGET_OVERRIDE" ]]; then
  def_alert_to="$SLACK_TARGET_OVERRIDE"
fi

jobs_json="$(load_existing_jobs)"

while IFS= read -r job; do
  name="$(jq -r '.name' <<<"$job")"
  description="$(jq -r '.description // empty' <<<"$job")"
  cron_expr="$(jq -r '.cron' <<<"$job")"
  check_name="$(jq -r '.check' <<<"$job")"
  tz="$(jq -r '.tz // empty' <<<"$job")"
  agent="$(jq -r '.agent // empty' <<<"$job")"
  session="$(jq -r '.session // empty' <<<"$job")"
  wake="$(jq -r '.wake // empty' <<<"$job")"
  model="$(jq -r '.model // empty' <<<"$job")"
  thinking="$(jq -r '.thinking // empty' <<<"$job")"
  light_context="$(jq -r '.light_context // empty' <<<"$job")"
  timeout_ms="$(jq -r '.timeout_ms // empty' <<<"$job")"

  [[ -n "$tz" && "$tz" != "null" ]] || tz="$def_tz"
  [[ -n "$agent" && "$agent" != "null" ]] || agent="$def_agent"
  [[ -n "$session" && "$session" != "null" ]] || session="$def_session"
  [[ -n "$wake" && "$wake" != "null" ]] || wake="$def_wake"
  [[ -n "$model" && "$model" != "null" ]] || model="$def_model"
  [[ -n "$thinking" && "$thinking" != "null" ]] || thinking="$def_thinking"
  [[ -n "$light_context" && "$light_context" != "null" ]] || light_context="$def_light_context"
  [[ -n "$timeout_ms" && "$timeout_ms" != "null" ]] || timeout_ms="$def_timeout_ms"

  message="$(build_message "$name" "$check_name" "$def_alert_to")"

  id="$(job_id_by_name "$jobs_json" "$name")"

  if [[ -z "$id" ]]; then
    log "create: $name"
    add_cmd=(
      "$OPENCLAW_BIN" cron add --json
      --name "$name"
      --cron "$cron_expr"
      --tz "$tz"
      --agent "$agent"
      --session "$session"
      --message "$message"
      --model "$model"
      --thinking "$thinking"
      --wake "$wake"
      --timeout "$timeout_ms"
      --no-deliver
    )
    if [[ -n "$description" ]]; then
      add_cmd+=(--description "$description")
    fi
    if [[ "$light_context" == "true" ]]; then
      add_cmd+=(--light-context)
    fi
    run_cmd "${add_cmd[@]}"

    if (( APPLY == 1 )); then
      sleep 1
      jobs_json="$(load_existing_jobs)"
      id="$(job_id_by_name "$jobs_json" "$name")"
      [[ -n "$id" ]] || die "failed to resolve created job id for '$name'"
    else
      id="<dry-run-id>"
    fi
  else
    log "update: $name ($id)"
  fi

  edit_cmd=(
    "$OPENCLAW_BIN" cron edit "$id"
    --enable
    --name "$name"
    --cron "$cron_expr"
    --tz "$tz"
    --agent "$agent"
    --session "$session"
    --message "$message"
    --model "$model"
    --thinking "$thinking"
    --wake "$wake"
    --timeout "$timeout_ms"
    --no-deliver
  )

  if [[ "$light_context" == "true" ]]; then
    edit_cmd+=(--light-context)
  else
    edit_cmd+=(--no-light-context)
  fi

  if [[ "$def_alert_enabled" == "true" ]]; then
    edit_cmd+=(
      --failure-alert
      --failure-alert-after "$def_alert_after"
      --failure-alert-channel "$def_alert_channel"
      --failure-alert-to "$def_alert_to"
      --failure-alert-cooldown "$def_alert_cooldown"
    )
  else
    edit_cmd+=(--no-failure-alert)
  fi

  run_cmd "${edit_cmd[@]}"
done < <(jq -c '.jobs[]' "$MANIFEST_PATH")

if (( APPLY == 1 )); then
  log "completed (applied)"
else
  log "completed (dry-run). Re-run with --apply to write jobs to OpenClaw."
fi
