"""Restrict client injection to Discord pages on the exact local CDP endpoint."""
import ntpath
import re
from urllib.parse import unquote, urlsplit


def allowed_page(target, port, install_dir):
    if not isinstance(target, dict) or target.get("type") != "page":
        return False
    identity = target.get("id")
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identity):
        return False
    try:
        socket = urlsplit(target.get("webSocketDebuggerUrl", ""))
        if (socket.scheme != "ws" or socket.hostname != "127.0.0.1" or socket.port != port
                or socket.username is not None or socket.password is not None or socket.query or socket.fragment
                or socket.path != "/devtools/page/" + identity):
            return False
        page = urlsplit(target.get("url", ""))
        if page.username is not None or page.password is not None:
            return False
        if page.scheme == "https":
            return page.hostname in {"discord.com", "ptb.discord.com", "canary.discord.com"} and page.port in (None, 443)
        if page.scheme == "file" and not page.netloc and not page.query and not page.fragment:
            local = ntpath.normcase(unquote(page.path).lstrip("/"))
            root = ntpath.normcase(ntpath.abspath(str(install_dir))).rstrip("\\/") + "\\"
            local = ntpath.normcase(ntpath.abspath(local.replace("/", "\\")))
            return local.startswith(root) and local.endswith("\\resources\\app.asar\\static\\views\\first-launch.html")
    except (ValueError, TypeError, AttributeError):
        return False
    return False


def select_page(targets, port, install_dir):
    if not isinstance(targets, list):
        return None
    candidates = [target for target in targets if allowed_page(target, port, install_dir)]
    return candidates[0] if len(candidates) == 1 else None
