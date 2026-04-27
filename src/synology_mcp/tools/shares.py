"""Shared Folder and Permission tools.

Covers: list shared folders, folder info, permissions, and quota management.

Note: synology-api's Share.list_folders() and related methods fail with
KeyError('SYNO.Core.Share') because the API isn't enumerated in core_list
during authentication.  We fall back to request_data() with a known API
path when this happens.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, handle_synology_error, error_response

# Known API paths for SYNO.Core.Share — used as fallback when the API
# isn't in the session's core_list (common on DSM 7).
_SHARE_API = "SYNO.Core.Share"
_SHARE_PATH = "entry.cgi"
_SHARE_PERM_API = "SYNO.Core.Share.Permission"
_SHARE_PERM_PATH = "entry.cgi"


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


def _direct_share_list(client) -> dict:
    """Call SYNO.Core.Share list directly, bypassing core_list lookup."""
    req_param = {
        "method": "list",
        "version": 1,
        "shareType": "all",
        "additional": json.dumps([
            "encryption", "is_aclmode", "unite_permission",
            "vol_path", "enable_recycle_bin", "description",
        ]),
    }
    return client.request_data(_SHARE_API, _SHARE_PATH, req_param)


def _direct_share_get(client, name: str) -> dict:
    """Call SYNO.Core.Share get directly, bypassing core_list lookup."""
    req_param = {
        "method": "get",
        "version": 1,
        "name": name,
        "additional": json.dumps([
            "encryption", "is_aclmode", "unite_permission",
            "vol_path", "enable_recycle_bin", "description",
        ]),
    }
    return client.request_data(_SHARE_API, _SHARE_PATH, req_param)


def _direct_share_permissions(client, name: str) -> dict:
    """Call SYNO.Core.Share.Permission list_by_share directly."""
    req_param = {
        "method": "list_by_share",
        "version": 1,
        "name": name,
    }
    return client.request_data(_SHARE_PERM_API, _SHARE_PERM_PATH, req_param)


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
    async def synology_shared_folders(nas: str | None = None) -> str:
        """List all shared folders with their volume, encryption, and recycle bin status."""
        try:
            share = _share(nas)
            # Try normal method first; fall back to direct API call if
            # core_list doesn't contain SYNO.Core.Share (KeyError).
            try:
                result = share.list_folders()
            except KeyError:
                result = _direct_share_list(share)
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
    async def synology_shared_folder_info(nas: str | None = None, name: str | None = None) -> str:
        """Get detailed info about a specific shared folder (volume, quota, encryption)."""
        try:
            share = _share(nas)
            try:
                result = share.get_folder(name=name)
            except KeyError:
                result = _direct_share_get(share, name)
            if not result or "data" not in result:
                return error_response(f"Shared folder '{name}' not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Shared folder info")

    @mcp.tool(
        name="synology_shared_folder_permissions",
        annotations={"title": "Shared Folder Permissions", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_shared_folder_permissions(nas: str | None = None, name: str | None = None) -> str:
        """Get permission (ACL) settings for a shared folder — who can read/write."""
        try:
            perm = _perm(nas)
            try:
                result = perm.get_folder_permissions(name=name)
            except KeyError:
                result = _direct_share_permissions(perm, name)
            if not result or "data" not in result:
                return error_response(f"Could not get permissions for '{name}'")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Folder permissions")
