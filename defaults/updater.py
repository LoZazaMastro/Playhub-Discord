"""This Windows fork is updated by Playhub's verified plugin catalog."""
import json
from pathlib import Path
from decky import DECKY_PLUGIN_DIR


def get_current_version():
    try:
        return str(json.loads((Path(DECKY_PLUGIN_DIR) / "package.json").read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        return "1.0.0"


def is_autoupdate_enabled():
    return False


def set_autoupdate_enabled(enabled):
    return False


async def check():
    version = get_current_version()
    return {"current": version, "latest": version, "update_available": False,
            "url": "", "notes": "", "managed": "playhub"}


async def apply(url):
    return {"ok": False, "error": "managed_by_playhub"}


def restart_loader():
    return False
