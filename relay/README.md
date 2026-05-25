# Relay

Generic LLM-to-database bridge. SQL definition files become MCP tools.

> *"Give me a call, I'll relay it to the database, and back."*

## How it works

Point Relay at a directory containing an `index.yaml` and a `sql/` folder. Each `.sql` file in that folder becomes a live MCP tool. Relay reads the front matter for the tool definition and the body for the SQL steps to execute.

```
my-domain/
  index.yaml          # server name + system prompt for the LLM
  sql/
    001_schema.sql    # run_on_startup: true — DDL, never exposed as a tool
    add_widget.sql    # becomes the add_widget MCP tool
    update_widget.sql
    delete_widget.sql
```

## SQL file format

Every `.sql` file uses `---` as a universal separator. The first block is YAML front matter; each subsequent block is a SQL step executed in order.

```sql
---
name: add_widget
description: Creates a new widget. Returns the new widget id.
transaction: true
parameters:
  name:
    type: string
    required: true
    description: Widget name
  colour:
    type: string
    required: false
    default: "blue"
    description: Widget colour
returns: id of the created widget
---
INSERT OR IGNORE INTO categories (name) VALUES ('default')
---
INSERT INTO widgets (name, colour, created_on)
VALUES ('{{ name }}', '{{ colour }}', '{{ now() }}')
RETURNING id
```

### Front matter fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | filename stem | Snake-case tool name exposed to the LLM |
| `description` | string | — | Plain-English description for the LLM |
| `run_on_startup` | bool | `false` | If true: run at startup, never register as a tool |
| `transaction` | bool | `false` | Wrap all SQL steps in one transaction; rollback on failure |
| `parameters` | map | `{}` | Named parameters injected into SQL via Jinja |
| `returns` | string | — | Plain-English description of the return value |
| `examples` | list | — | Optional — for docs and future test generation |

### Parameter fields

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | string | `string` | `string`, `integer`, or `boolean` |
| `required` | bool | `true` | Whether the LLM must provide this parameter |
| `default` | any | `null` | Value used when `required: false` and not provided |
| `description` | string | — | Shown in the generated tool description |

### Jinja globals available in SQL

| Expression | Value |
|---|---|
| `{{ param_name }}` | Any declared parameter value (strings auto-escaped for SQL) |
| `{{ now() }}` | Current UTC datetime as ISO 8601 string |
| `{{ uuid() }}` | New UUID v4 string |

String values are automatically escaped (single quotes doubled) before being injected. Integer and boolean values are injected as-is.

### Execution rules

- Files are processed in **filename sort order** — use numeric prefixes (`001_`, `002_`) to control startup execution order.
- The **last SQL step's result** is returned to the LLM.
- `SELECT` → returns list of row dicts.
- `INSERT / UPDATE / DELETE` → returns `{"rows_affected": N}`.
- `INSERT ... RETURNING ...` → returns list of row dicts (use this to return the new id).
- `transaction: true` → all steps wrapped in one transaction; any failure rolls everything back.

## Configuration

All configuration is via environment variables. A `.env` file in the working directory (next to `relay.py`) is loaded automatically, so a single file can drive the entire startup.

| Variable | CLI override | Description |
|---|---|---|
| `RELAY_CODE` | `--code` | Path to the code directory (required) |
| `RELAY_TRANSPORT` | `--transport` | `stdio` (default) or `http` |
| `RELAY_HOST` | `--host` | Bind address for HTTP transport (default: `0.0.0.0`) |
| `RELAY_PORT` | `--port` | Port for HTTP transport (default: `8788`) |
| `RELAY_TOKEN` | `--token` | Bearer token for HTTP transport (no auth if unset) |
| `RELAY_BASE_URL` | `--base-url` | Public base URL of this server, e.g. `https://mcp.example.com/citadel`. Required to enable OAuth 2.1. Must be set together with `RELAY_TOKEN`, `RELAY_CLIENT_ID`, and `RELAY_CLIENT_SECRET`. |
| `RELAY_CLIENT_ID` | — | OAuth client ID to register in Claude.ai (or any OAuth client). Generate with `openssl rand -hex 16`. |
| `RELAY_CLIENT_SECRET` | — | OAuth client secret. Generate with `openssl rand -hex 32`. |
| `DB_TYPE` | — | `sqlite` or `turso`; auto-detected from `TURSO_URL` if not set |
| `DB_PATH` | — | SQLite path (default: `~/.relay/relay.db`) |
| `TURSO_URL` | — | Turso database URL (`libsql://...`); presence implies `DB_TYPE=turso` |
| `TURSO_TOKEN` | — | Turso auth token |

**Load order:** `.env` in the working directory is loaded first. If the code directory has its own `.env` (e.g. for DB credentials), it is loaded second and fills in any variables not already set.

CLI arguments override environment variables.

## Usage

### Starting with a .env file (simplest)

Put a `.env` file next to `relay.py` and run:

```bash
python relay.py
```

**stdio example** (default, for local MCP clients):

```ini
# .env
RELAY_CODE=./citadel
DB_PATH=./citadel/citadel.db
```

**HTTP example** (for remote MCP clients, e.g. Claude Mobile):

```ini
# .env
RELAY_CODE=./citadel
DB_PATH=./citadel/citadel.db
RELAY_TRANSPORT=http
RELAY_PORT=8788
RELAY_TOKEN=your-secret-token
RELAY_BASE_URL=https://mcp.example.com/citadel
RELAY_CLIENT_ID=generated-with-openssl-rand-hex-16
RELAY_CLIENT_SECRET=generated-with-openssl-rand-hex-32
```

`RELAY_BASE_URL` is the public URL clients reach the server at. It is used to build OAuth 2.1 metadata and must match the URL clients actually connect to. Leave it unset for local/stdio use.

