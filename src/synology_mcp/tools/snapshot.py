"""Snapshot Replication tools — manage Btrfs snapshots.

Covers: list snapshots, snapshot info, create, delete, and replication tasks.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, format_timestamp, handle_synology_error, error_response


class SnapshotNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class SnapshotShareInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    shared_folder: str = Field(..., description="Shared folder name (e.g., 'homes', 'data')", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class CreateSnapshotInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    shared_folder: str = Field(..., description="Shared folder name", min_length=1)
    description: Optional[str] = Field(default=None, description="Snapshot description")
    is_locked: bool = Field(default=False, description="Lock snapshot to prevent auto-removal")
    nas: Optional[str] = Field(default=None, description="NAS name")


class DeleteSnapshotInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    snapshot_id: str = Field(..., description="Snapshot ID to delete", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_snapshot_tools(mcp, conn_mgr) -> None:
    """Register Snapshot Replication tools."""

    def _snap(nas=None):
        return conn_mgr.get_client("snapshot", nas)

    @mcp.tool(
        name="synology_snapshot_list",
        annotations={"title": "List Snapshots", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_snapshot_list(params: SnapshotShareInput) -> str:
        """List all snapshots for a shared folder."""
        try:
            snap = _snap(params.nas)
            result = snap.list_snapshots(share_name=params.shared_folder)
            if not result or "data" not in result:
                return error_response(f"Could not list snapshots for '{params.shared_folder}'")
            snapshots = result["data"].get("snapshots", result["data"].get("list", []))
            items = []
            if isinstance(snapshots, list):
                for s in snapshots:
                    items.append({
                        "id": s.get("id", ""),
                        "description": s.get("desc", s.get("description", "")),
                        "time": format_timestamp(s.get("time", s.get("create_time"))),
                        "status": s.get("status", ""),
                        "locked": s.get("lock", s.get("is_locked", False)),
                        "size": format_size(int(s.get("size", 0))) if s.get("size") else "N/A",
                    })
            return json.dumps({
                "shared_folder": params.shared_folder,
                "snapshots": items,
                "count": len(items),
            }, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List snapshots")

    @mcp.tool(
        name="synology_snapshot_create",
        annotations={"title": "Create Snapshot", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_snapshot_create(params: CreateSnapshotInput) -> str:
        """Create a new Btrfs snapshot of a shared folder."""
        try:
            snap = _snap(params.nas)
            kwargs = {"share_name": params.shared_folder}
            if params.description:
                kwargs["desc"] = params.description
            if params.is_locked:
                kwargs["is_locked"] = params.is_locked
            result = snap.create_snapshot(**kwargs)
            return json.dumps({
                "status": "success",
                "action": "snapshot_created",
                "shared_folder": params.shared_folder,
                "description": params.description or "(none)",
                "locked": params.is_locked,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Create snapshot")

    @mcp.tool(
        name="synology_snapshot_delete",
        annotations={"title": "Delete Snapshot", "readOnlyHint": False, "destructiveHint": True},
    )
    async def synology_snapshot_delete(params: DeleteSnapshotInput) -> str:
        """Delete a snapshot by ID. This action cannot be undone."""
        try:
            snap = _snap(params.nas)
            result = snap.delete_snapshot(snapshot_id=params.snapshot_id)
            return json.dumps({
                "status": "success",
                "action": "snapshot_deleted",
                "snapshot_id": params.snapshot_id,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Delete snapshot")

    @mcp.tool(
        name="synology_snapshot_replication_list",
        annotations={"title": "List Replication Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_snapshot_replication_list(params: SnapshotNasInput) -> str:
        """List snapshot replication tasks (local and remote)."""
        try:
            snap = _snap(params.nas)
            result = snap.list_replication_tasks()
            if not result or "data" not in result:
                return error_response("Could not list replication tasks")
            tasks = result["data"].get("tasks", result["data"].get("list", []))
            items = []
            if isinstance(tasks, list):
                for t in tasks:
                    items.append({
                        "id": t.get("id", ""),
                        "name": t.get("name", ""),
                        "status": t.get("status", ""),
                        "source": t.get("src_share", ""),
                        "destination": t.get("dst_share", ""),
                        "schedule": t.get("schedule", ""),
                    })
            return json.dumps({"replication_tasks": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List replication tasks")
