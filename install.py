"""Install MCP servers into Claude Desktop config and VS Code settings.json."""

import argparse
import json
import platform
import re
import sys
from pathlib import Path


def get_claude_config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        sys.exit(f"Unsupported platform: {system}")


def get_vscode_settings_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Code" / "User" / "settings.json"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    else:
        return Path.home() / ".config" / "Code" / "User" / "settings.json"


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


def strip_jsonc(text: str) -> str:
    """Strip // line comments and /* */ block comments, and trailing commas from JSONC."""
    result = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\" and i + 1 < n:
                result.append(c)
                result.append(text[i + 1])
                i += 2
                continue
            elif c == '"':
                in_string = False
            result.append(c)
            i += 1
        else:
            if c == '"':
                in_string = True
                result.append(c)
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i < n - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                result.append(c)
                i += 1
    cleaned = "".join(result)
    # Remove trailing commas before } or ]
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def install_claude_desktop(name: str, server_script: Path, python_cmd: str, manifest: dict) -> None:
    config_path = get_claude_config_path()

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
        print(f"[Claude Desktop] {name}: already configured correctly — nothing to do.")
        return

    if existing:
        old_path = (existing.get("args") or [None])[0]
        new_path = str(server_script)
        if old_path != new_path:
            print(f"[Claude Desktop] {name}: path changed — updating.")
            print(f"  Old: {old_path}")
            print(f"  New: {new_path}")
        else:
            print(f"[Claude Desktop] {name}: config updated.")

    config["mcpServers"][name] = desired

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    if existing:
        print(f"[Claude Desktop] {name}: updated in {config_path}")
    else:
        print(f"[Claude Desktop] {name}: added to {config_path}")
    print(f"  Server path: {server_script}")
    print(f"  Python: {python_cmd}")
    print("  Restart Claude Desktop to apply.")


def install_vscode(name: str, server_script: Path, python_cmd: str) -> None:
    settings_path = get_vscode_settings_path()

    if not settings_path.parent.exists():
        print(f"[VS Code] Settings directory not found ({settings_path.parent}) — VS Code may not be installed, skipping.")
        return

    if settings_path.exists():
        raw = settings_path.read_text(encoding="utf-8")
        try:
            settings = json.loads(strip_jsonc(raw))
        except json.JSONDecodeError as e:
            print(f"[VS Code] Could not parse {settings_path}: {e} — skipping VS Code registration.")
            return
    else:
        settings = {}

    if not isinstance(settings.get("mcp"), dict):
        settings["mcp"] = {}
    if not isinstance(settings["mcp"].get("servers"), dict):
        settings["mcp"]["servers"] = {}

    desired: dict = {
        "type": "stdio",
        "command": python_cmd,
        "args": [str(server_script)],
        "env": {},
    }

    existing = settings["mcp"]["servers"].get(name)
    if existing == desired:
        print(f"[VS Code] {name}: already configured correctly — nothing to do.")
        return

    if existing:
        old_path = (existing.get("args") or [None])[0]
        new_path = str(server_script)
        if old_path != new_path:
            print(f"[VS Code] {name}: path changed — updating.")
            print(f"  Old: {old_path}")
            print(f"  New: {new_path}")
        else:
            print(f"[VS Code] {name}: config updated.")

    settings["mcp"]["servers"][name] = desired

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    if existing:
        print(f"[VS Code] {name}: updated in {settings_path}")
    else:
        print(f"[VS Code] {name}: added to {settings_path}")
    print("  Restart VS Code to apply.")


def install_server(name: str) -> None:
    server_dir, manifest = load_manifest(name)
    server_script = (server_dir / manifest["script"]).resolve()

    if not server_script.exists():
        sys.exit(f"Server script not found: {server_script}")

    python_cmd = find_python()

    install_claude_desktop(name, server_script, python_cmd, manifest)
    install_vscode(name, server_script, python_cmd)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install MCP servers into Claude Desktop and VS Code configs.",
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
