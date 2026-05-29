# mcp

A collection of MCP servers built around two patterns: **local stdio** for tools that run on your machine, and **remote HTTP** for tools hosted on a server and shared across clients.

## Servers

| Server | Transport | Description |
|--------|-----------|-------------|
| [Citadel](./citadel/) | HTTP (relay) | Personal knowledge management — rooms, entries, todos |
| [Publish S3](./publishs3/) | stdio | Publish HTML, Markdown, and PDF to an S3 static website |
| [Route53](./route53/) | stdio | Check domain availability and inspect registered domains via AWS |

---

## Installation

### Local stdio servers

Clone the repo, install dependencies, then register with Claude Code:

```bash
git clone https://github.com/massyn/mcp
cd mcp
```

**Publish S3**
```bash
pip install -r publishs3/requirements.txt
claude mcp add publishs3 -- python $(pwd)/publishs3/publishs3_mcp.py
```

**Route53**
```bash
pip install -r route53/requirements.txt
claude mcp add route53 -- python $(pwd)/route53/mcpdns.py
```

### Remote HTTP servers (Citadel)

Citadel runs on a server via the [Relay](./relay/) bridge. Once deployed, connect any Claude client with a single command — no local installation required:

```bash
claude mcp add --transport http citadel https://your-host/citadel \
  --header "Authorization: Bearer <your-token>"
```

See [citadel/install_mcp.sh](./citadel/install_mcp.sh) for the server-side deployment script.

---

## Architecture

### stdio

Standard MCP over stdin/stdout. Runs as a subprocess of the MCP client. Suitable for tools that need local filesystem or credential access (AWS keys, `.env` files).

```
Claude Code → subprocess → server.py → AWS / S3 / etc.
```

### HTTP via Relay

[Relay](./relay/) is a generic bridge that turns SQL definition files into MCP tools. Point it at a directory containing an `index.yaml` and a `sql/` folder — each `.sql` file becomes a live tool. Relay handles transport (stdio or HTTP), authentication (OAuth 2.1 + bearer token), and database backends (SQLite or Turso).

```
Claude (any client) → HTTPS → nginx → relay.py → SQLite / Turso
```

This pattern lets you host an MCP server once and connect to it from Claude.ai, Claude Code, Claude Desktop, or any other MCP-compatible client without running anything locally.

See [relay/README.md](./relay/README.md) for the full Relay reference.

---

## Building your own Relay-backed server

1. Create a directory with an `index.yaml` (server name + system prompt) and a `sql/` folder
2. Write `.sql` files — front matter defines the tool, body is the SQL
3. Run `relay.py --code ./your-dir`

The Citadel implementation in `citadel/relay_code/` is the reference example.
