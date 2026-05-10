"""Install MCP servers into claude_desktop_config.json."""

import argparse
import json
import platform
import shutil
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


def find_python() -> str:
    return sys.executable


def load_manifest(name: str) -> tuple[Path, dict]:
    manifest_path = Path(__file__).parent / name / "mcp.json"
    if not manifest_path.exists():
        sys.exit(f"No mcp.json found for '{name}' (looked in {manifest_path})")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    for key in ("script", "alwaysAllow"):
        if key not in manifest:
            sys.exit(f"{manifest_path}: missing required key '{key}'")
    return manifest_path.parent, manifest


def install_server(name: str) -> None:
    server_dir, manifest = load_manifest(name)
    server_script = (server_dir / manifest["script"]).resolve()

    if not server_script.exists():
        sys.exit(f"Server script not found: {server_script}")

    python_cmd = find_python()
    config_path = get_config_path()

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}

    config.setdefault("mcpServers", {})

    desired = {
        "command": python_cmd,
        "args": [str(server_script)],
        "alwaysAllow": manifest["alwaysAllow"],
    }

    existing = config["mcpServers"].get(name)
    if existing == desired:
        print(f"{name} MCP is already configured correctly — nothing to do.")
        return

    if existing:
        old_path = (existing.get("args") or [None])[0]
        new_path = str(server_script)
        if old_path != new_path:
            print(f"{name} MCP path changed — updating.")
            print(f"  Old: {old_path}")
            print(f"  New: {new_path}")
        else:
            print(f"{name} MCP config updated.")

    config["mcpServers"][name] = desired

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    if existing:
        print(f"{name} MCP updated in {config_path}")
    else:
        print(f"{name} MCP added to {config_path}")
    print(f"Server path: {server_script}")
    print(f"Python command: {python_cmd}")
    print("Restart Claude Desktop to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install MCP servers into Claude Desktop config.",
        epilog="Each server directory must contain an mcp.json manifest.",
    )
    parser.add_argument(
        "server",
        help="Name of the server directory to install (must contain mcp.json)",
    )
    args = parser.parse_args()
    install_server(args.server)


if __name__ == "__main__":
    main()
