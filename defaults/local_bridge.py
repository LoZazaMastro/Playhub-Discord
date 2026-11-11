"""Ephemeral authentication for the private Discord client's loopback channel."""
import secrets
import asyncio
import json
from urllib.parse import urlsplit
from aiohttp.web import AppRunner, TCPSite

TOKEN = secrets.token_urlsafe(32)
LEGACY_PORT = 65123


def endpoint_port(port, windows):
    if port is None and not windows:
        return LEGACY_PORT
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError("The private Discord bridge is not ready")
    return port


def http_url(path, port, windows):
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ValueError("Invalid private Discord bridge path")
    return f"http://127.0.0.1:{endpoint_port(port, windows)}{path}"


def client_bootstrap(host_name, port):
    selected = endpoint_port(port, host_name == "windows")
    return ("window.STEAMCORD_HOST = " + json.dumps(host_name) + ";\n"
            "window.STEAMCORD_BRIDGE_PORT = " + str(selected) + ";\n"
            "window.STEAMCORD_BRIDGE_TOKEN = " + json.dumps(TOKEN) + ";\n")


class BridgeServer:
    """Own one listener; publish its OS-selected port only after it is bound."""
    def __init__(self):
        self.runner = None
        self.site = None
        self.port = None
        self.clients = set()

    async def start(self, application, windows):
        if self.runner is not None:
            raise RuntimeError("The private Discord bridge is already started")
        self.runner = AppRunner(application, access_log=None, shutdown_timeout=1)
        try:
            await asyncio.wait_for(self.runner.setup(), 3)
            address = "127.0.0.1" if windows else "0.0.0.0"
            self.site = TCPSite(self.runner, address, 0 if windows else LEGACY_PORT)
            await asyncio.wait_for(self.site.start(), 3)
            addresses = self.runner.addresses
            if len(addresses) != 1 or addresses[0][0] != address:
                raise RuntimeError("Unexpected private Discord bridge listener")
            self.port = endpoint_port(addresses[0][1], windows)
            if not windows and self.port != LEGACY_PORT:
                raise RuntimeError("Unexpected Linux Discord bridge port")
            return self.port
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self.port = None
        runner, self.runner = self.runner, None
        site, self.site = self.site, None
        if site is not None:
            try:
                await asyncio.wait_for(site.stop(), 1)
            except Exception:
                pass
        if self.clients:
            try:
                await asyncio.wait_for(asyncio.gather(*(
                    client.close(code=1001, message=b"Plugin shutdown")
                    for client in tuple(self.clients))), 1)
            except Exception:
                pass
            self.clients.clear()
        if runner is not None:
            try:
                await asyncio.wait_for(runner.cleanup(), 2)
            except Exception:
                pass


def authorized_token(request):
    supplied = request.query.get("bridge", "")
    return isinstance(supplied, str) and secrets.compare_digest(supplied, TOKEN)


def authorized(request):
    if not authorized_token(request):
        return False
    try:
        origin = urlsplit(request.headers.get("Origin", ""))
        return (origin.scheme == "https" and origin.hostname in
                {"discord.com", "ptb.discord.com", "canary.discord.com"}
                and origin.port in (None, 443) and not origin.username and not origin.password
                and origin.path in ("", "/") and not origin.query and not origin.fragment)
    except (TypeError, ValueError):
        return False
