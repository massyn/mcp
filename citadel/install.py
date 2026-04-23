"""Install Citadel MCP into claude_desktop_config.json."""

import json
import platform
import sys
from pathlib import Path


def get_config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        sys.exit(f"Unsupported platform: {system}")


ALWAYS_ALLOW = [
    "citadel_get_manifest",
    "citadel_add_room",
    "citadel_delete_room",
    "citadel_get_room",
    "citadel_get_entry",
    "citadel_add_entry",
    "citadel_update_entry",
    "citadel_delete_entry",
    "citadel_search",
]

DESIRED_ENTRY = {
    "command": "python",
    "args": None,  # filled in below
    "alwaysAllow": ALWAYS_ALLOW,
}


def main() -> None:
    server_script = (Path(__file__).parent / "citadel_mcp.py").resolve()
    config_path = get_config_path()

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}

    config.setdefault("mcpServers", {})

    desired = {
        "command": "python",
        "args": [str(server_script)],
        "alwaysAllow": ALWAYS_ALLOW,
    }

    existing = config["mcpServers"].get("citadel")
    if existing == desired:
        print("Citadel MCP is already configured correctly — nothing to do.")
        return

    if existing:
        old_path = (existing.get("args") or [None])[0]
        new_path = str(server_script)
        if old_path != new_path:
            print("Citadel MCP path changed — updating.")
            print(f"  Old: {old_path}")
            print(f"  New: {new_path}")
        else:
            print("Citadel MCP config updated (alwaysAllow list).")

    config["mcpServers"]["citadel"] = desired

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    if existing:
        print(f"Citadel MCP updated in {config_path}")
    else:
        print(f"Citadel MCP added to {config_path}")
    print(f"Server path: {server_script}")
    print("Restart Claude Desktop to apply.")


if __name__ == "__main__":
    main()
