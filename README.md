# Synology MCP Server

Comprehensive Synology NAS management through the [Model Context Protocol](https://modelcontextprotocol.io/). Control file operations, downloads, backups, Docker containers, photos, virtual machines, snapshots, and more — all from Claude or any MCP-compatible client.

## Features

- **80+ tools** across 15 service categories
- **Multi-NAS support** — manage up to 9 NAS units from a single server
- **DSM 7 and DSM 6** compatibility
- **Secure connections** — HTTPS with optional certificate verification
- **Two-factor auth** — OTP code support per NAS

### Tool Categories

| Category | Tools | Description |
|----------|-------|-------------|
| File Management | 16 | List, search, create folders, copy/move, delete, compress, share links, file tree |
| System Info | 6 | DSM info, CPU/RAM utilization, storage, network, services, health dashboard |
| Download Station | 8 | Create downloads (URL/magnet), pause/resume, delete, stats, config |
| Cloud Sync | 5 | List sync tasks, status, pause/resume, logs |
| Backup (HyperBackup) | 5 | List tasks, status, run, cancel, integrity check |
| Docker | 8 | List containers/images/networks, start/stop/restart, logs, resource usage |
| Task Scheduler | 5 | List scheduled tasks, info, run, enable/disable, output |
| Photos | 4 | List albums, browse, search, album items |
| Packages | 4 | List installed packages, start/stop, package info |
| Users & Groups | 4 | List users/groups, user info, group members |
| Shared Folders | 3 | List shares, folder info, permissions |
| Virtualization (VMM) | 5 | List VMs, info, power on/off, graceful shutdown |
| Snapshots | 4 | List snapshots, create, delete, replication tasks |
| Active Backup | 6 | List tasks/devices, info, logs, restore points |
| System | 4 | List connections, test connectivity, disconnect, capabilities |

## Installation

### Prerequisites

- Python 3.10+
- One or more Synology NAS units with DSM 6.x or 7.x
- An admin (or delegated) account on each NAS

### Install from source

```bash
git clone https://github.com/your-username/synology-mcp.git
cd synology-mcp
pip install .
```

### Install in development mode

```bash
pip install -e ".[dev]"
```

## Configuration

All configuration is done through environment variables. Copy the example and fill in your NAS details:

```bash
cp .env.example .env
```

### Single NAS

```env
SYNOLOGY_NAS1_NAME=ds923
SYNOLOGY_NAS1_HOST=192.168.1.100
SYNOLOGY_NAS1_PORT=5001
SYNOLOGY_NAS1_USERNAME=admin
SYNOLOGY_NAS1_PASSWORD=your-password
SYNOLOGY_NAS1_SECURE=true
SYNOLOGY_NAS1_CERT_VERIFY=false
SYNOLOGY_NAS1_DSM_VERSION=7

SYNOLOGY_DEFAULT_NAS=ds923
LOG_LEVEL=INFO
```

### Multi-NAS

Add additional NAS units with incrementing numbers (up to 9):

```env
SYNOLOGY_NAS1_NAME=ds923
SYNOLOGY_NAS1_HOST=192.168.1.100
SYNOLOGY_NAS1_PORT=5001
SYNOLOGY_NAS1_USERNAME=admin
SYNOLOGY_NAS1_PASSWORD=password1
SYNOLOGY_NAS1_SECURE=true
SYNOLOGY_NAS1_DSM_VERSION=7

SYNOLOGY_NAS2_NAME=ds517
SYNOLOGY_NAS2_HOST=192.168.1.101
SYNOLOGY_NAS2_PORT=5001
SYNOLOGY_NAS2_USERNAME=admin
SYNOLOGY_NAS2_PASSWORD=password2
SYNOLOGY_NAS2_SECURE=true
SYNOLOGY_NAS2_DSM_VERSION=7

SYNOLOGY_DEFAULT_NAS=ds923
```

### Two-Factor Authentication

If a NAS has 2FA enabled, provide the current OTP code:

```env
SYNOLOGY_NAS1_OTP_CODE=123456
```

Note: OTP codes expire quickly. For persistent use, consider creating a dedicated service account without 2FA.

## Usage

### With Claude Desktop

Add to your Claude Desktop MCP configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "synology": {
      "command": "synology-mcp",
      "env": {
        "SYNOLOGY_NAS1_NAME": "ds923",
        "SYNOLOGY_NAS1_HOST": "192.168.1.100",
        "SYNOLOGY_NAS1_PORT": "5001",
        "SYNOLOGY_NAS1_USERNAME": "admin",
        "SYNOLOGY_NAS1_PASSWORD": "your-password",
        "SYNOLOGY_NAS1_SECURE": "true",
        "SYNOLOGY_NAS1_CERT_VERIFY": "false",
        "SYNOLOGY_NAS1_DSM_VERSION": "7",
        "SYNOLOGY_DEFAULT_NAS": "ds923"
      }
    }
  }
}
```

### With Docker

```bash
# Build and run with stdio (default)
docker compose up -d

# Or build manually
docker build -t synology-mcp .
docker run --env-file .env -i synology-mcp
```

To use SSE transport (network-accessible), uncomment the relevant lines in `docker-compose.yml` or run:

```bash
docker run --env-file .env -p 8080:8080 synology-mcp --transport sse --port 8080
```

### Direct CLI

```bash
# Run with stdio transport (default)
synology-mcp

# Run with SSE transport
synology-mcp --transport sse --port 8080
```

## Multi-NAS Usage

Every tool accepts an optional `nas` parameter. If omitted, the default NAS is used.

```
"List files on ds923"        → nas parameter not needed (it's the default)
"List files on ds517"        → nas="ds517"
"Show VMs on ds923"          → nas parameter not needed
"Docker containers on ds517" → nas="ds517"
```

Use `synology_list_connections` to see all configured NAS units and their active sessions, or `synology_test_connection` to verify connectivity.

## Project Structure

```
synology-mcp/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
└── src/
    └── synology_mcp/
        ├── __init__.py
        ├── server.py              # FastMCP server entry point
        ├── utils/
        │   ├── config.py          # Environment config loader
        │   ├── connection.py       # Multi-NAS ConnectionManager
        │   └── formatters.py       # Response formatting helpers
        └── tools/
            ├── filestation.py      # File management (16 tools)
            ├── sysinfo.py          # System monitoring (6 tools)
            ├── downloadstation.py  # Downloads (8 tools)
            ├── cloudsync.py        # Cloud Sync (5 tools)
            ├── backup.py           # HyperBackup (5 tools)
            ├── docker_tools.py     # Docker/Container (8 tools)
            ├── task_scheduler.py   # Scheduled tasks (5 tools)
            ├── photos.py           # Synology Photos (4 tools)
            ├── package.py          # Package management (4 tools)
            ├── users_groups.py     # Users & groups (4 tools)
            ├── shares.py           # Shared folders (3 tools)
            ├── virtualization.py   # VMM (5 tools)
            ├── snapshot.py         # Snapshots (4 tools)
            ├── active_backup.py    # Active Backup (6 tools)
            └── system_tools.py     # NAS connections (4 tools)
```

## Dependencies

- [mcp](https://pypi.org/project/mcp/) — Model Context Protocol SDK with FastMCP
- [synology-api](https://pypi.org/project/synology-api/) — Python wrapper for Synology DSM APIs
- [pydantic](https://docs.pydantic.dev/) — Input validation
- [python-dotenv](https://pypi.org/project/python-dotenv/) — Environment variable loading

## License

MIT
