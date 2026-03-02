"""Virtualization (VMM) tools — manage virtual machines.

Covers: list VMs, VM details, start/stop/pause, and guest info.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import handle_synology_error, error_response


class VirtNasInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class VmInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    guest_id: str = Field(..., description="Virtual machine (guest) ID", min_length=1)
    nas: Optional[str] = Field(default=None, description="NAS name")


def register_virtualization_tools(mcp, conn_mgr) -> None:
    """Register Virtual Machine Manager tools."""

    def _virt(nas=None):
        return conn_mgr.get_client("virtualization", nas)

    @mcp.tool(
        name="synology_vm_list",
        annotations={"title": "List Virtual Machines", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_vm_list(params: VirtNasInput) -> str:
        """List all virtual machines with status, CPU, and memory info."""
        try:
            virt = _virt(params.nas)
            result = virt.get_guest_list()
            if not result or "data" not in result:
                return error_response("Could not list virtual machines")
            guests = result["data"].get("guests", result["data"])
            items = []
            if isinstance(guests, list):
                for g in guests:
                    items.append({
                        "id": g.get("guest_id", g.get("id", "")),
                        "name": g.get("guest_name", g.get("name", "")),
                        "status": g.get("status", ""),
                        "vcpu": g.get("vcpu_num", ""),
                        "ram_mb": g.get("vram_size", ""),
                    })
            return json.dumps({"vms": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List VMs")

    @mcp.tool(
        name="synology_vm_info",
        annotations={"title": "VM Details", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_vm_info(params: VmInput) -> str:
        """Get detailed information about a virtual machine."""
        try:
            virt = _virt(params.nas)
            result = virt.get_guest_info(guest_id=params.guest_id)
            if not result or "data" not in result:
                return error_response(f"VM '{params.guest_id}' not found")
            return json.dumps(result["data"], indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "VM info")

    @mcp.tool(
        name="synology_vm_poweron",
        annotations={"title": "Power On VM", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_vm_poweron(params: VmInput) -> str:
        """Power on a virtual machine."""
        try:
            virt = _virt(params.nas)
            result = virt.poweron_guest(guest_id=params.guest_id)
            return json.dumps({"status": "success", "action": "poweron", "guest_id": params.guest_id}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Power on VM")

    @mcp.tool(
        name="synology_vm_poweroff",
        annotations={"title": "Power Off VM", "readOnlyHint": False, "destructiveHint": True},
    )
    async def synology_vm_poweroff(params: VmInput) -> str:
        """Force power off a virtual machine (like pulling the power cord)."""
        try:
            virt = _virt(params.nas)
            result = virt.poweroff_guest(guest_id=params.guest_id)
            return json.dumps({"status": "success", "action": "poweroff", "guest_id": params.guest_id}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Power off VM")

    @mcp.tool(
        name="synology_vm_shutdown",
        annotations={"title": "Graceful Shutdown VM", "readOnlyHint": False, "destructiveHint": False},
    )
    async def synology_vm_shutdown(params: VmInput) -> str:
        """Gracefully shut down a virtual machine (sends ACPI shutdown signal)."""
        try:
            virt = _virt(params.nas)
            result = virt.shutdown_guest(guest_id=params.guest_id)
            return json.dumps({"status": "success", "action": "shutdown", "guest_id": params.guest_id}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "Shutdown VM")
