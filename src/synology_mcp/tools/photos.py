"""Synology Photos tools — albums, browsing, and sharing.

Covers: list albums, browse photos, search, share albums, and photo info.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, format_timestamp, handle_synology_error, error_response


class PhotosNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class AlbumInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    album_id: int = Field(..., description="Album ID")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    nas: Optional[str] = Field(default=None, description="NAS name")


class PhotoSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    keyword: str = Field(..., description="Search keyword", min_length=1)
    limit: int = Field(default=50, ge=1, le=500)
    nas: Optional[str] = Field(default=None, description="NAS name")


class BrowsePhotosInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    folder_id: Optional[int] = Field(default=None, description="Folder ID to browse (root if omitted)")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_photos_tools(mcp, conn_mgr) -> None:
    """Register Synology Photos tools."""

    def _photos(nas=None):
        return conn_mgr.get_client("photos", nas)

    @mcp.tool(
        name="synology_photos_list_albums",
        annotations={"title": "List Photo Albums", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_photos_list_albums(params: PhotosNasInput) -> str:
        """List all photo albums on Synology Photos."""
        try:
            ph = _photos(params.nas)
            result = ph.get_albums()
            if not result or "data" not in result:
                return error_response("Could not list albums")
            albums = result["data"].get("list", result["data"])
            items = []
            if isinstance(albums, list):
                for a in albums:
                    items.append({
                        "id": a.get("id", ""),
                        "name": a.get("name", ""),
                        "item_count": a.get("item_count", 0),
                        "type": a.get("type", ""),
                    })
            return json.dumps({"albums": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List albums")

    @mcp.tool(
        name="synology_photos_browse",
        annotations={"title": "Browse Photos", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_photos_browse(params: BrowsePhotosInput) -> str:
        """Browse photos in the personal or shared space with pagination."""
        try:
            ph = _photos(params.nas)
            kwargs = {"offset": params.offset, "limit": params.limit}
            if params.folder_id is not None:
                kwargs["folder_id"] = params.folder_id
            result = ph.get_items(**kwargs)
            if not result or "data" not in result:
                return error_response("Could not browse photos")
            items_data = result["data"].get("list", [])
            items = []
            for p in items_data:
                items.append({
                    "id": p.get("id", ""),
                    "filename": p.get("filename", ""),
                    "type": p.get("type", ""),
                    "filesize": format_size(int(p.get("filesize", 0))),
                    "time": format_timestamp(p.get("time")),
                })
            return json.dumps({
                "count": len(items),
                "offset": params.offset,
                "items": items,
            }, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Browse photos")

    @mcp.tool(
        name="synology_photos_search",
        annotations={"title": "Search Photos", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_photos_search(params: PhotoSearchInput) -> str:
        """Search photos by keyword (filename, tag, or description)."""
        try:
            ph = _photos(params.nas)
            result = ph.search(keyword=params.keyword, limit=params.limit)
            if not result or "data" not in result:
                return error_response("Search returned no results")
            items = result["data"].get("list", [])
            return json.dumps({
                "keyword": params.keyword,
                "count": len(items),
                "items": items,
            }, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Search photos")

    @mcp.tool(
        name="synology_photos_album_items",
        annotations={"title": "Get Album Photos", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_photos_album_items(params: AlbumInput) -> str:
        """List photos/videos within a specific album."""
        try:
            ph = _photos(params.nas)
            result = ph.get_album_items(
                album_id=params.album_id,
                offset=params.offset,
                limit=params.limit,
            )
            if not result or "data" not in result:
                return error_response(f"Could not get items for album {params.album_id}")
            items = result["data"].get("list", [])
            return json.dumps({
                "album_id": params.album_id,
                "count": len(items),
                "offset": params.offset,
                "items": items,
            }, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Album items")
