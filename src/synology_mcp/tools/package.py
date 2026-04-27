"""Package tools — manage installed and available DSM packages.

Covers: list packages, install, uninstall, start, stop, and update check.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import handle_synology_error, error_response


class PackageNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class PackageNameInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    package_id: str = Field(..., description="Package identifier (e.g., 'Docker', 'SynologyDrive')", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_package_tools(mcp, conn_mgr) -> None:
    """Register Package Center tools."""

    def _pkg(nas=None):
        return conn_mgr.get_client("package", nas)

    @mcp.tool(
        name="synology_package_list",
        annotations={"title": "List Installed Packages", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_package_list(nas: str | None = None) -> str:
        """List all installed packages on the NAS with version and status."""
        try:
            pkg = _pkg(nas)
            result = pkg.list_installed()
            if not result or "data" not in result:
                return error_response("Could not list packages")
            pkgs = result["data"].get("packages", result["data"])
            items = []
            if isinstance(pkgs, list):
                for p in pkgs:
                    items.append({
                        "id": p.get("id", ""),
                        "name": p.get("dname", p.get("name", "")),
                        "version": p.get("version", ""),
                        "status": "running" if p.get("additional", {}).get("status") == "running" else p.get("status", ""),
                    })
            return json.dumps({"packages": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List packages")

    @mcp.tool(
        name="synology_package_start",
        annotations={"title": "Start Package", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_package_start(nas: str | None = None, package_id: str | None = None) -> str:
        """Start (launch) an installed DSM package."""
        try:
            pkg = _pkg(nas)
            # synology-api Package class doesn't expose start/stop;
            # use the underlying request_data method to call the DSM API
            result = pkg.request_data(
                "SYNO.Core.Package.Control",
                "entry.cgi",
                req_param={"method": "start", "version": 1, "id": package_id},
            )
            if isinstance(result, dict) and result.get("success"):
                return json.dumps({"status": "success", "action": "started", "package": package_id}, indent=2)
            return error_response(f"Could not start package '{package_id}': {result}")
        except AttributeError:
            return error_response(
                "Package start/stop not supported by this synology-api version. "
                "Use DSM web UI to start the package."
            )
        except Exception as e:
            return handle_synology_error(e, "Start package")

    @mcp.tool(
        name="synology_package_stop",
        annotations={"title": "Stop Package", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_package_stop(nas: str | None = None, package_id: str | None = None) -> str:
        """Stop a running DSM package."""
        try:
            pkg = _pkg(nas)
            # synology-api Package class doesn't expose start/stop;
            # use the underlying request_data method to call the DSM API
            result = pkg.request_data(
                "SYNO.Core.Package.Control",
                "entry.cgi",
                req_param={"method": "stop", "version": 1, "id": package_id},
            )
            if isinstance(result, dict) and result.get("success"):
                return json.dumps({"status": "success", "action": "stopped", "package": package_id}, indent=2)
            return error_response(f"Could not stop package '{package_id}': {result}")
        except AttributeError:
            return error_response(
                "Package start/stop not supported by this synology-api version. "
                "Use DSM web UI to stop the package."
            )
        except Exception as e:
            return handle_synology_error(e, "Stop package")

    @mcp.tool(
        name="synology_package_info",
        annotations={"title": "Package Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_package_info(nas: str | None = None, package_id: str | None = None) -> str:
        """Get detailed information about a specific installed package."""
        try:
            pkg = _pkg(nas)
            result = pkg.get_package(package_id=package_id)
            if not result or "data" not in result:
                return error_response(f"Package '{package_id}' not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Package info")
