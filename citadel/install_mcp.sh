#!/bin/sh

# Create /opt if it doesn't exist
mkdir -p /opt

# Refresh the code base
if [ -d /opt/mcp ]; then
    cd /opt/mcp && git pull
else
    cd /opt && git clone https://github.com/massyn/mcp
fi

# Change the permissions of /opt/mcp to www-data:www-data
chown -R www-data:www-data /opt/mcp

# Create the data folder
mkdir -p /data
mkdir -p /data/citadel
chown -R www-data:www-data /data/citadel


# Create a python venv and install requirements
python3 -m venv /opt/mcp/venv
/opt/mcp/venv/bin/pip install -q -r /opt/mcp/relay/requirements.txt

# Write .env to /opt/mcp/relay
# If values already exist from a previous run, reuse them; otherwise generate/prompt.
ENV_FILE=/opt/mcp/relay/.env
SLUG=citadel

if [ -f "$ENV_FILE" ]; then
    RELAY_TOKEN=$(grep -E '^RELAY_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
    RELAY_BASE_URL=$(grep -E '^RELAY_BASE_URL=' "$ENV_FILE" | cut -d= -f2-)
    RELAY_CLIENT_ID=$(grep -E '^RELAY_CLIENT_ID=' "$ENV_FILE" | cut -d= -f2-)
    RELAY_CLIENT_SECRET=$(grep -E '^RELAY_CLIENT_SECRET=' "$ENV_FILE" | cut -d= -f2-)
fi

if [ -z "$RELAY_TOKEN" ]; then
    RELAY_TOKEN=$(openssl rand -hex 32)
    echo "Generated RELAY_TOKEN."
fi

if [ -z "$RELAY_BASE_URL" ]; then
    printf 'Enter public base URL (e.g. https://mcp.massyn.net/citadel): '
    read -r RELAY_BASE_URL
fi

if [ -z "$RELAY_CLIENT_ID" ]; then
    RELAY_CLIENT_ID=$(openssl rand -hex 16)
    echo "Generated RELAY_CLIENT_ID."
fi

if [ -z "$RELAY_CLIENT_SECRET" ]; then
    RELAY_CLIENT_SECRET=$(openssl rand -hex 32)
    echo "Generated RELAY_CLIENT_SECRET."
fi

cat > "$ENV_FILE" << EOF
RELAY_CODE=/opt/mcp/relay/citadel/
RELAY_TRANSPORT=http
RELAY_TOKEN=${RELAY_TOKEN}
RELAY_BASE_URL=${RELAY_BASE_URL}
RELAY_CLIENT_ID=${RELAY_CLIENT_ID}
RELAY_CLIENT_SECRET=${RELAY_CLIENT_SECRET}
DB_TYPE=sqlite
DB_PATH=/data/${SLUG}/${SLUG}.db
EOF

echo ""
echo "=== OAuth credentials (paste these into Claude.ai) ==="
echo "  Client ID     : ${RELAY_CLIENT_ID}"
echo "  Client Secret : ${RELAY_CLIENT_SECRET}"
echo "======================================================"
echo ""

# Write the systemd service file
cat > /etc/systemd/system/${SLUG}.service << EOF
[Unit]
Description={$SLUG} Relay MCP server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/mcp/relay
EnvironmentFile=$ENV_FILE
ExecStart=/opt/mcp/venv/bin/python relay.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Write the nginx config
cat > /etc/nginx/sites-enabled/${SLUG}.conf << EOF
server {
    listen 80;
    server_name mcp.massyn.net;

    location /ping {
        return 200 'pong';
        add_header Content-Type text/plain;
    }

    # MCP traffic (OAuth sub-paths /${SLUG}/authorize, /token also flow through here)
    location /${SLUG} {
        proxy_pass http://localhost:8788/mcp;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }

    # OAuth 2.1 discovery endpoints (RFC 8414 / RFC 9728)
    location /.well-known/ {
        proxy_pass http://localhost:8788/.well-known/;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
    }
}
EOF

# Reload systemd, enable and restart the relay service, then restart nginx
systemctl daemon-reload
systemctl enable ${SLUG}
systemctl restart ${SLUG}
systemctl restart nginx
