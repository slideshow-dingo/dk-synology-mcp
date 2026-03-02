"""Connection manager for multi-NAS Synology API access.

Handles lazy connection initialization, session management, and service
client caching so each NAS+service pair is only instantiated once.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Optional, Type

from synology_api import filestation, downloadstation, cloud_sync, docker_api
from synology_api.core_sys_info import SysInfo
from synology_api.core_backup import Backup
from synology_api.core_active_backup import ActiveBackupBusiness
from synology_api.core_package import Package
from synology_api.core_user import User
from synology_api.core_group import Group
from synology_api.core_share import Share, SharePermission
from synology_api.core_certificate import Certificate
from synology_api.task_scheduler import TaskScheduler
from synology_api.event_scheduler import EventScheduler
from synology_api.photos import Photos
from synology_api.snapshot import Snapshot
from synology_api.virtualization import Virtualization
from synology_api.vpn import VPN
from synology_api.log_center import LogCenter
from synology_api.security_advisor import SecurityAdvisor
from synology_api.universal_search import UniversalSearch
from synology_api.usb_copy import USBCopy
from synology_api.audiostation import AudioStation
from synology_api.notestation import NoteStation
from synology_api.drive_admin_console import AdminConsole
from synology_api.dhcp_server import DhcpServer
from synology_api.directory_server import DirectoryServer

from .config import NasConfig, ServerConfig


# Map of service name -> (module class, extra kwargs)
SERVICE_REGISTRY: dict[str, Type] = {
    "filestation": filestation.FileStation,
    "downloadstation": downloadstation.DownloadStation,
    "sysinfo": SysInfo,
    "cloudsync": cloud_sync.CloudSync,
    "backup": Backup,
    "activebackup": ActiveBackupBusiness,
    "package": Package,
    "user": User,
    "group": Group,
    "share": Share,
    "share_permission": SharePermission,
    "certificate": Certificate,
    "task_scheduler": TaskScheduler,
    "event_scheduler": EventScheduler,
    "photos": Photos,
    "snapshot": Snapshot,
    "virtualization": Virtualization,
    "vpn": VPN,
    "log_center": LogCenter,
    "security_advisor": SecurityAdvisor,
    "universal_search": UniversalSearch,
    "usb_copy": USBCopy,
    "audiostation": AudioStation,
    "notestation": NoteStation,
    "drive_admin": AdminConsole,
    "docker": docker_api.Docker,
    "dhcp_server": DhcpServer,
    "directory_server": DirectoryServer,
}


class ConnectionManager:
    """Manages connections to multiple Synology NAS units.

    Thread-safe, lazily creates service clients on first access.
    """

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._clients: dict[str, Any] = {}  # key: "{nas_name}:{service}"
        self._lock = threading.Lock()

    @property
    def config(self) -> ServerConfig:
        return self._config

    def get_client(self, service: str, nas_name: Optional[str] = None) -> Any:
        """Get or create a service client for the specified NAS.

        Args:
            service: Service name (e.g., 'filestation', 'sysinfo')
            nas_name: NAS name. Uses default if not provided.

        Returns:
            Initialized synology-api client instance.

        Raises:
            ValueError: If service or NAS name is invalid.
        """
        if service not in SERVICE_REGISTRY:
            raise ValueError(
                f"Unknown service '{service}'. Available: {sorted(SERVICE_REGISTRY.keys())}"
            )

        nas_cfg = self._config.get_nas(nas_name)
        cache_key = f"{nas_cfg.name}:{service}"

        with self._lock:
            if cache_key not in self._clients:
                self._clients[cache_key] = self._create_client(service, nas_cfg)
            return self._clients[cache_key]

    def _create_client(self, service: str, nas_cfg: NasConfig) -> Any:
        """Instantiate a synology-api client for the given service and NAS."""
        cls = SERVICE_REGISTRY[service]
        kwargs: dict[str, Any] = {
            "ip_address": nas_cfg.host,
            "port": str(nas_cfg.port),
            "username": nas_cfg.username,
            "password": nas_cfg.password,
            "secure": nas_cfg.secure,
            "cert_verify": nas_cfg.cert_verify,
            "dsm_version": nas_cfg.dsm_version,
        }
        if nas_cfg.otp_code:
            kwargs["otp_code"] = nas_cfg.otp_code

        print(f"Connecting to {nas_cfg.name} ({nas_cfg.host}) — {service}...", file=sys.stderr)
        try:
            client = cls(**kwargs)
            print(f"  Connected: {nas_cfg.name}/{service}", file=sys.stderr)
            return client
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to {nas_cfg.name} ({nas_cfg.host}) for {service}: {e}"
            ) from e

    def disconnect_all(self) -> None:
        """Logout and clean up all cached clients."""
        with self._lock:
            for key, client in self._clients.items():
                try:
                    client.logout()
                except Exception:
                    pass
            self._clients.clear()

    def disconnect_nas(self, nas_name: str) -> None:
        """Disconnect all services for a specific NAS."""
        with self._lock:
            keys_to_remove = [k for k in self._clients if k.startswith(f"{nas_name}:")]
            for key in keys_to_remove:
                try:
                    self._clients[key].logout()
                except Exception:
                    pass
                del self._clients[key]

    def list_connections(self) -> list[dict[str, str]]:
        """List all active connections."""
        with self._lock:
            return [
                {"nas": k.split(":")[0], "service": k.split(":")[1]}
                for k in self._clients
            ]
