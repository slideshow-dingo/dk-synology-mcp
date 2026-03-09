"""Synology MCP Server — main entry point.

Registers all tool modules and manages the lifecycle of
the multi-NAS ConnectionManager.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import anyio
import mcp.types as types
from mcp.shared.message import SessionMessage
from mcp.server.fastmcp import FastMCP

from .utils.config import load_config
from .utils.connection import ConnectionManager

# ── Tool registration imports ────────────────────────────────────────
from .tools.filestation import register_filestation_tools
from .tools.sysinfo import register_sysinfo_tools
from .tools.downloadstation import register_downloadstation_tools
from .tools.cloudsync import register_cloudsync_tools
from .tools.backup import register_backup_tools
from .tools.docker_tools import register_docker_tools
from .tools.task_scheduler import register_task_scheduler_tools
from .tools.photos import register_photos_tools
from .tools.package import register_package_tools
from .tools.users_groups import register_users_groups_tools
from .tools.shares import register_shares_tools
from .tools.virtualization import register_virtualization_tools
from .tools.snapshot import register_snapshot_tools
from .tools.active_backup import register_active_backup_tools
from .tools.system_tools import register_system_tools

logger = logging.getLogger("synology-mcp")

# Module-level reference set by the lifespan context manager.
# The _ConnMgrProxy reads from this so tool closures can resolve
# the ConnectionManager regardless of how FastMCP stores context.
_active_conn_mgr: ConnectionManager | None = None


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Manage ConnectionManager lifecycle — create on startup, disconnect on shutdown."""
    global _active_conn_mgr

    config = load_config()

    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, stream=sys.stderr, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    logger.info("Synology MCP Server starting up")
    logger.info("Configured NAS units: %s", config.nas_names or "(none)")
    if config.default_nas:
        logger.info("Default NAS: %s", config.default_nas)

    conn_mgr = ConnectionManager(config)
    _active_conn_mgr = conn_mgr

    try:
        yield {"conn_mgr": conn_mgr}
    finally:
        logger.info("Shutting down — disconnecting all NAS sessions")
        _active_conn_mgr = None
        conn_mgr.disconnect_all()


# ── Create the MCP server instance ───────────────────────────────────

mcp = FastMCP(
    "Synology MCP Server",
    instructions=(
        "Comprehensive Synology NAS management — file operations, downloads, "
        "backups, Docker, photos, system monitoring, user/group management, "
        "snapshots, virtualization, and more. Supports multiple NAS units."
    ),
    lifespan=server_lifespan,
)


def _register_all_tools(server: FastMCP) -> None:
    """Register every tool module with the server.

    Each register function creates closures that capture the
    ConnectionManager from the lifespan context at call time.
    """
    # We need a small adapter: the lifespan yields conn_mgr into the
    # server context dict, but tools grab it at invocation time via a
    # helper closure that reads from server.
    # Instead, we pass a lazy accessor that resolves conn_mgr on first use.

    class _ConnMgrProxy:
        """Proxy that defers to the module-level ConnectionManager set by the lifespan."""

        def _resolve(self) -> ConnectionManager:
            mgr = _active_conn_mgr
            if mgr is None:
                raise RuntimeError("ConnectionManager not available — server not fully started")
            return mgr

        def get_client(self, service, nas_name=None):
            return self._resolve().get_client(service, nas_name)

        @property
        def config(self):
            return self._resolve().config

        def list_connections(self):
            return self._resolve().list_connections()

        def disconnect_nas(self, nas_name):
            return self._resolve().disconnect_nas(nas_name)

    proxy = _ConnMgrProxy()

    # Phase 1 — Core file & system tools
    register_filestation_tools(server, proxy)
    register_sysinfo_tools(server, proxy)
    register_downloadstation_tools(server, proxy)

    # Phase 2 — Cloud, backup, containers, scheduling, media
    register_cloudsync_tools(server, proxy)
    register_backup_tools(server, proxy)
    register_docker_tools(server, proxy)
    register_task_scheduler_tools(server, proxy)
    register_photos_tools(server, proxy)

    # Phase 3 — Administration & advanced features
    register_package_tools(server, proxy)
    register_users_groups_tools(server, proxy)
    register_shares_tools(server, proxy)
    register_virtualization_tools(server, proxy)
    register_snapshot_tools(server, proxy)
    register_active_backup_tools(server, proxy)

    # Cross-cutting — NAS connectivity & misc
    register_system_tools(server, proxy)


# Register all tools at import time (closures resolve conn_mgr lazily)
_register_all_tools(mcp)


def main():
    """CLI entry point."""
    if sys.version_info >= (3, 14):
        anyio.run(run_stdio_async_compat)
    else:
        mcp.run()


async def run_stdio_async_compat() -> None:
    """Run stdio transport without anyio.wrap_file/thread helpers.

    Python 3.14 currently hangs with anyio's thread-offloaded file I/O in this
    environment, so we use asyncio pipe readers directly for stdio transport.
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    async def stdin_reader() -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        try:
            async with read_stream_writer:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        message = types.JSONRPCMessage.model_validate_json(line.decode("utf-8"))
                    except Exception as exc:  # pragma: no cover
                        await read_stream_writer.send(exc)
                        continue

                    await read_stream_writer.send(SessionMessage(message))
        finally:
            transport.close()

    async def stdout_writer() -> None:
        async with write_stream_reader:
            async for session_message in write_stream_reader:
                json = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                sys.stdout.write(json + "\n")
                sys.stdout.flush()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),
        )


if __name__ == "__main__":
    main()
