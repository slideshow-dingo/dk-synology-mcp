"""CloudSync tools — manage cloud synchronization connections and tasks.

Covers: list connections, sync status, start/pause/resume sync,
connection logs, and traffic control.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import handle_synology_error, error_response


class CloudSyncNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class CloudSyncConnectionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    connection_id: int = Field(..., description="Cloud Sync connection ID")
    nas: Optional[str] = Field(default=None, description="NAS name")


class CloudSyncLogInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    connection_id: int = Field(..., description="Cloud Sync connection ID")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_cloudsync_tools(mcp, conn_mgr) -> None:
    """Register Cloud Sync tools."""

    def _cs(nas=None):
        return conn_mgr.get_client("cloudsync", nas)

    @mcp.tool(
        name="synology_cloudsync_list",
        annotations={"title": "List Cloud Sync Connections", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_cloudsync_list(params: CloudSyncNasInput) -> str:
        """List all Cloud Sync connections and their current status."""
        try:
            cs = _cs(params.nas)
            result = cs.get_connections()
            if not result or "data" not in result:
                return error_response("Could not list Cloud Sync connections")
            conns = result["data"].get("conn", result["data"])
            items = []
            if isinstance(conns, list):
                for c in conns:
                    items.append({
                        "id": c.get("id", ""),
                        "cloud_type": c.get("cloud_type", ""),
                        "local_path": c.get("path", ""),
                        "status": c.get("status", ""),
                        "direction": c.get("sync_direction", ""),
                    })
            return json.dumps({"connections": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List Cloud Sync")

    @mcp.tool(
        name="synology_cloudsync_status",
        annotations={"title": "Cloud Sync Connection Status", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_cloudsync_status(params: CloudSyncConnectionInput) -> str:
        """Get detailed status for a specific Cloud Sync connection."""
        try:
            cs = _cs(params.nas)
            result = cs.get_connection_status(conn_id=params.connection_id)
            if not result or "data" not in result:
                return error_response(f"No status for connection {params.connection_id}")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Cloud Sync status")

    @mcp.tool(
        name="synology_cloudsync_pause",
        annotations={"title": "Pause Cloud Sync", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_cloudsync_pause(params: CloudSyncConnectionInput) -> str:
        """Pause a Cloud Sync connection."""
        try:
            cs = _cs(params.nas)
            result = cs.pause_connection(conn_id=params.connection_id)
            return json.dumps({"status": "success", "action": "paused", "connection_id": params.connection_id}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Pause Cloud Sync")

    @mcp.tool(
        name="synology_cloudsync_resume",
        annotations={"title": "Resume Cloud Sync", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_cloudsync_resume(params: CloudSyncConnectionInput) -> str:
        """Resume a paused Cloud Sync connection."""
        try:
            cs = _cs(params.nas)
            result = cs.resume_connection(conn_id=params.connection_id)
            return json.dumps({"status": "success", "action": "resumed", "connection_id": params.connection_id}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Resume Cloud Sync")

    @mcp.tool(
        name="synology_cloudsync_logs",
        annotations={"title": "Cloud Sync Logs", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_cloudsync_logs(params: CloudSyncLogInput) -> str:
        """Get recent sync logs for a Cloud Sync connection."""
        try:
            cs = _cs(params.nas)
            result = cs.get_connection_log(conn_id=params.connection_id, offset=params.offset, limit=params.limit)
            if not result or "data" not in result:
                return error_response("Could not retrieve Cloud Sync logs")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Cloud Sync logs")