The `RELAY_CLIENT_ID` and `RELAY_CLIENT_SECRET` are the credentials you paste into Claude.ai (or any OAuth client) when adding the MCP server. Generate them once:

```bash
openssl rand -hex 16   # client ID
openssl rand -hex 32   # client secret
```

The `RELAY_TOKEN` is the bearer token that relay validates on every MCP request. Both the OAuth flow and direct bearer access resolve to this token — the OAuth flow simply hands it to the client after credential verification.

Then start:

```bash
python relay.py
# 2026-05-24 12:00:00 [INFO] Registered tool: add_entry
# 2026-05-24 12:00:00 [INFO] Starting HTTP server on 0.0.0.0:8788
# 2026-05-24 12:00:00 [INFO] Bearer token authentication enabled
```

### As an MCP server via stdio (local clients)

SQLite:

```json
{
  "mcpServers": {
    "citadel": {
      "command": "python",
      "args": ["relay.py"],
      "env": {
        "RELAY_CODE": "/path/to/citadel",
        "DB_PATH": "/path/to/citadel.db"
      }
    }
  }
}
```

Turso:

```json
{
  "mcpServers": {
    "citadel": {
      "command": "python",
      "args": ["relay.py"],
      "env": {
        "RELAY_CODE": "/path/to/citadel",
        "TURSO_URL": "libsql://your-db.turso.io",
        "TURSO_TOKEN": "your-token"
      }
    }
  }
}
```

### As a remote HTTP server

Start relay with HTTP transport (via `.env` or CLI):

```bash
python relay.py --transport http --port 8788 --token your-secret-token
```

Configure an MCP client to connect to it:

```json
{
  "mcpServers": {
    "citadel": {
      "type": "http",
      "url": "http://your-server:8788/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-token"
      }
    }
  }
}
```

If no `RELAY_TOKEN` / `--token` is set, the server starts without authentication (a warning is logged). This is only appropriate for trusted local networks.

### Exposing via nginx (with Cloudflare or public HTTPS)

When relay runs behind nginx, add a location block that proxies a public path to the local `/mcp` endpoint. `proxy_buffering off` is required for the streaming MCP transport.

```nginx
server {
    listen 80;
    server_name your-domain.example.com;

    # MCP traffic (and the OAuth sub-paths /citadel/authorize, /token, /register)
    location /citadel {
        proxy_pass http://localhost:8788/mcp;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }

    # OAuth 2.1 discovery endpoints — required for remote clients such as Claude Mobile.
    # These are served at the domain root per RFC 8414 / RFC 9728.
    location /.well-known/ {
        proxy_pass http://localhost:8788/.well-known/;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

If Cloudflare (or another CDN) handles TLS termination, the nginx block only needs to listen on port 80 — HTTPS is handled upstream.

### Running as a systemd service

Create a service file at `/etc/systemd/system/relay.service`. Adjust `User`, `WorkingDirectory`, and `ExecStart` to match your deployment:

```ini
[Unit]
Description=Relay MCP server
After=network.target

[Service]
Type=simple
User=relay
WorkingDirectory=/opt/relay
EnvironmentFile=/opt/relay/.env
ExecStart=/opt/relay/venv/bin/python relay.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Place your `.env` next to `relay.py` in `WorkingDirectory`. At minimum, set `RELAY_TRANSPORT=http` and `RELAY_PORT` so the process does not exit immediately (stdio mode exits as soon as stdin closes):

```ini
# /opt/relay/.env
RELAY_CODE=/opt/relay/citadel
DB_PATH=/opt/relay/citadel/citadel.db
RELAY_TRANSPORT=http
RELAY_PORT=8788
RELAY_TOKEN=your-secret-token
RELAY_BASE_URL=https://mcp.example.com/citadel
RELAY_CLIENT_ID=generated-with-openssl-rand-hex-16
RELAY_CLIENT_SECRET=generated-with-openssl-rand-hex-32
```

Reload systemd, enable the service to start on boot, then start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable relay
sudo systemctl start relay
```

Check that it is running:

```bash
sudo systemctl status relay
```

Tail the logs:

```bash
sudo journalctl -u relay -f
```

### Connecting Claude Desktop via mcp-proxy

Claude Desktop does not natively support remote MCP servers. Use [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) as a local bridge:

```bash
pip install mcp-proxy
```

Add an entry to `claude_desktop_config.json` using `--transport streamablehttp` (not `sse` — relay serves streamable HTTP, not SSE):

```json
{
  "mcpServers": {
    "citadel": {
      "command": "mcp-proxy",
      "args": [
        "https://your-domain.example.com/citadel",
        "--transport",
        "streamablehttp",
        "-H",
        "Authorization",
        "Bearer your-secret-token"
      ],
      "autoApprove": []
    }
  }
}
```

Config file locations:
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Restart Claude Desktop after editing.

### Debug mode (development)

Run a single tool, print the rendered SQL, and show the result:

```bash
python relay.py --code ./citadel --debug --tool add_entry \
  --params '{"room": "test", "title": "Hello", "summary": "Test entry", "detail": "Testing relay."}'
```

## Reference implementation — Citadel

The `citadel/` directory in this repo is the reference implementation. It exposes `add_entry`, `update_entry`, and `delete_entry` tools backed by the Citadel schema (rooms, entries, todos with FTS5).

## Installation

```bash
pip install -r requirements.txt
```

Turso support requires `libsql-client`, which is listed in `requirements.txt` but only imported at runtime when `TURSO_URL` is set (or `DB_TYPE=turso` is explicit).

HTTP transport requires `uvicorn`, also in `requirements.txt`.
