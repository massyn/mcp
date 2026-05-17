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

Run `install.py` from the repository root to register the server automatically:

```bash
python install.py citadel
```

The script detects whether `python3` or `python` is available and uses whichever it finds. It reads `citadel/mcp.json` to determine the entry point and `alwaysAllow` list, then adds or updates the Citadel entry in your Claude Desktop config. Restart Claude Desktop after running.

### Network (HTTP)

If Citadel is running in HTTP mode on another machine (or as a background service), add it to your Claude Desktop config manually:

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

**Turso** — set both variables in `.env`:

```
TURSO_URL=libsql://your-database.turso.io
TURSO_TOKEN=your-auth-token-here
```

### Migrating from local SQLite to Turso

```bash
python migrate.py
python migrate.py --yes   # skip confirmation
```

---

## How It Works

### The Knowledge Model

Citadel separates two distinct concerns: **knowledge** and **work**.

**Entries are knowledge artifacts.** They capture decisions, rationale, context, patterns, and outcomes. They are the library — the Wikipedia of what was built and why. Entries are persistent and reference-oriented. They should never be structured as todo lists.

**Todos are work items.** They are actionable, completable, and time-bound. They serve as a system of record for what was done and when. When a todo is completed, the linked entry should be updated to reflect the outcome — then the todo is marked done. The todo disappears from the active view; the entry absorbs the knowledge.

**The relationship:** A todo may link to an entry (via `entry_id`) to provide context. Completing a todo should prompt updating the linked entry with outcomes before closing. An entry should never be the primary tracker of open work — that belongs in todos.

### Rooms

A room is a named collection of related knowledge — a project, a domain, a topic area.

Examples: `citadel-mcp`, `bike-rides`, `cooking`

Rooms are created organically as conversations introduce things worth capturing. They have tags for cross-cutting navigation. Room names are normalised to lowercase hyphenated slugs; the original name is stored as an alias.

### Entries

A room contains entries. Each entry is a coherent unit of knowledge — not a catch-all blob, and not an open work tracker.

Entries are living documents. Update the same entry as a topic develops. Create a new entry only when the conversation shifts into genuinely distinct territory. Entry `detail` supports Markdown.

Entry status values: `active`, `archived`, `deprecated`.

### Todos

A room also contains todo items. Each todo has a short integer ID (e.g. task 42) so it can be referenced conversationally.

The workflow:
1. Create a todo for actionable work, optionally linking it to a relevant entry via `entry_id`.
2. Work the todo through its lifecycle: `open` → `in_progress` → `blocked` / `done` / `cancelled` / `deferred`.
3. Before marking done: update the linked entry with the outcome. The entry absorbs the knowledge.
4. Mark the todo done. It recedes from the active view.

Todo priority: 1 (critical) to 5 (nice-to-have). Results sort by priority ascending, then due date, then creation time.

### The Manifest

At the start of a conversation the LLM calls `citadel_get_manifest` to see what rooms exist, then selectively retrieves only what's relevant. This two-step pattern keeps token cost low.

### Search

`citadel_search` uses SQLite FTS5 for ranked full-text search across title, summary, and detail. Each search term is matched as a prefix (`pyth` matches `python`). Multiple words are treated as AND. Results are ordered by relevance.

---

## MCP Tools

All tools are prefixed `citadel_`.

### Manifest

| Tool | Description |
|------|-------------|
| `citadel_get_manifest(tags?)` | All rooms, optionally filtered by tags (matches room tags and entry tags). |

### Room Operations

| Tool | Description |
|------|-------------|
| `citadel_add_room(name, tags?)` | Create a room. No-ops if already exists. |
| `citadel_update_room(room, name?, tags?, add_aliases?)` | Rename, retag, or add aliases. Rename re-points all entries automatically. |
| `citadel_delete_room(room)` | Permanently delete a room and all its entries. Irreversible. |

### Entry Operations

| Tool | Description |
|------|-------------|
| `citadel_get_room(room, status?, limit?, offset?)` | Summary-level entry list (no detail). Paginated. |
| `citadel_get_entry(entry_id, room?)` | Full entry including detail. `room` is optional. |
| `citadel_add_entry(room, title, summary, detail, tags?)` | Create a knowledge entry. Auto-creates room. |
| `citadel_bulk_add_entries(entries)` | Create multiple entries in one call. |
| `citadel_update_entry(room, entry_id, title?, summary?, detail?, status?, tags?)` | Update any fields. |
| `citadel_move_entry(entry_id, from_room, to_room)` | Move an entry between rooms. |
| `citadel_delete_entry(room, entry_id)` | Permanently delete. Use `status='archived'` for soft-delete. |

### Todo Operations

| Tool | Description |
|------|-------------|
| `citadel_get_todos(room?, status?, priority_max?, due_before?, limit?)` | List todos. Defaults to `status=['open']`. Pass `[]` for all statuses. |
| `citadel_get_todo(todo_id)` | Full todo by integer ID. |
| `citadel_add_todo(room, title, detail?, priority?, due_date?, entry_id?)` | Create a work item. |
| `citadel_update_todo(todo_id, title?, detail?, priority?, due_date?, status?, entry_id?)` | Update any fields. Update the linked entry before marking done. |
| `citadel_delete_todo(todo_id)` | Permanently delete. Use `status='cancelled'` for soft-delete. |

### Search

| Tool | Description |
|------|-------------|
| `citadel_search(query, room?, tags?, status?, limit?)` | FTS5 ranked search. `status` defaults to `active`. |

---

## Offline Viewer

```bash
python offline_citadel.py
python offline_citadel.py --output snapshot.html
```

Generates a self-contained HTML file showing all rooms, entries (with Markdown rendered), and all non-closed todos sorted by priority.

---

## File Structure

```
citadel/
  citadel_mcp.py     — entry point (wiring only)
  server.py          — shared MCP server and database instances
  rooms.py           — room management tools
  entries.py         — entry management tools
  todos.py           — todo list tools
  search.py          — FTS5 search tool
  helpers.py         — shared utilities (_now, _slugify, _resolve_room)
  models.py          — Pydantic input models
  sql.py             — Jinja2 SQL template loader
  db.py              — database abstraction (local SQLite + Turso backends)
  offline_citadel.py — static HTML snapshot generator
  migrate.py         — copies local SQLite data into Turso
  requirements.txt   — dependencies
  .env_example       — configuration template
  .env               — your local configuration (not committed)
  templates/
    citadel.html.j2  — offline viewer template
    sql/             — one SQL template per query (23 entry/room + 6 todo files)
```
