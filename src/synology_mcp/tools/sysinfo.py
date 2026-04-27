"""SysInfo tools — system health, storage, network, and resource monitoring.

Covers: CPU, RAM, disk utilization, volume info, network status, DSM info,
thermal readings, UPS status, and overall system health dashboards.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from ..utils.formatters import format_size, format_timestamp, handle_synology_error, error_response


# ── Input Models ──────────────────────────────────────────────────────


class NasInput(BaseModel):
    """Base input that only needs the NAS selector."""
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name. Uses default if omitted.")


class UtilizationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class StorageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class NetworkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


class ServiceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    nas: Optional[str] = Field(default=None, description="NAS name")


# ── Tool Registration ─────────────────────────────────────────────────


def register_sysinfo_tools(mcp, conn_mgr) -> None:
    """Register all SysInfo tools with the MCP server."""

    def _sys(nas: Optional[str] = None):
        return conn_mgr.get_client("sysinfo", nas)

    # ── DSM info ──────────────────────────────────────────────────

    @mcp.tool(
        name="synology_dsm_info",
        annotations={"title": "DSM Information", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_dsm_info(nas: str | None = None) -> str:
        """Get Synology DSM version, model, serial number, uptime, and system status."""
        try:
            sys_client = _sys(nas)
            result = sys_client.dsm_info()
            if not result or "data" not in result:
                return error_response("Could not retrieve DSM info")
            data = result["data"]
            info = {
                "model": data.get("model", ""),
                "serial": data.get("serial", ""),
                "dsm_version": data.get("version_string", data.get("version", "")),
                "hostname": data.get("hostname", ""),
                "uptime_seconds": data.get("uptime", 0),
                "ram_mb": data.get("ram", 0),
                "temperature": data.get("temperature", "N/A"),
                "temperature_warn": data.get("temperature_warn", False),
                "sys_tempwarn": data.get("sys_tempwarn", False),
            }
            # Human-readable uptime
            uptime = info["uptime_seconds"]
            days, rem = divmod(uptime, 86400)
            hours, rem = divmod(rem, 3600)
            mins, _ = divmod(rem, 60)
            info["uptime_human"] = f"{days}d {hours}h {mins}m"
            return json.dumps(info, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "DSM info")

    # ── CPU / Memory utilization ──────────────────────────────────

    @mcp.tool(
        name="synology_utilization",
        annotations={"title": "System Utilization", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_utilization(nas: str | None = None) -> str:
        """Get current CPU, memory, and swap utilization of the NAS."""
        try:
            sys_client = _sys(nas)
            data = sys_client.get_all_system_utilization()
            if not data or "cpu" not in data:
                return error_response("Could not retrieve utilization data")
            cpu = data.get("cpu", {})
            memory = data.get("memory", {})

            cpu_info = {
                "user_load": cpu.get("user_load", 0),
                "system_load": cpu.get("system_load", 0),
                "other_load": cpu.get("other_load", 0),
                "total_load": cpu.get("user_load", 0) + cpu.get("system_load", 0),
            }

            total_real = int(memory.get("total_real", 0))
            avail = int(memory.get("avail_real", 0))
            used = total_real - avail
            memory_info = {
                "total": format_size(total_real * 1024),
                "used": format_size(used * 1024),
                "available": format_size(avail * 1024),
                "percent_used": round((used / total_real * 100), 1) if total_real > 0 else 0,
            }

            total_swap = int(memory.get("total_swap", 0))
            used_swap = total_swap - int(memory.get("avail_swap", 0))
            swap_info = {
                "total": format_size(total_swap * 1024),
                "used": format_size(used_swap * 1024),
                "percent_used": round((used_swap / total_swap * 100), 1) if total_swap > 0 else 0,
            }

            return json.dumps({"cpu": cpu_info, "memory": memory_info, "swap": swap_info}, indent=2)
        except Exception as e:
            return handle_synology_error(e, "System utilization")

    # ── Storage / Volume info ─────────────────────────────────────

    @mcp.tool(
        name="synology_storage_info",
        annotations={"title": "Storage Information", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_storage_info(nas: str | None = None) -> str:
        """Get storage pool, volume, and disk information — sizes, health, RAID status."""
        try:
            sys_client = _sys(nas)
            result = sys_client.storage()
            if not result or "data" not in result:
                return error_response("Could not retrieve storage info")
            data = result["data"]

            volumes = []
            for vol in data.get("volumes", data.get("vol_info", [])):
                vol_info = {
                    "id": vol.get("id", vol.get("volume_id", "")),
                    "status": vol.get("status", ""),
                    "fs_type": vol.get("fs_type", ""),
                }
                total = int(vol.get("total_size", vol.get("size", {}).get("total", 0)))
                used = int(vol.get("used_size", vol.get("size", {}).get("used", 0)))
                if total > 0:
                    vol_info["total"] = format_size(total)
                    vol_info["used"] = format_size(used)
                    vol_info["free"] = format_size(total - used)
                    vol_info["percent_used"] = round(used / total * 100, 1)
                volumes.append(vol_info)

            disks = []
            for disk in data.get("disks", data.get("disk_info", [])):
                disks.append({
                    "id": disk.get("id", disk.get("name", "")),
                    "model": disk.get("model", ""),
                    "vendor": disk.get("vendor", ""),
                    "size": format_size(int(disk.get("size_total", 0))),
                    "temp": disk.get("temp", "N/A"),
                    "status": disk.get("status", disk.get("smart_status", "")),
                })

            return json.dumps({"volumes": volumes, "disks": disks}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Storage info")

    # ── Network info ──────────────────────────────────────────────

    @mcp.tool(
        name="synology_network_info",
        annotations={"title": "Network Information", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_network_info(nas: str | None = None) -> str:
        """Get network interface details — IPs, link speed, MAC addresses, DNS, and gateway."""
        try:
            sys_client = _sys(nas)
            result = sys_client.get_network_info()
            if not result or "data" not in result:
                return error_response("Could not retrieve network info")
            data = result["data"]

            interfaces = []
            for iface in data.get("nifs", data.get("network", [])):
                interfaces.append({
                    "id": iface.get("id", ""),
                    "ip": iface.get("ip", ""),
                    "mask": iface.get("mask", ""),
                    "mac": iface.get("mac", ""),
                    "type": iface.get("type", ""),
                })

            info = {
                "hostname": data.get("hostname", ""),
                "dns": data.get("dns", []),
                "gateway": data.get("gateway", ""),
                "interfaces": interfaces,
            }
            return json.dumps(info, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Network info")

    # ── Running services ──────────────────────────────────────────

    @mcp.tool(
        name="synology_list_services",
        annotations={"title": "List Running Services", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_list_services(nas: str | None = None) -> str:
        """List all services and their current running/stopped status on the NAS."""
        try:
            sys_client = _sys(nas)
            result = sys_client.services_status()
            if not result or "data" not in result:
                return error_response("Could not retrieve services list")
            services = result["data"].get("services", result["data"])
            if isinstance(services, dict):
                items = [{"name": k, "enabled": v} for k, v in services.items()]
            else:
                items = services
            return json.dumps({"services": items, "count": len(items)}, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "List services")

    # ── System health dashboard ───────────────────────────────────

    @mcp.tool(
        name="synology_health_dashboard",
        annotations={"title": "Health Dashboard", "readOnlyHint": True, "destructiveHint": False},
    )
    async def synology_health_dashboard(nas: str | None = None) -> str:
        """Get a combined health dashboard: DSM info, CPU/RAM, storage, and temperature in one call."""
        try:
            sys_client = _sys(nas)
            dashboard = {}

            # DSM info
            try:
                dsm = sys_client.dsm_info()
                if dsm and "data" in dsm:
                    d = dsm["data"]
                    uptime = int(d.get("uptime", 0))
                    days, rem = divmod(uptime, 86400)
                    hours, rem = divmod(rem, 3600)
                    mins, _ = divmod(rem, 60)
                    dashboard["system"] = {
                        "model": d.get("model", ""),
                        "dsm_version": d.get("version_string", ""),
                        "hostname": d.get("hostname", ""),
                        "uptime": f"{days}d {hours}h {mins}m",
                        "temperature_c": d.get("temperature", "N/A"),
                    }
            except Exception:
                dashboard["system"] = {"error": "Could not fetch DSM info"}

            # Utilization
            try:
                util = sys_client.get_all_system_utilization()
                if util and "cpu" in util:
                    cpu = util.get("cpu", {})
                    mem = util.get("memory", {})
                    total_mem = int(mem.get("total_real", 0))
                    avail_mem = int(mem.get("avail_real", 0))
                    dashboard["cpu_load_percent"] = cpu.get("user_load", 0) + cpu.get("system_load", 0)
                    dashboard["memory_percent"] = (
                        round((total_mem - avail_mem) / total_mem * 100, 1) if total_mem > 0 else 0
                    )
            except Exception:
                dashboard["cpu_load_percent"] = "N/A"
                dashboard["memory_percent"] = "N/A"

            # Storage summary
            try:
                storage = sys_client.storage()
                if storage and "data" in storage:
                    vols = storage["data"].get("volumes", storage["data"].get("vol_info", []))
                    vol_summary = []
                    for v in vols:
                        total = int(v.get("total_size", v.get("size", {}).get("total", 0)))
                        used = int(v.get("used_size", v.get("size", {}).get("used", 0)))
                        vol_summary.append({
                            "id": v.get("id", v.get("volume_id", "")),
                            "status": v.get("status", ""),
                            "used_percent": round(used / total * 100, 1) if total > 0 else 0,
                            "free": format_size(total - used) if total > 0 else "N/A",
                        })
                    dashboard["volumes"] = vol_summary
            except Exception:
                dashboard["volumes"] = {"error": "Could not fetch storage info"}

            return json.dumps(dashboard, indent=2, default=str)
        except Exception as e:
            return handle_synology_error(e, "Health dashboard")
