"""DownloadStation tools — download tasks, torrents, RSS, and scheduling.

Covers: list tasks, create download, pause/resume, delete, set priority,
and download station configuration.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, handle_synology_error, error_response


# ── Input Models ──────────────────────────────────────────────────────


class ListDownloadsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    nas: Optional[str] = Field(default=None, description="NAS name")


class CreateDownloadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    uri: str = Field(..., description="Download URL or magnet link", min_length=1)
    destination: Optional[str] = Field(default=None, description="Destination folder path on NAS (e.g., '/volume1/downloads')")
    nas: Optional[str] = Field(default=None, description="NAS name")


class DownloadTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_id: str = Field(..., description="Download task ID", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class DownloadMultiTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    task_ids: str = Field(..., description="Comma-separated task IDs", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class DownloadStationConfigInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class DownloadScheduleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    enabled: bool = Field(..., description="Enable or disable the download schedule")
    nas: Optional[str] = Field(default=None, description="NAS name")


# ── Tool Registration ─────────────────────────────────────────────────


def register_downloadstation_tools(mcp, conn_mgr) -> None:
    """Register all DownloadStation tools with the MCP server."""

    def _ds(nas: Optional[str] = None):
        return conn_mgr.get_client("downloadstation", nas)

    # ── List download tasks ──────────────────────────────────────

    @mcp.tool(
        name="synology_list_downloads",
        annotations={"title": "List Download Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_downloads(params: ListDownloadsInput) -> str:
        """List all download tasks (active, paused, completed, errored) on the NAS."""
        try:
            ds = _ds(params.nas)
            result = ds.get_list_of_tasks(offset=params.offset, limit=params.limit)
            if not result or "data" not in result:
                return error_response("Could not retrieve download tasks")
            data = result["data"]
            tasks = data.get("tasks", [])
            items = []
            for t in tasks:
                transfer = t.get("additional", {}).get("transfer", {})
                item = {
                    "id": t.get("id", ""),
                    "title": t.get("title", ""),
                    "status": t.get("status", ""),
                    "type": t.get("type", ""),
                    "size": format_size(int(t.get("size", 0))),
                }
                if transfer:
                    item["downloaded"] = format_size(int(transfer.get("size_downloaded", 0)))
                    item["uploaded"] = format_size(int(transfer.get("size_uploaded", 0)))
                    speed_down = int(transfer.get("speed_download", 0))
                    item["speed_down"] = f"{format_size(speed_down)}/s" if speed_down > 0 else "0"
                items.append(item)
            return json.dumps({
                "total": data.get("total", len(items)),
                "count": len(items),
                "offset": params.offset,
                "tasks": items,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "List downloads")

    # ── Create download ──────────────────────────────────────────

    @mcp.tool(
        name="synology_create_download",
        annotations={"title": "Create Download Task", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_create_download(params: CreateDownloadInput) -> str:
        """Create a new download task from a URL or magnet link.

        Supports HTTP, FTP, magnet, ed2k, and torrent URLs.
        """
        try:
            ds = _ds(params.nas)
            kwargs = {"uri": params.uri}
            if params.destination:
                kwargs["destination"] = params.destination
            result = ds.create_task(**kwargs)
            return json.dumps({
                "status": "success",
                "message": "Download task created",
                "uri": params.uri,
                "destination": params.destination or "(default)",
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Create download")

    # ── Pause tasks ──────────────────────────────────────────────

    @mcp.tool(
        name="synology_pause_download",
        annotations={"title": "Pause Download", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_pause_download(params: DownloadMultiTaskInput) -> str:
        """Pause one or more download tasks. Provide comma-separated task IDs."""
        try:
            ds = _ds(params.nas)
            ids = [tid.strip() for tid in params.task_ids.split(",") if tid.strip()]
            result = ds.pause_task(id=",".join(ids))
            return json.dumps({
                "status": "success",
                "action": "paused",
                "task_ids": ids,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Pause download")

    # ── Resume tasks ─────────────────────────────────────────────

    @mcp.tool(
        name="synology_resume_download",
        annotations={"title": "Resume Download", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_resume_download(params: DownloadMultiTaskInput) -> str:
        """Resume one or more paused download tasks."""
        try:
            ds = _ds(params.nas)
            ids = [tid.strip() for tid in params.task_ids.split(",") if tid.strip()]
            result = ds.resume_task(id=",".join(ids))
            return json.dumps({
                "status": "success",
                "action": "resumed",
                "task_ids": ids,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Resume download")

    # ── Delete tasks ─────────────────────────────────────────────

    @mcp.tool(
        name="synology_delete_download",
        annotations={"title": "Delete Download Task", "readOnlyHint": False, "destructiveHint": True},
    )
    async def synology_delete_download(params: DownloadMultiTaskInput) -> str:
        """Delete download tasks. This removes the task entry (downloaded files remain on disk)."""
        try:
            ds = _ds(params.nas)
            ids = [tid.strip() for tid in params.task_ids.split(",") if tid.strip()]
            result = ds.delete_task(id=",".join(ids))
            return json.dumps({
                "status": "success",
                "action": "deleted",
                "task_ids": ids,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Delete download")

    # ── Download task info ───────────────────────────────────────

    @mcp.tool(
        name="synology_download_info",
        annotations={"title": "Download Task Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_download_info(params: DownloadTaskInput) -> str:
        """Get detailed information about a specific download task."""
        try:
            ds = _ds(params.nas)
            result = ds.get_task_info(id=params.task_id)
            if not result or "data" not in result:
                return error_response(f"Task not found: {params.task_id}")
            tasks = result["data"].get("tasks", [])
            if tasks:
                return json.dumps(tasks[0], indent=2, default=str)
            return error_response(f"No details for task: {params.task_id}")
        except Exception as e:
            return handle_synology_error(e, "Download info")

    # ── Download Station config ──────────────────────────────────

    @mcp.tool(
        name="synology_download_config",
        annotations={"title": "Download Station Config", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_download_config(params: DownloadStationConfigInput) -> str:
        """Get current Download Station configuration (default destination, speed limits, etc.)."""
        try:
            ds = _ds(params.nas)
            result = ds.get_config()
            if not result or "data" not in result:
                return error_response("Could not retrieve Download Station config")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Download config")

    # ── Download station statistics ──────────────────────────────

    @mcp.tool(
        name="synology_download_stats",
        annotations={"title": "Download Statistics", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_download_stats(params: DownloadStationConfigInput) -> str:
        """Get Download Station transfer statistics — current speeds and bandwidth usage."""
        try:
            ds = _ds(params.nas)
            result = ds.get_statistic()
            if not result or "data" not in result:
                return error_response("Could not retrieve download statistics")
            data = result["data"]
            stats = {
                "download_speed": f"{format_size(int(data.get('speed_download', 0)))}/s",
                "upload_speed": f"{format_size(int(data.get('speed_upload', 0)))}/s",
            }
            return json.dumps(stats, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Download statistics")
