"""Shared Folder and Permission tools.

Covers: list shared folders, folder info, permissions, and quota management.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, handle_synology_error, error_response


class ShareNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class ShareInfoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Shared folder name", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class SharePermissionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Shared folder name", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_shares_tools(mcp, conn_mgr) -> None:
    """Register Shared Folder and Permission tools."""

    def _share(nas=None):
        return conn_mgr.get_client("share", nas)

    def _perm(nas=None):
        return conn_mgr.get_client("share_permission", nas)

    @mcp.tool(
        name="synology_shared_folders",
        annotations={"title": "List Shared Folders (Admin)", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_shared_folders(params: ShareNasInput) -> str:
        """List all shared folders with their volume, encryption, and recycle bin status."""
        try:
            share = _share(params.nas)
            result = share.get_share_list()
            if not result or "data" not in result:
                return error_response("Could not list shared folders")
            shares = result["data"].get("shares", result["data"])
            items = []
            if isinstance(shares, list):
                for s in shares:
                    items.append({
                        "name": s.get("name", ""),
                        "path": s.get("vol_path", s.get("path", "")),
                        "description": s.get("desc", ""),
                        "encryption": s.get("encryption", 0),
                        "recycle_bin": s.get("enable_recycle_bin", False),
                    })
            return json.dumps({"shares": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List shared folders")

    @mcp.tool(
        name="synology_shared_folder_info",
        annotations={"title": "Shared Folder Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_shared_folder_info(params: ShareInfoInput) -> str:
        """Get detailed info about a specific shared folder (volume, quota, encryption)."""
        try:
            share = _share(params.nas)
            result = share.get_share_info(name=params.name)
            if not result or "data" not in result:
                return error_response(f"Shared folder '{params.name}' not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Shared folder info")

    @mcp.tool(
        name="synology_shared_folder_permissions",
        annotations={"title": "Shared Folder Permissions", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_shared_folder_permissions(params: SharePermissionInput) -> str:
        """Get permission (ACL) settings for a shared folder — who can read/write."""
        try:
            perm = _perm(params.nas)
            result = perm.get_share_permission(name=params.name)
            if not result or "data" not in result:
                return error_response(f"Could not get permissions for '{params.name}'")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Folder permissions")
