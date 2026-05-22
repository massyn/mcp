# AWS Route53 Domain Availability Checker MCP Server

An MCP (Model Context Protocol) server that allows Claude to check domain availability and inspect registered domains using the AWS Route53 Domains API.

## Features

- Check domain registration availability through Claude
- List all registered domains with full detail: name servers, expiry, creation and update dates, auto-renew, transfer lock, DNSSEC status, and registrar
- Filter registered domains by substring (e.g. show only `.com` or `acme` domains)
- Support for multiple domains in a single query
- AWS profile support for multi-account setups
- Returns clear availability status: AVAILABLE, UNAVAILABLE, RESERVED, or DONT_KNOW

## Prerequisites

- Python 3.10 or higher
- AWS account with Route53 Domains access
- AWS credentials configured (via `~/.aws/credentials` or environment variables)
- Claude Desktop app or compatible MCP client

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure AWS credentials are configured:
```bash
# Check if credentials exist
cat ~/.aws/credentials

# Or set environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
```

3. Register with Claude Desktop using the install script from the repository root:
```bash
python install.py route53
```

Restart Claude Desktop after running.

## AWS Permissions Required

Your AWS IAM user/role needs the following permissions:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53domains:CheckDomainAvailability",
        "route53domains:ListDomains",
        "route53domains:GetDomainDetail"
      ],
      "Resource": "*"
    }
  ]
}
```

`CheckDomainAvailability` is required for the availability checker. `ListDomains` and `GetDomainDetail` are required to list registered domains with full detail.

## Configuration for Claude Desktop

Run the install script from the repository root — it detects `python3` or `python` automatically and writes the correct config for your platform:

```bash
python install.py route53
```

Config file locations:
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

The resulting config entry looks like:

```json
{
  "mcpServers": {
    "route53": {
      "command": "python3",
      "args": ["/path/to/route53/mcpdns.py"],
      "alwaysAllow": ["check_domain_availability", "list_registered_domains"]
    }
  }
}
```

## Using with Specific AWS Profiles

To use a specific AWS profile, add an `env` block to the config entry manually after running the install script:

```json
{
  "mcpServers": {
    "route53": {
      "command": "python3",
      "args": ["/path/to/route53/mcpdns.py"],
      "alwaysAllow": ["check_domain_availability", "list_registered_domains"],
      "env": {
        "AWS_PROFILE": "production"
      }
    }
  }
}
```

## Usage in Claude

After configuring the MCP server and restarting Claude Desktop, you can ask Claude to check domain availability:

**Example prompts:**
- "Check if example.com is available for registration"
- "Are these domains available: mysite.com, mysite.org, mysite.net"
- "I need to register a domain for my project. Can you check if projectname.io is available?"
- "List all my registered domains"
- "Show me all my .com domains"
- "Which of my domains expire this year?"
- "Do any of my domains have DNSSEC disabled?"

**Availability check example response:**
```
Domain Availability Check Results:

✅ example.com: Available for registration
❌ google.com: Already registered
🔒 reserved-domain.com: Reserved (cannot be registered)
```

**List registered domains example response:**
```
Registered Domains — 2 result(s) (filter: '.com')

Domain:       example.com
Expiry:       2026-11-14T00:00:00+00:00
Created:      2010-11-14T00:00:00+00:00
Updated:      2024-03-01T12:34:56+00:00
Auto-renew:   yes
Transfer lock:yes
DNSSEC:       disabled
Registrar:    Amazon Registrar, Inc.
Registrar URL:https://registrar.amazon.com
Status:       ACTIVE
Name servers:
  - ns-123.awsdns-45.com
  - ns-456.awsdns-78.net
```

## Using the Profile Parameter in Claude

You can specify a different AWS profile when asking Claude to check domains:

"Check if example.com is available using the 'production' AWS profile"

## Testing

You can test the domain lookup functionality directly without Claude:

```bash
python lookup_route53.py
```

This will check the example domains using your default AWS profile.

## Troubleshooting

### MCP Server Not Showing Up in Claude

1. Check that the path in `claude_desktop_config.json` is correct and absolute
2. Restart Claude Desktop completely
3. Check Claude Desktop logs for errors:
   - Windows: `%APPDATA%\Claude\logs`
   - macOS: `~/Library/Logs/Claude`
   - Linux: `~/.config/Claude/logs`

### AWS Credentials Error

If you see "AWS credentials not configured":
1. Verify credentials exist: `cat ~/.aws/credentials`
2. Check environment variables: `echo $AWS_ACCESS_KEY_ID`
3. Ensure the IAM user has the required `route53domains` permissions (see AWS Permissions Required above)

### Region Errors

The Route53 Domains API only works in `us-east-1` region. This is hardcoded in the script and should work automatically.

### Permission Denied Errors

On macOS/Linux, make the script executable:
```bash
chmod +x mcp.py
```

## Files

- `mcpdns.py` - MCP server implementation
- `lookup_route53.py` - Core domain lookup logic
- `requirements.txt` - Python dependencies
- `README.md` - This file

## Cost Considerations

AWS Route53 domain availability checks are **free** for the first 10 requests per AWS account per day. After that, each request costs $0.001 USD.

## Security Notes

- Never commit AWS credentials to version control
- Use IAM roles with minimal required permissions
- Consider using AWS Organizations SCPs to restrict domain registration if needed
- Store sensitive configuration in `.env` files (excluded from git)

## License

This project is provided as-is for checking domain availability through AWS Route53.
