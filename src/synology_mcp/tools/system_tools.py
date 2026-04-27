"""Cross-cutting system tools — NAS connection management and diagnostics.

Covers: list connections, test connectivity, switch NAS, and server capabilities.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import handle_synology_error, error_response


class EmptyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class NasNameInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: str = Field(..., description="NAS name to operate on", min_length=1)


class TestConnInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name (default NAS if omitted)")


def register_system_tools(mcp, conn_mgr) -> None:
    """Register cross-cutting system management tools."""

    @mcp.tool(
        name="synology_list_connections",
        annotations={"title": "List NAS Connections", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_connections(params: EmptyInput) -> str:
        """List all configured NAS units and their connection status."""
        try:
            connections = conn_mgr.list_connections()
            config = conn_mgr.config

            nas_list = []
            for nas_cfg in config.nas_configs.values():
                name = nas_cfg.name
                active_services = [
                    c["service"] for c in connections if c["nas"] == name
                ]
                nas_list.append({
                    "name": name,
                    "host": nas_cfg.host,
                    "port": nas_cfg.port,
                    "secure": nas_cfg.secure,
                    "dsm_version": nas_cfg.dsm_version,
                    "is_default": name == config.default_nas,
                    "active_services": active_services,
                    "active_count": len(active_services),
                })

            return json.dumps({
                "nas_units": nas_list,
                "total": len(nas_list),
                "default_nas": config.default_nas,
            }, indent=2, default=str)
        except Exception as e:
            return error_response(f"Could not list connections: {e}")

    @mcp.tool(
        name="synology_test_connection",
        annotations={"title": "Test NAS Connection", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_test_connection(nas: str | None = None) -> str:
        """Test connectivity to a NAS by fetching basic DSM info."""
        try:
            client = conn_mgr.get_client("sysinfo", nas)
            info = client.get_system_info()
            if not info or "data" not in info:
                return json.dumps({
                    "status": "error",
                    "nas": nas or "(default)",
                    "message": "Connected but could not retrieve DSM info",
                }, indent=2)

            data = info["data"]
            return json.dumps({
                "status": "ok",
                "nas": nas or "(default)",
                "model": data.get("model", ""),
                "serial": data.get("serial", ""),
                "version": data.get("version_string", data.get("version", "")),
                "uptime_seconds": data.get("uptime", ""),
            }, indent=2, default=str)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "nas": nas or "(default)",
                "message": str(e),
            }, indent=2)

    @mcp.tool(
        name="synology_disconnect_nas",
        annotations={"title": "Disconnect NAS", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_disconnect_nas(nas: str | None = None) -> str:
        """Disconnect all active sessions for a specific NAS (frees resources)."""
        try:
            conn_mgr.disconnect_nas(nas)
            return json.dumps({
                "status": "success",
                "action": "disconnected",
                "nas": nas,
            }, indent=2)
        except Exception as e:
            return error_response(f"Could not disconnect '{nas}': {e}")

    @mcp.tool(
        name="synology_server_capabilities",
        annotations={"title": "Server Capabilities", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_server_capabilities(params: EmptyInput) -> str:
        """Show all available tool categories and the configured NAS units."""
        config = conn_mgr.config
        capabilities = {
            "server": "Synology MCP Server",
            "version": "0.1.0",
            "tool_categories": {
                "file_management": [
                    "synology_list_files", "synology_get_file_info", "synology_search_files",
                    "synology_create_folder", "synology_rename", "synology_copy_move",
                    "synology_delete", "synology_compress", "synology_extract",
                    "synology_create_share_link", "synology_upload_file", "synology_file_tree",
                ],
                "system_info": [
                    "synology_dsm_info", "synology_utilization", "synology_storage_info",
                    "synology_network_info", "synology_list_services", "synology_health_dashboard",
                ],
                "downloads": [
                    "synology_list_downloads", "synology_create_download",
                    "synology_pause_download", "synology_resume_download",
                    "synology_delete_download", "synology_download_info",
                    "synology_download_config", "synology_download_stats",
                ],
                "cloud_sync": [
                    "synology_cloudsync_list", "synology_cloudsync_status",
                    "synology_cloudsync_pause", "synology_cloudsync_resume",
                    "synology_cloudsync_logs",
                ],
                "backup": [
                    "synology_backup_list", "synology_backup_status",
                    "synology_backup_run", "synology_backup_cancel",
                    "synology_backup_integrity_check",
                ],
                "docker": [
                    "synology_docker_list_containers", "synology_docker_start",
                    "synology_docker_stop", "synology_docker_restart",
                    "synology_docker_logs", "synology_docker_list_images",
                    "synology_docker_list_networks", "synology_docker_resource_usage",
                ],
                "task_scheduler": [
                    "synology_scheduled_tasks_list", "synology_scheduled_task_info",
                    "synology_scheduled_task_run", "synology_scheduled_task_enable",
                    "synology_scheduled_task_output",
                ],
                "photos": [
                    "synology_photos_list_albums", "synology_photos_browse",
                    "synology_photos_search", "synology_photos_album_items",
                ],
                "packages": [
                    "synology_package_list", "synology_package_start",
                    "synology_package_stop", "synology_package_info",
                ],
                "users_groups": [
                    "synology_list_users", "synology_user_info",
                    "synology_list_groups", "synology_group_members",
                ],
                "shared_folders": [
                    "synology_shared_folders", "synology_shared_folder_info",
                    "synology_shared_folder_permissions",
                ],
                "virtualization": [
                    "synology_vm_list", "synology_vm_info",
                    "synology_vm_poweron", "synology_vm_poweroff", "synology_vm_shutdown",
                ],
                "snapshots": [
                    "synology_snapshot_list", "synology_snapshot_create",
                    "synology_snapshot_delete", "synology_snapshot_replication_list",
                ],
                "active_backup": [
                    "synology_abb_list_tasks", "synology_abb_task_info",
                    "synology_abb_list_devices", "synology_abb_device_info",
                    "synology_abb_logs", "synology_abb_restore_points",
                ],
                "system": [
                    "synology_list_connections", "synology_test_connection",
                    "synology_disconnect_nas", "synology_server_capabilities",
                ],
            },
            "configured_nas": [
                {"name": c.name, "host": c.host, "is_default": c.name == config.default_nas}
                for c in config.nas_configs.values()
            ],
        }
        # Count total tools
        total = sum(len(v) for v in capabilities["tool_categories"].values())
        capabilities["total_tools"] = total
        return json.dumps(capabilities, indent=2)
