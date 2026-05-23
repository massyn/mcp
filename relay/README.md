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

All configuration is via environment variables. A `.env` file inside the code directory is loaded automatically.

| Variable | CLI override | Description |
|---|---|---|
| `RELAY_CODE` | `--code` | Path to the code directory (required) |
| `DB_TYPE` | — | `sqlite` or `turso`; auto-detected from `TURSO_URL` if not set |
| `DB_PATH` | — | SQLite path (default: `~/.relay/relay.db`) |
| `TURSO_URL` | — | Turso database URL (`libsql://...`); presence implies `DB_TYPE=turso` |
| `TURSO_TOKEN` | — | Turso auth token |

`RELAY_CODE` is typically set in the MCP client config, not in the code directory's `.env` (that would be circular). All other variables can live in the `.env`.

## Usage

### As an MCP server (production)

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
