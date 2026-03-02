"""User and Group management tools.

Covers: list users/groups, user info, create/delete users, group membership.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import handle_synology_error, error_response


class UserNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class UserInfoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    username: str = Field(..., description="Username to look up", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


class GroupInfoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    group_name: str = Field(..., description="Group name", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_users_groups_tools(mcp, conn_mgr) -> None:
    """Register User and Group management tools."""

    def _user(nas=None):
        return conn_mgr.get_client("user", nas)

    def _group(nas=None):
        return conn_mgr.get_client("group", nas)

    @mcp.tool(
        name="synology_list_users",
        annotations={"title": "List Users", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_users(params: UserNasInput) -> str:
        """List all local users on the NAS."""
        try:
            user = _user(params.nas)
            result = user.get_list_user()
            if not result or "data" not in result:
                return error_response("Could not list users")
            users = result["data"].get("users", result["data"])
            items = []
            if isinstance(users, list):
                for u in users:
                    items.append({
                        "name": u.get("name", ""),
                        "uid": u.get("uid", ""),
                        "description": u.get("description", ""),
                        "expired": u.get("expired", ""),
                    })
            return json.dumps({"users": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List users")

    @mcp.tool(
        name="synology_user_info",
        annotations={"title": "User Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_user_info(params: UserInfoInput) -> str:
        """Get detailed information about a specific user."""
        try:
            user = _user(params.nas)
            result = user.get_user(name=params.username)
            if not result or "data" not in result:
                return error_response(f"User '{params.username}' not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "User info")

    @mcp.tool(
        name="synology_list_groups",
        annotations={"title": "List Groups", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_groups(params: UserNasInput) -> str:
        """List all local groups on the NAS."""
        try:
            group = _group(params.nas)
            result = group.get_list_group()
            if not result or "data" not in result:
                return error_response("Could not list groups")
            groups = result["data"].get("groups", result["data"])
            items = []
            if isinstance(groups, list):
                for g in groups:
                    items.append({
                        "name": g.get("name", ""),
                        "gid": g.get("gid", ""),
                        "description": g.get("description", ""),
                    })
            return json.dumps({"groups": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List groups")

    @mcp.tool(
        name="synology_group_members",
        annotations={"title": "Group Members", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_group_members(params: GroupInfoInput) -> str:
        """List all members of a specific group."""
        try:
            group = _group(params.nas)
            result = group.get_group_member(name=params.group_name)
            if not result or "data" not in result:
                return error_response(f"Group '{params.group_name}' not found")
            members = result["data"].get("members", result["data"])
            return json.dumps({
                "group": params.group_name,
                "members": members,
                "count": len(members) if isinstance(members, list) else 0,
            }, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Group members")
