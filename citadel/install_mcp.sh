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
# If RELAY_TOKEN already exists from a previous run, reuse it; otherwise prompt.
ENV_FILE=/opt/mcp/relay/.env

if [ -f "$ENV_FILE" ]; then
    RELAY_TOKEN=$(grep -E '^RELAY_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
fi

if [ -z "$RELAY_TOKEN" ]; then
    printf 'Enter RELAY_TOKEN: '
    read -r RELAY_TOKEN
fi

cat > "$ENV_FILE" << EOF
RELAY_CODE=/opt/mcp/relay/citadel/
RELAY_TRANSPORT=http
RELAY_TOKEN=${RELAY_TOKEN}
DB_TYPE=sqlite
DB_PATH=/data/citadel/citadel.db
EOF

# Write the systemd service file
cat > /etc/systemd/system/relay.service << EOF
[Unit]
Description=Relay MCP server
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
cat > /etc/nginx/sites-enabled/mcp.conf << EOF
server {
    listen 80;
    server_name mcp.massyn.net;

    location /ping {
        return 200 'pong';
        add_header Content-Type text/plain;
    }

    location /citadel {
        proxy_pass http://localhost:8788/mcp;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
}
EOF

# Reload systemd, enable and restart the relay service, then restart nginx
systemctl daemon-reload
systemctl enable relay
systemctl restart relay
systemctl restart nginx
