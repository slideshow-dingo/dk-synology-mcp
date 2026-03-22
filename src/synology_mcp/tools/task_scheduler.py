"""TaskScheduler tools — manage scheduled tasks on the NAS.

Covers: list tasks, task details, enable/disable, run now, and task output.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import (
    error_response,
    exception_message,
    format_timestamp,
    handle_synology_error,
)


class TaskSchedulerNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class TaskSchedulerTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: int = Field(..., description="Scheduled task ID")
    real_owner: Optional[str] = Field(
        default=None,
        description="Task real owner. Usually auto-resolved from the task list when omitted.",
    )
    nas: Optional[str] = Field(default=None, description="NAS name")


class TaskSchedulerEnableInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: int = Field(..., description="Scheduled task ID")
    enabled: bool = Field(..., description="True to enable, False to disable")
    real_owner: Optional[str] = Field(
        default=None,
        description="Task real owner. Usually auto-resolved from the task list when omitted.",
    )
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_task_scheduler_tools(mcp, conn_mgr) -> None:
    """Register Task Scheduler tools."""

    def _ts(nas=None):
        return conn_mgr.get_client("task_scheduler", nas)

    def _task_scheduler_api(ts) -> tuple[str, str, int]:
        api_name = "SYNO.Core.TaskScheduler"
        info = ts.gen_list.get(api_name)
        if not info:
            raise RuntimeError("SYNO.Core.TaskScheduler API is not available on this NAS")

        max_version = info.get("maxVersion", 1)
        try:
            max_version = int(max_version)
        except (TypeError, ValueError):
            max_version = 1

        return api_name, info["path"], max_version

    def _is_retryable_task_scheduler_error(exc: Exception) -> bool:
        if getattr(exc, "error_code", None) in {101, 103, 104, 114, 1198}:
            return True

        message = exception_message(exc).lower()
        return any(
            marker in message
            for marker in (
                "no parameter of api, method or version",
                "lost parameters for this api",
                "requested method does not exist",
                "requested version does not support the functionality",
                "operation incompatible with this version",
            )
        )

    def _task_scheduler_request(ts, attempts: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
        api_name, api_path, max_version = _task_scheduler_api(ts)
        last_retryable: Exception | None = None

        for version, params in attempts:
            if version > max_version:
                continue

            req_param = {"version": version, **params}
            try:
                return ts.request_data(api_name, api_path, req_param)
            except Exception as exc:
                if _is_retryable_task_scheduler_error(exc):
                    last_retryable = exc
                    continue
                raise

        if last_retryable is not None:
            raise last_retryable

        raise RuntimeError("No compatible Task Scheduler API version is available")

    def _task_list_result(ts, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        attempts = [
            (
                version,
                {
                    "method": "list",
                    "sort_by": "next_trigger_time",
                    "sort_direction": "ASC",
                    "offset": offset,
                    "limit": limit,
                },
            )
            for version in (3, 2, 1)
        ]
        return _task_scheduler_request(ts, attempts)

    def _extract_tasks(result: dict[str, Any]) -> list[dict[str, Any]]:
        data = result.get("data")
        if isinstance(data, dict):
            tasks = data.get("tasks", data)
        else:
            tasks = data

        if isinstance(tasks, list):
            return [task for task in tasks if isinstance(task, dict)]
        return []

    def _resolve_real_owner(ts, task_id: int, explicit_owner: Optional[str]) -> Optional[str]:
        if explicit_owner:
            return explicit_owner

        task_id_str = str(task_id)
        try:
            task_list = _task_list_result(ts, offset=0, limit=500)
        except Exception as exc:
            if _is_retryable_task_scheduler_error(exc):
                return None
            raise

        for task in _extract_tasks(task_list):
            if str(task.get("id", "")) != task_id_str:
                continue

            real_owner = task.get("real_owner") or task.get("owner")
            if real_owner:
                return str(real_owner)
            return None

        return None

    def _task_info_attempts(task_id: int, real_owner: Optional[str]) -> list[tuple[int, dict[str, Any]]]:
        attempts: list[tuple[int, dict[str, Any]]] = []
        if real_owner:
            for version in (4, 3, 2, 1):
                attempts.append((version, {"method": "get", "id": task_id, "real_owner": real_owner}))
        for version in (4, 3, 2, 1):
            attempts.append((version, {"method": "get", "id": task_id}))
        return attempts

    def _task_run_attempts(task_id: int, real_owner: Optional[str]) -> list[tuple[int, dict[str, Any]]]:
        attempts: list[tuple[int, dict[str, Any]]] = []
        if real_owner:
            attempts.append(
                (
                    2,
                    {
                        "method": "run",
                        "tasks": json.dumps([{"id": task_id, "real_owner": real_owner}]),
                    },
                )
            )
        attempts.append((2, {"method": "run", "tasks": json.dumps([{"id": task_id}])}))
        attempts.append((1, {"method": "run", "id": task_id}))
        return attempts

    def _task_enable_attempts(
        task_id: int,
        enabled: bool,
        real_owner: Optional[str],
    ) -> list[tuple[int, dict[str, Any]]]:
        attempts: list[tuple[int, dict[str, Any]]] = []
        if real_owner:
            attempts.append(
                (
                    2,
                    {
                        "method": "set_enable",
                        "status": json.dumps([{"id": task_id, "real_owner": real_owner, "enable": enabled}]),
                    },
                )
            )
        attempts.append(
            (
                2,
                {
                    "method": "set_enable",
                    "status": json.dumps([{"id": task_id, "enable": enabled}]),
                },
            )
        )
        attempts.append((1, {"method": "set_enable", "id": task_id, "enable": enabled}))
        return attempts

    @mcp.tool(
        name="synology_scheduled_tasks_list",
        annotations={"title": "List Scheduled Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_scheduled_tasks_list(params: TaskSchedulerNasInput) -> str:
        """List all scheduled tasks (cron jobs, user scripts, recycle bin cleanup, etc.)."""
        try:
            ts = _ts(params.nas)
            result = _task_list_result(ts)
            if not result or "data" not in result:
                return error_response("List scheduled tasks failed: could not retrieve task list")

            tasks = _extract_tasks(result)
            items = []
            for task in tasks:
                items.append(
                    {
                        "id": task.get("id", ""),
                        "name": task.get("name", ""),
                        "type": task.get("type", ""),
                        "enabled": task.get("enable", task.get("enabled", False)),
                        "owner": task.get("owner", ""),
                        "real_owner": task.get("real_owner", task.get("owner", "")),
                        "next_run": format_timestamp(task.get("next_trigger_time")),
                        "last_run": format_timestamp(task.get("last_trigger_time")),
                    }
                )

            data = result.get("data", {})
            total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
            return json.dumps({"tasks": items, "count": len(items), "total": total}, indent=2, default=str)
        except Exception as e:
            if _is_retryable_task_scheduler_error(e):
                return error_response(
                    f"List scheduled tasks failed: {exception_message(e)}",
                    "This DSM/API combination does not expose a compatible Task Scheduler list method.",
                )
            return handle_synology_error(e, "List scheduled tasks")

    @mcp.tool(
        name="synology_scheduled_task_info",
        annotations={"title": "Scheduled Task Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_scheduled_task_info(params: TaskSchedulerTaskInput) -> str:
        """Get detailed info about a specific scheduled task."""
        try:
            ts = _ts(params.nas)
            real_owner = _resolve_real_owner(ts, params.task_id, params.real_owner)
            result = _task_scheduler_request(ts, _task_info_attempts(params.task_id, real_owner))
            if not result or "data" not in result:
                return error_response(f"Task {params.task_id} not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Task info")

    @mcp.tool(
        name="synology_scheduled_task_run",
        annotations={"title": "Run Scheduled Task Now", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_scheduled_task_run(params: TaskSchedulerTaskInput) -> str:
        """Trigger immediate execution of a scheduled task."""
        try:
            ts = _ts(params.nas)
            real_owner = _resolve_real_owner(ts, params.task_id, params.real_owner)
            _task_scheduler_request(ts, _task_run_attempts(params.task_id, real_owner))
            return json.dumps(
                {
                    "status": "success",
                    "action": "triggered",
                    "task_id": params.task_id,
                    "real_owner": real_owner or "",
                },
                indent=2,
            )
        except Exception as e:
            return handle_synology_error(e, "Run task")

    @mcp.tool(
        name="synology_scheduled_task_enable",
        annotations={"title": "Enable/Disable Scheduled Task", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_scheduled_task_enable(params: TaskSchedulerEnableInput) -> str:
        """Enable or disable a scheduled task."""
        try:
            ts = _ts(params.nas)
            real_owner = _resolve_real_owner(ts, params.task_id, params.real_owner)
            _task_scheduler_request(ts, _task_enable_attempts(params.task_id, params.enabled, real_owner))
            action = "enabled" if params.enabled else "disabled"
            return json.dumps(
                {
                    "status": "success",
                    "action": action,
                    "task_id": params.task_id,
                    "real_owner": real_owner or "",
                },
                indent=2,
            )
        except Exception as e:
            return handle_synology_error(e, "Enable/disable task")

    @mcp.tool(
        name="synology_scheduled_task_output",
        annotations={"title": "Scheduled Task Output", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_scheduled_task_output(params: TaskSchedulerTaskInput) -> str:
        """Get the output/result from the last run of a scheduled task."""
        try:
            ts = _ts(params.nas)
            result = _task_scheduler_request(
                ts,
                [
                    (1, {"method": "get_history_status_list", "id": params.task_id}),
                ],
            )
            if not result or "data" not in result:
                return error_response(f"No output for task {params.task_id}")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Task output")
