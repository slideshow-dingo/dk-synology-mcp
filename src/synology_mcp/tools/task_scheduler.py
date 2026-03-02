"""TaskScheduler tools — manage scheduled tasks on the NAS.

Covers: list tasks, task details, enable/disable, run now, and task output.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_timestamp, handle_synology_error, error_response


class TaskSchedulerNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class TaskSchedulerTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: int = Field(..., description="Scheduled task ID")
    nas: Optional[str] = Field(default=None, description="NAS name")


class TaskSchedulerEnableInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: int = Field(..., description="Scheduled task ID")
    enabled: bool = Field(..., description="True to enable, False to disable")
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_task_scheduler_tools(mcp, conn_mgr) -> None:
    """Register Task Scheduler tools."""

    def _ts(nas=None):
        return conn_mgr.get_client("task_scheduler", nas)

    @mcp.tool(
        name="synology_scheduled_tasks_list",
        annotations={"title": "List Scheduled Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_scheduled_tasks_list(params: TaskSchedulerNasInput) -> str:
        """List all scheduled tasks (cron jobs, user scripts, recycle bin cleanup, etc.)."""
        try:
            ts = _ts(params.nas)
            result = ts.get_task_list()
            if not result or "data" not in result:
                return error_response("Could not list scheduled tasks")
            tasks = result["data"].get("tasks", result["data"])
            items = []
            if isinstance(tasks, list):
                for t in tasks:
                    items.append({
                        "id": t.get("id", ""),
                        "name": t.get("name", ""),
                        "type": t.get("type", ""),
                        "enabled": t.get("enable", t.get("enabled", False)),
                        "next_run": format_timestamp(t.get("next_trigger_time")),
                        "last_run": format_timestamp(t.get("last_trigger_time")),
                    })
            return json.dumps({"tasks": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List scheduled tasks")

    @mcp.tool(
        name="synology_scheduled_task_info",
        annotations={"title": "Scheduled Task Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_scheduled_task_info(params: TaskSchedulerTaskInput) -> str:
        """Get detailed info about a specific scheduled task."""
        try:
            ts = _ts(params.nas)
            result = ts.get_task_config(task_id=params.task_id)
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
            result = ts.task_run(task_id=params.task_id)
            return json.dumps({"status": "success", "action": "triggered", "task_id": params.task_id}, indent=2)
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
            result = ts.task_set_enable(task_id=params.task_id, enable=params.enabled)
            action = "enabled" if params.enabled else "disabled"
            return json.dumps({"status": "success", "action": action, "task_id": params.task_id}, indent=2)
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
            result = ts.get_task_result(task_id=params.task_id)
            if not result or "data" not in result:
                return error_response(f"No output for task {params.task_id}")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Task output")
