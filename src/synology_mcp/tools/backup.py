"""Backup tools — Hyper Backup task management and monitoring.

Covers: list tasks, task status, start/cancel backup, integrity check,
and backup version info.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, format_timestamp, handle_synology_error, error_response


class BackupNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class BackupTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: int = Field(..., description="Backup task ID")
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_backup_tools(mcp, conn_mgr) -> None:
    """Register Hyper Backup tools."""

    def _bk(nas=None):
        return conn_mgr.get_client("backup", nas)

    @mcp.tool(
        name="synology_backup_list",
        annotations={"title": "List Backup Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_backup_list(nas: str | None = None) -> str:
        """List all Hyper Backup tasks and their status."""
        try:
            bk = _bk(nas)
            result = bk.backup_task_list()
            if not result or "data" not in result:
                return error_response("Could not list backup tasks")
            tasks = result["data"].get("task_list", result["data"])
            items = []
            if isinstance(tasks, list):
                for t in tasks:
                    items.append({
                        "id": t.get("task_id", t.get("id", "")),
                        "name": t.get("name", ""),
                        "status": t.get("status", ""),
                        "last_backup": format_timestamp(t.get("last_backup_time")),
                        "next_backup": format_timestamp(t.get("next_backup_time")),
                    })
            return json.dumps({"tasks": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List backups")

    @mcp.tool(
        name="synology_backup_status",
        annotations={"title": "Backup Task Status", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_backup_status(nas: str | None = None, task_id: int = 0) -> str:
        """Get detailed status of a specific backup task."""
        try:
            bk = _bk(nas)
            result = bk.backup_task_status(task_id=task_id)
            if not result or "data" not in result:
                return error_response(f"No status for backup task {task_id}")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Backup status")

    @mcp.tool(
        name="synology_backup_run",
        annotations={"title": "Start Backup", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_backup_run(nas: str | None = None, task_id: int = 0) -> str:
        """Trigger an immediate backup for a task."""
        try:
            bk = _bk(nas)
            result = bk.backup_task_run(task_id=task_id)
            return json.dumps({
                "status": "success",
                "action": "started",
                "task_id": task_id,
                "message": "Backup task started. Check status with synology_backup_status.",
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Start backup")

    @mcp.tool(
        name="synology_backup_cancel",
        annotations={"title": "Cancel Backup", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_backup_cancel(nas: str | None = None, task_id: int = 0) -> str:
        """Cancel a running backup task."""
        try:
            bk = _bk(nas)
            result = bk.backup_task_cancel(task_id=task_id)
            return json.dumps({"status": "success", "action": "cancelled", "task_id": task_id}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Cancel backup")

    @mcp.tool(
        name="synology_backup_integrity_check",
        annotations={"title": "Backup Integrity Check", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_backup_integrity_check(nas: str | None = None, task_id: int = 0) -> str:
        """Start an integrity check on a backup task to verify data consistency."""
        try:
            bk = _bk(nas)
            result = bk.integrity_check_run(task_id=task_id)
            if not result or "data" not in result:
                return error_response("Could not start integrity check")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Integrity check")
