#!/usr/bin/env python3
"""
MCP Server for AWS Route53 Domain Availability Checker

This MCP server allows Claude to check if domains are available for registration
using the AWS Route53 Domains API.
"""

import asyncio
import json
import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from lookup_route53 import does_domain_exist

# Create server instance
server = Server("route53-domain-checker")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """
    List available tools.
    """
    return [
        Tool(
            name="check_domain_availability",
            description=(
                "Check if one or more domains are available for registration using AWS Route53. "
                "Returns the availability status for each domain: AVAILABLE (can be registered), "
                "UNAVAILABLE (already registered), RESERVED (cannot be registered), or DONT_KNOW. "
                "Requires AWS credentials to be configured."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of domain names to check (e.g., ['example.com', 'mysite.org'])",
                        "minItems": 1
                    },
                    "profile": {
                        "type": "string",
                        "description": "AWS profile name to use (optional, defaults to default profile)",
                        "default": None
                    }
                },
                "required": ["domains"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Handle tool calls.
    """
    if name == "check_domain_availability":
        domains = arguments.get("domains", [])
        profile = arguments.get("profile")

        # If no profile specified in arguments, check environment variable
        if not profile:
            profile = os.environ.get("AWS_PROFILE")

        if not domains:
            return [TextContent(
                type="text",
                text="Error: No domains provided. Please specify at least one domain to check."
            )]

        # Call the domain lookup function
        try:
            results = does_domain_exist(domains, profile=profile)

            # Format the results
            output_lines = ["Domain Availability Check Results:", ""]

            for result in results:
                domain = result['domain']
                status = result['result']

                # Add emoji indicators for better readability
                if status == 'AVAILABLE':
                    indicator = "✅"
                    message = "Available for registration"
                elif status == 'UNAVAILABLE':
                    indicator = "❌"
                    message = "Already registered"
                elif status == 'RESERVED':
                    indicator = "🔒"
                    message = "Reserved (cannot be registered)"
                elif status == 'DONT_KNOW':
                    indicator = "❓"
                    message = "Cannot determine availability"
                elif status.startswith('error:'):
                    indicator = "⚠️"
                    message = status
                else:
                    indicator = "ℹ️"
                    message = status

                output_lines.append(f"{indicator} {domain}: {message}")

            output_text = "\n".join(output_lines)

            return [TextContent(
                type="text",
                text=output_text
            )]

        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error checking domain availability: {str(e)}"
            )]

    else:
        return [TextContent(
            type="text",
            text=f"Unknown tool: {name}"
        )]


async def main():
    """
    Main entry point for the MCP server.
    """
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
