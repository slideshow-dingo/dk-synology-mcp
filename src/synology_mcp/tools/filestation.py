"""FileStation tools — comprehensive file and folder management.

Covers: browse, list, search, create, copy, move, rename, delete,
compress, extract, upload, share links, favorites, and background tasks.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import (
    ResponseFormat,
    format_size,
    format_timestamp,
    handle_synology_error,
    error_response,
    paginate_list,
)


# ── Input Models ──────────────────────────────────────────────────────


class ListFilesInput(BaseModel):
    """Input for listing files and folders."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Folder path to list (e.g., '/volume1/homes')", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name. Uses default if omitted.")
    offset: int = Field(default=0, description="Pagination offset", ge=0)
    limit: int = Field(default=50, description="Max items to return", ge=1, le=1000)
    sort_by: Optional[str] = Field(default=None, description="Sort field: name, size, mtime, crtime, type")
    sort_direction: Optional[str] = Field(default=None, description="Sort direction: asc or desc")
    file_type: Optional[str] = Field(default=None, description="Filter: 'file', 'dir', or 'all' (default)")
    pattern: Optional[str] = Field(default=None, description="Filename pattern filter (e.g., '*.jpg')")


class GetFileInfoInput(BaseModel):
    """Input for getting detailed file/folder info."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Full path to file or folder", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class SearchFilesInput(BaseModel):
    """Input for searching files across the NAS."""
    model_config = ConfigDict(str_strip_whitespace=True)

    folder_path: str = Field(..., description="Root folder to search within", min_length=1)
    pattern: str = Field(..., description="Search pattern (e.g., '*.pdf', 'report')", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")
    extension: Optional[str] = Field(default=None, description="File extension filter (e.g., 'pdf')")
    limit: int = Field(default=100, description="Max results", ge=1, le=1000)


class CreateFolderInput(BaseModel):
    """Input for creating one or more folders."""
    model_config = ConfigDict(str_strip_whitespace=True)

    folder_path: str = Field(..., description="Parent path where folder(s) will be created", min_length=1)
    name: str = Field(..., description="Name for the new folder (or comma-separated names for multiple)", min_length=1)
    force_parent: bool = Field(default=False, description="Create parent directories if they don't exist")
    nas: Optional[str] = Field(default=None, description="NAS name")


class RenameInput(BaseModel):
    """Input for renaming a file or folder."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Full path of the file/folder to rename", min_length=1)
    name: str = Field(..., description="New name (just the name, not full path)", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class CopyMoveInput(BaseModel):
    """Input for copying or moving files/folders."""
    model_config = ConfigDict(str_strip_whitespace=True)

    paths: str = Field(..., description="Source path(s), comma-separated for multiple", min_length=1)
    dest_folder: str = Field(..., description="Destination folder path", min_length=1)
    overwrite: bool = Field(default=False, description="Overwrite existing files at destination")
    remove_src: bool = Field(default=False, description="True = move (delete source after copy), False = copy only")
    nas: Optional[str] = Field(default=None, description="NAS name")


class DeleteInput(BaseModel):
    """Input for deleting files/folders."""
    model_config = ConfigDict(str_strip_whitespace=True)

    paths: str = Field(..., description="Path(s) to delete, comma-separated for multiple", min_length=1)
    recursive: bool = Field(default=True, description="Recursively delete folder contents")
    nas: Optional[str] = Field(default=None, description="NAS name")


class CompressInput(BaseModel):
    """Input for compressing files/folders into an archive."""
    model_config = ConfigDict(str_strip_whitespace=True)

    paths: str = Field(..., description="Path(s) to compress, comma-separated for multiple", min_length=1)
    dest_file_path: str = Field(..., description="Full destination path for the archive (e.g., '/volume1/archives/backup.zip')")
    format: str = Field(default="zip", description="Archive format: zip, 7z, or gz")
    nas: Optional[str] = Field(default=None, description="NAS name")


class ExtractInput(BaseModel):
    """Input for extracting an archive."""
    model_config = ConfigDict(str_strip_whitespace=True)

    file_path: str = Field(..., description="Path to the archive file", min_length=1)
    dest_folder: str = Field(..., description="Destination folder to extract into", min_length=1)
    overwrite: bool = Field(default=False, description="Overwrite existing files")
    keep_dir: bool = Field(default=True, description="Keep directory structure from archive")
    nas: Optional[str] = Field(default=None, description="NAS name")


class ShareLinkInput(BaseModel):
    """Input for creating a sharing link."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Path to file/folder to share", min_length=1)
    password: Optional[str] = Field(default=None, description="Optional password to protect the link")
    expire_days: Optional[int] = Field(default=None, description="Days until link expires (omit for permanent)", ge=1, le=365)
    nas: Optional[str] = Field(default=None, description="NAS name")


class ListShareLinksInput(BaseModel):
    """Input for listing existing share links."""
    model_config = ConfigDict(str_strip_whitespace=True)

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    nas: Optional[str] = Field(default=None, description="NAS name")


class ListSharesInput(BaseModel):
    """Input for listing shared folders (volumes)."""
    model_config = ConfigDict(str_strip_whitespace=True)

    nas: Optional[str] = Field(default=None, description="NAS name")


class DirSizeInput(BaseModel):
    """Input for calculating directory size."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Folder path to calculate size for", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class BackgroundTasksInput(BaseModel):
    """Input for listing background file tasks."""
    model_config = ConfigDict(str_strip_whitespace=True)

    nas: Optional[str] = Field(default=None, description="NAS name")


class UploadFileInput(BaseModel):
    """Input for uploading a file."""
    model_config = ConfigDict(str_strip_whitespace=True)

    dest_path: str = Field(..., description="Destination folder path on NAS", min_length=1)
    file_path: str = Field(..., description="Local file path to upload", min_length=1)
    overwrite: bool = Field(default=False, description="Overwrite if file exists")
    nas: Optional[str] = Field(default=None, description="NAS name")


class GetFileInput(BaseModel):
    """Input for downloading a file from NAS."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Full path to file on NAS", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class FileTreeInput(BaseModel):
    """Input for generating a file tree."""
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(..., description="Root folder path", min_length=1)
    depth: int = Field(default=3, description="Max depth to traverse", ge=1, le=10)
    nas: Optional[str] = Field(default=None, description="NAS name")


# ── Tool Registration ─────────────────────────────────────────────────


def register_filestation_tools(mcp, conn_mgr) -> None:
    """Register all FileStation tools with the MCP server."""

    def _fs(nas: Optional[str] = None):
        return conn_mgr.get_client("filestation", nas)

    # ── List files ────────────────────────────────────────────────

    @mcp.tool(
        name="synology_list_files",
        annotations={
            "title": "List Files and Folders",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def synology_list_files(params: ListFilesInput) -> str:
        """List files and folders in a directory on the Synology NAS.

        Returns file names, sizes, types, and modification times with pagination support.
        Use this to browse the NAS filesystem.
        """
        try:
            fs = _fs(params.nas)
            kwargs = {"folder_path": params.path}
            if params.sort_by:
                kwargs["sort_by"] = params.sort_by
            if params.sort_direction:
                kwargs["sort_direction"] = params.sort_direction
            if params.file_type and params.file_type != "all":
                kwargs["filetype"] = params.file_type
            if params.pattern:
                kwargs["pattern"] = params.pattern
            kwargs["offset"] = params.offset
            kwargs["limit"] = params.limit

            result = fs.get_file_list(**kwargs)

            if not result or "data" not in result:
                return error_response(f"Could not list files at '{params.path}'", "Verify the path exists.")

            files = result["data"].get("files", [])
            total = result["data"].get("total", len(files))

            items = []
            for f in files:
                item = {
                    "name": f.get("name", ""),
                    "path": f.get("path", ""),
                    "is_dir": f.get("isdir", False),
                }
                additional = f.get("additional", {})
                if "size" in additional:
                    item["size"] = additional["size"]
                    item["size_human"] = format_size(additional["size"])
                if "time" in additional:
                    time_info = additional["time"]
                    item["modified"] = format_timestamp(time_info.get("mtime"))
                    item["created"] = format_timestamp(time_info.get("crtime"))
                if "real_path" in additional:
                    item["real_path"] = additional["real_path"]
                items.append(item)

            return json.dumps({
                "path": params.path,
                "total": total,
                "count": len(items),
                "offset": params.offset,
                "has_more": total > params.offset + len(items),
                "next_offset": params.offset + len(items) if total > params.offset + len(items) else None,
                "items": items,
            }, indent=2)

        except Exception as e:
            return handle_synology_error(e, "List files")

    # ── Get file info ─────────────────────────────────────────────

    @mcp.tool(
        name="synology_get_file_info",
        annotations={"title": "Get File Info", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_get_file_info(params: GetFileInfoInput) -> str:
        """Get detailed information about a specific file or folder including size, permissions, and timestamps."""
        try:
            fs = _fs(params.nas)
            result = fs.get_file_info(path=params.path)
            if not result or "data" not in result:
                return error_response(f"File not found: '{params.path}'")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Get file info")

    # ── Search files ──────────────────────────────────────────────

    @mcp.tool(
        name="synology_search_files",
        annotations={"title": "Search Files", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_search_files(params: SearchFilesInput) -> str:
        """Search for files by name pattern within a folder. Supports wildcards and extension filters.

        Note: This starts an async search on the NAS. Results may take a moment for large directories.
        """
        try:
            fs = _fs(params.nas)
            # Start search
            kwargs = {"folder_path": params.folder_path, "pattern": params.pattern}
            if params.extension:
                kwargs["extension"] = params.extension

            start_result = fs.search_start(**kwargs)
            if not start_result or "data" not in start_result:
                return error_response("Failed to start search")

            taskid = start_result["data"].get("taskid")
            if not taskid:
                return error_response("No search task ID returned")

            # Get results
            import time
            for _ in range(20):  # Poll up to ~10 seconds
                time.sleep(0.5)
                search_result = fs.get_search_list(taskid=taskid, limit=params.limit)
                if search_result and "data" in search_result:
                    finished = search_result["data"].get("finished", False)
                    files = search_result["data"].get("files", [])
                    if finished or len(files) >= params.limit:
                        break

            # Clean up
            try:
                fs.stop_search_task(taskid=taskid)
            except Exception:
                pass

            items = []
            for f in files:
                items.append({
                    "name": f.get("name", ""),
                    "path": f.get("path", ""),
                    "is_dir": f.get("isdir", False),
                })

            return json.dumps({
                "pattern": params.pattern,
                "folder": params.folder_path,
                "total_found": len(items),
                "items": items,
            }, indent=2)

        except Exception as e:
            return handle_synology_error(e, "Search files")

    # ── List shared folders (volumes) ─────────────────────────────

    @mcp.tool(
        name="synology_list_shares",
        annotations={"title": "List Shared Folders", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_shares(params: ListSharesInput) -> str:
        """List all shared folders (top-level volumes/shares) on the NAS."""
        try:
            fs = _fs(params.nas)
            result = fs.get_list_share()
            if not result or "data" not in result:
                return error_response("Could not list shared folders")
            shares = result["data"].get("shares", [])
            items = []
            for s in shares:
                item = {"name": s.get("name", ""), "path": s.get("path", "")}
                additional = s.get("additional", {})
                if "real_path" in additional:
                    item["real_path"] = additional["real_path"]
                if "volume_status" in additional:
                    item["volume_status"] = additional["volume_status"]
                items.append(item)
            return json.dumps({"shares": items, "count": len(items)}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "List shares")

    # ── Create folder ─────────────────────────────────────────────

    @mcp.tool(
        name="synology_create_folder",
        annotations={"title": "Create Folder", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_create_folder(params: CreateFolderInput) -> str:
        """Create one or more new folders on the NAS.

        Provide a comma-separated list of names to create multiple folders at once.
        """
        try:
            fs = _fs(params.nas)
            result = fs.create_folder(
                folder_path=params.folder_path,
                name=params.name,
                force_parent=params.force_parent,
            )
            if not result or "data" not in result:
                return error_response(f"Failed to create folder(s) '{params.name}' in '{params.folder_path}'")
            folders = result["data"].get("folders", [])
            created = [{"name": f.get("name", ""), "path": f.get("path", "")} for f in folders]
            return json.dumps({"status": "success", "created": created}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Create folder")

    # ── Rename ────────────────────────────────────────────────────

    @mcp.tool(
        name="synology_rename",
        annotations={"title": "Rename File/Folder", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_rename(params: RenameInput) -> str:
        """Rename a file or folder on the NAS."""
        try:
            fs = _fs(params.nas)
            result = fs.rename_folder(path=params.path, name=params.name)
            if not result or "data" not in result:
                return error_response(f"Failed to rename '{params.path}' to '{params.name}'")
            files = result["data"].get("files", [])
            if files:
                return json.dumps({
                    "status": "success",
                    "old_path": params.path,
                    "new_name": params.name,
                    "new_path": files[0].get("path", ""),
                }, indent=2)
            return json.dumps({"status": "success", "message": f"Renamed to '{params.name}'"})
        except Exception as e:
            return handle_synology_error(e, "Rename")

    # ── Copy / Move ───────────────────────────────────────────────

    @mcp.tool(
        name="synology_copy_move",
        annotations={"title": "Copy or Move Files", "readOnlyHint": False, "destructiveHint": True},
    )
    async def synology_copy_move(params: CopyMoveInput) -> str:
        """Copy or move files/folders to a destination.

        Set remove_src=True to move (deletes originals after copy). Comma-separate paths for batch operations.
        """
        try:
            fs = _fs(params.nas)
            paths_list = [p.strip() for p in params.paths.split(",") if p.strip()]
            path_str = json.dumps(paths_list)
            result = fs.start_copy_move(
                path=path_str,
                dest_folder_path=params.dest_folder,
                overwrite=params.overwrite,
                remove_src=params.remove_src,
            )
            op = "Move" if params.remove_src else "Copy"
            if result and "data" in result:
                taskid = result["data"].get("taskid", "")
                return json.dumps({
                    "status": "started",
                    "operation": op.lower(),
                    "taskid": taskid,
                    "sources": paths_list,
                    "destination": params.dest_folder,
                    "message": f"{op} task started. Use synology_list_background_tasks to check progress.",
                }, indent=2)
            return error_response(f"Failed to start {op.lower()} operation")
        except Exception as e:
            return handle_synology_error(e, "Copy/Move")

    # ── Delete ────────────────────────────────────────────────────

    @mcp.tool(
        name="synology_delete",
        annotations={"title": "Delete Files/Folders", "readOnlyHint": False, "destructiveHint": True},
    )
    async def synology_delete(params: DeleteInput) -> str:
        """Delete files or folders from the NAS.

        WARNING: This is a destructive operation. Comma-separate paths for batch deletion.
        """
        try:
            fs = _fs(params.nas)
            paths_list = [p.strip() for p in params.paths.split(",") if p.strip()]
            path_str = json.dumps(paths_list)
            result = fs.start_delete_task(path=path_str, recursive=params.recursive)
            if result and "data" in result:
                taskid = result["data"].get("taskid", "")
                return json.dumps({
                    "status": "started",
                    "taskid": taskid,
                    "paths": paths_list,
                    "message": "Delete task started. Use synology_list_background_tasks to check progress.",
                }, indent=2)
            return error_response("Failed to start delete operation")
        except Exception as e:
            return handle_synology_error(e, "Delete")

    # ── Compress ──────────────────────────────────────────────────

    @mcp.tool(
        name="synology_compress",
        annotations={"title": "Compress Files", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_compress(params: CompressInput) -> str:
        """Compress files/folders into a zip, 7z, or gz archive on the NAS."""
        try:
            fs = _fs(params.nas)
            paths_list = [p.strip() for p in params.paths.split(",") if p.strip()]
            path_str = json.dumps(paths_list)
            result = fs.start_file_compression(
                path=path_str,
                dest_file_path=params.dest_file_path,
                format=params.format,
            )
            if result and "data" in result:
                taskid = result["data"].get("taskid", "")
                return json.dumps({
                    "status": "started",
                    "taskid": taskid,
                    "destination": params.dest_file_path,
                    "format": params.format,
                }, indent=2)
            return error_response("Failed to start compression")
        except Exception as e:
            return handle_synology_error(e, "Compress")

    # ── Extract ───────────────────────────────────────────────────

    @mcp.tool(
        name="synology_extract",
        annotations={"title": "Extract Archive", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_extract(params: ExtractInput) -> str:
        """Extract a compressed archive (zip, 7z, gz, tar, etc.) to a folder on the NAS."""
        try:
            fs = _fs(params.nas)
            result = fs.start_extract_task(
                file_path=params.file_path,
                dest_folder_path=params.dest_folder,
                overwrite=params.overwrite,
                keep_dir=params.keep_dir,
            )
            if result and "data" in result:
                taskid = result["data"].get("taskid", "")
                return json.dumps({
                    "status": "started",
                    "taskid": taskid,
                    "destination": params.dest_folder,
                }, indent=2)
            return error_response("Failed to start extraction")
        except Exception as e:
            return handle_synology_error(e, "Extract")

    # ── Create share link ─────────────────────────────────────────

    @mcp.tool(
        name="synology_create_share_link",
        annotations={"title": "Create Share Link", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_create_share_link(params: ShareLinkInput) -> str:
        """Create a shareable download link for a file or folder on the NAS."""
        try:
            fs = _fs(params.nas)
            kwargs = {"path": params.path}
            if params.password:
                kwargs["password"] = params.password
            if params.expire_days:
                kwargs["date_expired"] = str(params.expire_days)
            result = fs.create_sharing_link(**kwargs)
            if not result or "data" not in result:
                return error_response("Failed to create share link")
            links = result["data"].get("links", [])
            if links:
                link = links[0]
                return json.dumps({
                    "status": "success",
                    "url": link.get("url", ""),
                    "path": link.get("path", params.path),
                    "has_password": bool(params.password),
                    "expires": f"{params.expire_days} days" if params.expire_days else "never",
                }, indent=2)
            return json.dumps({"status": "success", "data": result["data"]}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Create share link")

    # ── List share links ──────────────────────────────────────────

    @mcp.tool(
        name="synology_list_share_links",
        annotations={"title": "List Share Links", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_share_links(params: ListShareLinksInput) -> str:
        """List all active sharing links on the NAS."""
        try:
            fs = _fs(params.nas)
            result = fs.get_shared_link_list(offset=params.offset, limit=params.limit)
            if not result or "data" not in result:
                return error_response("Could not list share links")
            links = result["data"].get("links", [])
            items = []
            for link in links:
                items.append({
                    "url": link.get("url", ""),
                    "path": link.get("path", ""),
                    "status": link.get("status", ""),
                    "has_password": link.get("has_password", False),
                    "expire_date": link.get("date_expired", "never"),
                })
            return json.dumps({
                "total": result["data"].get("total", len(items)),
                "count": len(items),
                "links": items,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "List share links")

    # ── Calculate directory size ──────────────────────────────────

    @mcp.tool(
        name="synology_dir_size",
        annotations={"title": "Calculate Directory Size", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_dir_size(params: DirSizeInput) -> str:
        """Start a directory size calculation. Returns a task ID — poll with synology_list_background_tasks."""
        try:
            fs = _fs(params.nas)
            result = fs.start_dir_size_calc(path=params.path)
            if result and "data" in result:
                taskid = result["data"].get("taskid", "")
                return json.dumps({
                    "status": "started",
                    "taskid": taskid,
                    "path": params.path,
                    "message": "Size calculation started. Check status with synology_list_background_tasks.",
                }, indent=2)
            return error_response("Failed to start size calculation")
        except Exception as e:
            return handle_synology_error(e, "Directory size")

    # ── Background tasks ──────────────────────────────────────────

    @mcp.tool(
        name="synology_list_background_tasks",
        annotations={"title": "List Background Tasks", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_background_tasks(params: BackgroundTasksInput) -> str:
        """List all running background file tasks (copy, move, delete, compress, extract, size calc)."""
        try:
            fs = _fs(params.nas)
            result = fs.get_list_of_all_background_task()
            if not result or "data" not in result:
                return json.dumps({"tasks": [], "count": 0})
            tasks = result["data"].get("tasks", [])
            return json.dumps({"tasks": tasks, "count": len(tasks)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List background tasks")

    # ── Upload file ───────────────────────────────────────────────

    @mcp.tool(
        name="synology_upload_file",
        annotations={"title": "Upload File", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_upload_file(params: UploadFileInput) -> str:
        """Upload a file from the local machine to the NAS."""
        try:
            fs = _fs(params.nas)
            result = fs.upload_file(
                dest_path=params.dest_path,
                file_path=params.file_path,
                overwrite=params.overwrite,
            )
            return json.dumps({
                "status": "success",
                "file": params.file_path,
                "destination": params.dest_path,
            }, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Upload file")

    # ── File tree ─────────────────────────────────────────────────

    @mcp.tool(
        name="synology_file_tree",
        annotations={"title": "Generate File Tree", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_file_tree(params: FileTreeInput) -> str:
        """Generate a visual file tree for a directory, showing the folder structure up to a given depth."""
        try:
            fs = _fs(params.nas)
            result = fs.generate_file_tree(path=params.path)
            if result and "data" in result:
                return json.dumps(result["data"], indent=2, default=str)
            return error_response("Failed to generate file tree")
        except Exception as e:
            return handle_synology_error(e, "File tree")
