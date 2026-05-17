"""Citadel MCP — personal knowledge management server for LLMs."""

import argparse

import entries  # noqa: F401 — registers entry tools on mcp
import rooms    # noqa: F401 — registers room tools on mcp
import search   # noqa: F401 — registers search tool on mcp
import todos    # noqa: F401 — registers todo tools on mcp
from server import mcp

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Citadel MCP server")
    parser.add_argument("--http", action="store_true", help="Run as HTTP server instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (HTTP mode only)")
    parser.add_argument("--port", type=int, default=8000, help="Port (HTTP mode only)")
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
