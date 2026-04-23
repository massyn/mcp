# Citadel MCP

A personal knowledge management MCP server. Citadel gives an LLM a persistent, structured place to store and retrieve knowledge across conversations — curated by the LLM, for the LLM. The user never interacts with the data directly.

---

## Requirements

- Python 3.12+
- Claude Desktop (or any MCP-compatible client)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Running the server

### stdio (Claude Desktop — local)

```bash
python citadel_mcp.py
```

This is the default mode. Claude Desktop spawns the process directly and communicates over stdin/stdout.

### HTTP (network)

```bash
python citadel_mcp.py --http
python citadel_mcp.py --http --host 0.0.0.0 --port 8000
```

| Flag     | Default       | Description      |
|----------|---------------|------------------|
| `--http` | off           | Enable HTTP mode |
| `--host` | `127.0.0.1`   | Bind address     |
| `--port` | `8000`        | Port             |

> **Note:** HTTP mode has no built-in authentication. If you expose it beyond localhost, put a reverse proxy with auth in front of it.

---

## Claude Desktop integration

### Local (stdio)

Run `install.py` to register the server automatically:

```bash
python install.py
```

This adds (or updates) the Citadel entry in your Claude Desktop config, including the `alwaysAllow` list so Claude Desktop does not prompt for approval on every tool call. Restart Claude Desktop after running.

The resulting config entry looks like:

```json
{
  "mcpServers": {
    "citadel": {
      "command": "python",
      "args": ["/path/to/citadel/citadel_mcp.py"],
      "alwaysAllow": [
        "citadel_get_manifest",
        "citadel_add_room",
        "citadel_get_room",
        "citadel_get_entry",
        "citadel_add_entry",
        "citadel_update_entry",
        "citadel_search"
      ]
    }
  }
}
```

### Network (HTTP)

If Citadel is running in HTTP mode on another machine (or as a background service), add it to your Claude Desktop config manually as a URL-based server:

```json
{
  "mcpServers": {
    "citadel": {
      "type": "streamable-http",
      "url": "http://<host>:8000/mcp"
    }
  }
}
```

Replace `<host>` with the IP or hostname of the machine running Citadel.

Config file locations:
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

---

## Configuration

Copy `.env_example` to `.env` and fill in what you need. All values are optional.

### Database backend

Citadel supports two backends. It picks one at startup based on environment variables:

| Condition | Backend used |
|-----------|-------------|
| `TURSO_URL` + `TURSO_TOKEN` both set | Turso (remote) |
| Otherwise | Local SQLite |

**Local SQLite** — database path resolved in this order:
1. `DB_PATH` environment variable / `.env`
2. Default: `~/.citadel/citadel.db`

Supports `~` expansion. The directory is created automatically.

**Turso** — set both variables in `.env`:

```
TURSO_URL=libsql://your-database.turso.io
TURSO_TOKEN=your-auth-token-here
```

`libsql-client` must be installed (included in `requirements.txt`).

### Migrating from local SQLite to Turso

Once `TURSO_URL` and `TURSO_TOKEN` are configured in `.env`, run:

```bash
python migrate.py
```

The script reads all rooms and entries from the local database, initialises the schema on Turso, and copies the data across. It uses `INSERT OR IGNORE`, so it is safe to run multiple times — existing records in Turso are left untouched.

```bash
python migrate.py --yes   # skip the confirmation prompt
```

---

## How It Works

### Rooms

A room is a named collection of related knowledge — a project, a domain, a topic area.

Examples:
- `citadel-mcp` — this project
- `bike-rides` — motorcycle ride logs
- `cooking` — recipes and food experiments

Rooms are created by the LLM when a conversation introduces something worth capturing. The Citadel starts empty and grows organically. Rooms have tags for cross-cutting navigation.

### Entries

A room contains entries. Each entry is a coherent unit of knowledge — not a catch-all blob.

Entries are living documents. The LLM updates the same entry as a conversation develops. A new entry is only created when the conversation shifts into genuinely distinct territory.

### The Manifest

The manifest is the LLM's entry point. At the start of a conversation the LLM calls `citadel_get_manifest` to see what rooms exist, then selectively retrieves only what's relevant. This two-step pattern keeps token cost low.

---

## MCP Tools

All tools are prefixed `citadel_`.

### Manifest

```
citadel_get_manifest(tags: list[str] | None = None) -> str
```
Returns all rooms, optionally filtered by tags. Each room includes: name, tags, entry_count, updated_on.

### Room Operations

```
citadel_add_room(name: str, tags: list[str]) -> str
```
Creates a new room. Slug format names (e.g. `bike-rides`). No-ops gracefully if the room already exists.

```
citadel_get_room(room: str, status: str = "active") -> str
```
Returns all entries in a room at summary level — id, title, summary, tags, status, updated_on. No detail field.

### Entry Operations

```
citadel_get_entry(room: str, entry_id: str) -> str
```
Returns a full entry including the detail field.

```
citadel_add_entry(room: str, title: str, summary: str, detail: str, tags: list[str] | None = None) -> str
```
Creates a new entry. Auto-creates the room if it doesn't exist.

```
citadel_update_entry(room: str, entry_id: str, summary: str | None, detail: str | None, status: str | None, tags: list[str] | None) -> str
```
Updates any combination of fields. Only provided fields are changed. Entry status values: `active`, `archived`, `deprecated`.

```
citadel_search(query: str, room: str | None = None, tags: list[str] | None = None) -> str
```
Full-text search across title, summary, and detail. Optionally scoped to a room or filtered by tags. Returns summary-level results.

---

## File Structure

```
citadel/
  citadel_mcp.py   — MCP server and tools
  db.py            — database abstraction (local SQLite + Turso backends)
  migrate.py       — copies local SQLite data into Turso
  install.py       — registers the server with Claude Desktop
  requirements.txt — dependencies
  .env_example     — configuration template
  .env             — your local configuration (not committed)
```
