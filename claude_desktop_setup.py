"""Connect the read-only MCP server (mcp_server.py) to the Claude Desktop app.

    .venv\\Scripts\\python claude_desktop_setup.py            # show the config snippet for this computer
    .venv\\Scripts\\python claude_desktop_setup.py --install  # add it to Claude Desktop's config file

--install keeps every other MCP server in the config and writes a .bak copy first.
Afterwards fully quit Claude Desktop (tray/menu bar icon -> Quit) and start it again.
"""

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER_NAME = "garmin-training"


def venv_python() -> Path:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        if (ROOT / rel).exists():
            return ROOT / rel
    return Path(sys.executable)


def config_path() -> Path:
    """Claude Desktop's config file (it may not exist yet)."""
    if sys.platform == "win32":
        # The Microsoft Store / MSIX install keeps its config in a virtualised folder.
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
        for pkg in sorted(packages.glob("Claude_*")) if packages.exists() else []:
            msix = pkg / "LocalCache" / "Roaming" / "Claude"
            if msix.exists():
                return msix / "claude_desktop_config.json"
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def server_entry() -> dict:
    return {"command": str(venv_python()), "args": [str(ROOT / "mcp_server.py")]}


def install() -> None:
    path = config_path()
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            sys.exit(f"{path} is not valid JSON ({e}). Fix it by hand or add the snippet manually.")
        shutil.copy2(path, path.with_suffix(".json.bak"))
    cfg.setdefault("mcpServers", {})[SERVER_NAME] = server_entry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"Added '{SERVER_NAME}' to {path}")
    print("Now fully quit Claude Desktop (tray/menu bar icon -> Quit) and start it again.")


def main() -> None:
    if "--install" in sys.argv:
        install()
        return
    print(f"Claude Desktop config file: {config_path()}")
    print("Add this (merge it into an existing \"mcpServers\" block if there is one):\n")
    print(json.dumps({"mcpServers": {SERVER_NAME: server_entry()}}, indent=2))
    print("\nOr let this script do it: python claude_desktop_setup.py --install")


if __name__ == "__main__":
    main()
