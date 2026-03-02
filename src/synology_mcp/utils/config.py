"""Configuration management for multi-NAS environments."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv


@dataclass
class NasConfig:
    """Connection configuration for a single Synology NAS."""

    name: str
    host: str
    port: int = 5001
    username: str = "admin"
    password: str = ""
    secure: bool = True
    cert_verify: bool = False
    dsm_version: int = 7
    otp_code: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError(f"NAS '{self.name}' has no host configured")
        if not self.password:
            raise ValueError(f"NAS '{self.name}' has no password configured")


@dataclass
class ServerConfig:
    """Top-level server configuration with all NAS connections."""

    nas_configs: dict[str, NasConfig] = field(default_factory=dict)
    default_nas: Optional[str] = None
    log_level: str = "INFO"

    def get_nas(self, name: Optional[str] = None) -> NasConfig:
        """Get NAS config by name, falling back to default."""
        target = name or self.default_nas
        if not target:
            if len(self.nas_configs) == 1:
                return next(iter(self.nas_configs.values()))
            raise ValueError(
                f"No NAS specified and no default set. Available: {list(self.nas_configs.keys())}"
            )
        target_lower = target.lower()
        for key, cfg in self.nas_configs.items():
            if key.lower() == target_lower or cfg.name.lower() == target_lower:
                return cfg
        raise ValueError(
            f"NAS '{target}' not found. Available: {list(self.nas_configs.keys())}"
        )

    @property
    def nas_names(self) -> list[str]:
        """List all configured NAS names."""
        return [cfg.name for cfg in self.nas_configs.values()]


def load_config() -> ServerConfig:
    """Load configuration from environment variables.

    Supports SYNOLOGY_NAS1_*, SYNOLOGY_NAS2_*, ... SYNOLOGY_NAS9_* patterns.
    """
    load_dotenv()

    config = ServerConfig(
        log_level=os.getenv("SYNOLOGY_LOG_LEVEL", "INFO"),
        default_nas=os.getenv("SYNOLOGY_DEFAULT_NAS"),
    )

    for i in range(1, 10):
        prefix = f"SYNOLOGY_NAS{i}_"
        host = os.getenv(f"{prefix}HOST")
        if not host:
            continue

        name = os.getenv(f"{prefix}NAME", f"NAS{i}")
        password = os.getenv(f"{prefix}PASSWORD", "")
        if not password:
            print(f"Warning: {prefix}PASSWORD not set, skipping NAS '{name}'", file=sys.stderr)
            continue

        nas = NasConfig(
            name=name,
            host=host,
            port=int(os.getenv(f"{prefix}PORT", "5001")),
            username=os.getenv(f"{prefix}USERNAME", "admin"),
            password=password,
            secure=os.getenv(f"{prefix}SECURE", "true").lower() == "true",
            cert_verify=os.getenv(f"{prefix}CERT_VERIFY", "false").lower() == "true",
            dsm_version=int(os.getenv(f"{prefix}DSM_VERSION", "7")),
            otp_code=os.getenv(f"{prefix}OTP_CODE") or None,
        )
        config.nas_configs[name] = nas

    if not config.nas_configs:
        print(
            "Warning: No NAS connections configured. Set SYNOLOGY_NAS1_HOST, etc.",
            file=sys.stderr,
        )

    return config
