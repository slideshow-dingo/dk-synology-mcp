"""Active Backup for Business tools — PC, server, and VM backup management.

Covers: list tasks, task details, device list, backup logs, and restore points.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, format_timestamp, handle_synology_error, error_response


class ABBNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class ABBTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: int = Field(..., description="Active Backup task ID")
    nas: Optional[str] = Field(default=None, description="NAS name")


class ABBDeviceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    device_id: int = Field(..., description="Device ID")
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_active_backup_tools(mcp, conn_mgr) -> None:
    """Register Active Backup for Business tools."""

    def _abb(nas=None):
        return conn_mgr.get_client("activebackup", nas)

    @mcp.tool(
        name="synology_abb_list_tasks",
        annotations={"title": "List ABB Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_abb_list_tasks(nas: str | None = None) -> str:
        """List all Active Backup for Business tasks (PC, server, VM)."""
        try:
            abb = _abb(nas)
            result = abb.list_tasks()
            if not result or "data" not in result:
                return error_response("Could not list Active Backup tasks")
            tasks = result["data"].get("task_list", result["data"].get("list", []))
            items = []
            if isinstance(tasks, list):
                for t in tasks:
                    items.append({
                        "id": t.get("task_id", t.get("id", "")),
                        "name": t.get("task_name", t.get("name", "")),
                        "status": t.get("status", ""),
                        "type": t.get("type", ""),
                        "schedule": t.get("schedule", ""),
                        "last_backup": format_timestamp(t.get("last_backup_time")),
                    })
            return json.dumps({"tasks": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List ABB tasks")

    @mcp.tool(
        name="synology_abb_task_info",
        annotations={"title": "ABB Task Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_abb_task_info(nas: str | None = None, task_id: int = 0) -> str:
        """Get detailed information about an Active Backup task."""
        try:
            abb = _abb(nas)
            result = abb.task_history(task_id=task_id)
            if not result or "data" not in result:
                return error_response(f"Task {task_id} not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "ABB task info")

    @mcp.tool(
        name="synology_abb_list_devices",
        annotations={"title": "List ABB Devices", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_abb_list_devices(nas: str | None = None) -> str:
        """List all devices registered with Active Backup for Business."""
        try:
            abb = _abb(nas)
            result = abb.list_device_transfer_size()
            if not result or "data" not in result:
                return error_response("Could not list ABB devices")
            devices = result["data"].get("device_list", result["data"].get("list", []))
            items = []
            if isinstance(devices, list):
                for d in devices:
                    items.append({
                        "id": d.get("device_id", d.get("id", "")),
                        "name": d.get("device_name", d.get("name", "")),
                        "status": d.get("status", ""),
                        "type": d.get("type", ""),
                        "ip": d.get("ip_address", d.get("ip", "")),
                        "last_backup": format_timestamp(d.get("last_backup_time")),
                    })
            return json.dumps({"devices": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List ABB devices")

    @mcp.tool(
        name="synology_abb_device_info",
        annotations={"title": "ABB Device Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_abb_device_info(device_id: int = 0, nas: str | None = None) -> str:
        """Get detailed information about a registered backup device."""
        try:
            abb = _abb(nas)
            result = abb.list_device_transfer_size(device_id=device_id)
            if not result or "data" not in result:
                return error_response(f"Device {device_id} not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "ABB device info")

    @mcp.tool(
        name="synology_abb_logs",
        annotations={"title": "ABB Backup Logs", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_abb_logs(nas: str | None = None) -> str:
        """Get recent Active Backup for Business logs and events."""
        try:
            abb = _abb(nas)
            result = abb.list_logs()
            if not result or "data" not in result:
                return error_response("Could not retrieve ABB logs")
            logs = result["data"].get("log_list", result["data"].get("list", []))
            items = []
            if isinstance(logs, list):
                for log in logs[:50]:  # Cap at 50 entries
                    items.append({
                        "time": format_timestamp(log.get("time")),
                        "level": log.get("log_level", log.get("level", "")),
                        "message": log.get("message", log.get("msg", "")),
                        "task": log.get("task_name", ""),
                    })
            return json.dumps({"logs": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "ABB logs")

    @mcp.tool(
        name="synology_abb_restore_points",
        annotations={"title": "ABB Restore Points", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_abb_restore_points(device_id: int = 0, nas: str | None = None) -> str:
        """List available restore points for a device."""
        try:
            abb = _abb(nas)
            result = abb.result_details(device_id=device_id)
            if not result or "data" not in result:
                return error_response(f"No restore points for device {device_id}")
            points = result["data"].get("restore_point_list", result["data"].get("list", []))
            items = []
            if isinstance(points, list):
                for rp in points:
                    items.append({
                        "id": rp.get("restore_point_id", rp.get("id", "")),
                        "time": format_timestamp(rp.get("backup_time", rp.get("time"))),
                        "size": format_size(int(rp.get("size", 0))) if rp.get("size") else "N/A",
                        "status": rp.get("status", ""),
                    })
            return json.dumps({
                "device_id": device_id,
                "restore_points": items,
                "count": len(items),
            }, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "ABB restore points")
