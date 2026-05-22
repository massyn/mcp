# mcp
A collection of MCP services I am working on

* [Citadel](./citadel/README.md) - a knowledge management system
* [Publish S3](./publishs3/README.md) - publish HTML, markdown, and PDF to an S3 static website
* [Route53](./route53/README.md) - check domain availability via AWS Route53
* [UptimeRobot](./uptimerobot/README.md) - list, search, and edit UptimeRobot monitors

## Installation

Use `install.py` at the root to register any MCP server with Claude Desktop:

```bash
python install.py citadel
python install.py publishs3
python install.py route53
python install.py uptimerobot
```

The script uses the interpreter that runs it (`sys.executable`), so the registered server always uses the same Python environment. Restart Claude Desktop after running.

Config file locations:
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

## Adding a new server

Each server directory must contain an `mcp.json` manifest:

```json
{
  "script": "server.py",
  "alwaysAllow": [
    "tool_name_one",
    "tool_name_two"
  ]
}
```

| Field | Description |
|-------|-------------|
| `script` | Entry-point Python file, relative to the server directory |
| `alwaysAllow` | MCP tool names that Claude Desktop will call without prompting |

Once the manifest exists, `python install.py <directory-name>` is all that is needed.