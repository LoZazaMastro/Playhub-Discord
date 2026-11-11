"""Real loopback HTTP/WebSocket fixtures; no Discord or Steam is launched."""
import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, web

DEFAULTS = Path(__file__).resolve().parents[1] / "defaults"
sys.path.insert(0, str(DEFAULTS))
import discord_cdp
import local_bridge
import windows_identity


class PageFilterTests(unittest.TestCase):
    def page(self, url="https://discord.com/channels/@me"):
        return {"type": "page", "title": "Discord", "id": "A123", "url": url,
                "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/A123"}

    def test_exact_origins_only(self):
        for url in ("https://discord.com/login", "https://ptb.discord.com/channels/@me", "https://canary.discord.com"):
            self.assertTrue(discord_cdp.allowed_page(self.page(url), 9223, r"C:\private"))
        for url in ("https://discord.com.attacker.invalid/", "https://attacker.invalid/discord.com", "http://discord.com",
                    "https://discord.com:444", "https://user@discord.com", "chrome://inspect", "javascript:alert(1)"):
            self.assertFalse(discord_cdp.allowed_page(self.page(url), 9223, r"C:\private"))

    def test_debugger_identity_and_ambiguity(self):
        page = self.page()
        for socket in ("ws://localhost:9223/devtools/page/A123", "ws://127.0.0.1:9224/devtools/page/A123",
                       "ws://127.0.0.1:9223/devtools/page/B456", "ws://127.0.0.1:9223/devtools/page/A123?x=1",
                       "ws://u@127.0.0.1:9223/devtools/page/A123"):
            self.assertFalse(discord_cdp.allowed_page({**page, "webSocketDebuggerUrl": socket}, 9223, r"C:\private"))
        self.assertEqual(discord_cdp.select_page([page, self.page("https://example.org")], 9223, r"C:\private"), page)
        self.assertIsNone(discord_cdp.select_page([page, page], 9223, r"C:\private"))
        self.assertIsNone(discord_cdp.select_page({}, 9223, r"C:\private"))

    def test_first_launch_only_inside_private_asar(self):
        self.assertTrue(discord_cdp.allowed_page(self.page("file:///C:/private/resources/app.asar/static/views/first-launch.html"), 9223, r"C:\private"))
        for url in ("file:///C:/private-other/resources/app.asar/static/views/first-launch.html",
                    "file:///C:/private/../other/resources/app.asar/static/views/first-launch.html",
                    "file://remote/C:/private/resources/app.asar/static/views/first-launch.html"):
            self.assertFalse(discord_cdp.allowed_page(self.page(url), 9223, r"C:\private"))

    def test_native_process_identity_is_birth_bound(self):
        current = windows_identity.read(os.getpid())
        if sys.platform != "win32":
            self.skipTest("Windows process identity")
        self.assertIsNotNone(current)
        self.assertTrue(windows_identity.matches(current, sys.executable))
        self.assertFalse(windows_identity.matches({**current, "birth": current["birth"] + 1}, sys.executable))
        self.assertFalse(windows_identity.matches({**current, "pid": True}, sys.executable))
        self.assertFalse(windows_identity.matches(current, r"C:\foreign\Vesktop.exe"))
        self.assertIsNone(windows_identity.capture(os.getpid(), sys.executable, -1))


class CdpLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.commands = []
        self.requests = []
        self.owned = True
        self.redirect = False
        self.targets = []
        app = web.Application()

        async def listing(request):
            self.requests.append(request.path)
            if self.redirect:
                return web.Response(status=302, headers={"Location": "http://127.0.0.1:1/foreign"})
            return web.json_response({"Browser": "fixture"} if request.path.endswith("version") else self.targets)

        async def debugger(request):
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            async for message in websocket:
                command = message.json(); self.commands.append(command)
                await websocket.send_json({"id": command["id"], "result": {"fixture": True}})
            return websocket

        app.router.add_get("/json", listing)
        app.router.add_get("/json/version", listing)
        app.router.add_get("/devtools/page/A123", debugger)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.targets = [{"type": "page", "title": "Discord", "id": "A123", "url": "https://discord.com/login",
                         "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/A123"}]
        self.host = types.SimpleNamespace(WINDOWS=True)
        self.win = types.SimpleNamespace(owns_cdp=lambda: self.owned, CDP_PORT=self.port, install_dir=lambda: Path(r"C:\private"))
        # Other upstream fixtures stub tab_utils globally. This integration
        # fixture deliberately loads the real CDP implementation every time.
        cdp_spec = importlib.util.spec_from_file_location("fixture_real_cdp", DEFAULTS / "tab_utils/cdp.py")
        real_cdp = importlib.util.module_from_spec(cdp_spec); cdp_spec.loader.exec_module(real_cdp)
        with patch.dict(sys.modules, {"host": self.host, "vesktop_win": self.win,
                                     "tab_utils.cdp": real_cdp,
                                     "decky": types.SimpleNamespace(logger=logging.getLogger(__name__))}):
            spec = importlib.util.spec_from_file_location("fixture_vesktop", DEFAULTS / "vesktop.py")
            self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.module.VESKTOP_CDP = f"http://127.0.0.1:{self.port}"

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_real_http_and_websocket_with_revocation(self):
        page = await self.module._get_page()
        self.assertEqual(page["id"], "A123")
        tab = self.module.PrivateDiscordTab(page)
        await tab.open_websocket()
        try:
            result = await tab._send_devtools_cmd({"method": "Runtime.evaluate", "params": {"expression": "1+1"}})
            self.assertTrue(result["result"]["fixture"])
            self.owned = False
            with self.assertRaises(RuntimeError):
                await tab._send_devtools_cmd({"method": "Page.reload"})
            self.assertEqual(len(self.commands), 1)
        finally:
            await tab.close_websocket()

    async def test_no_http_when_foreign_owner_and_no_redirect(self):
        self.owned = False
        with self.assertRaises(RuntimeError):
            await self.module._get_page()
        self.assertEqual(self.requests, [])
        self.owned = True; self.redirect = True
        with self.assertRaises(RuntimeError):
            await self.module._get_page()
        self.assertEqual(self.requests, ["/json"])

    async def test_foreign_page_never_becomes_injection_target(self):
        self.targets[0]["url"] = "https://example.org/"
        self.assertIsNone(await self.module._get_page())
        self.assertEqual(self.commands, [])


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_websocket_rejects_missing_token_and_foreign_origin(self):
        async def socket(request):
            if not local_bridge.authorized(request):
                return web.Response(status=403)
            websocket = web.WebSocketResponse()
            await websocket.prepare(request)
            await websocket.send_json({"ok": True})
            await websocket.close()
            return websocket
        app = web.Application(); app.router.add_get("/socket", socket)
        runner = web.AppRunner(app, access_log=None); await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
        url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1]) + "/socket"
        try:
            async with ClientSession() as client:
                for token, origin in (("", "https://discord.com"), ("wrong", "https://discord.com"),
                                      (local_bridge.TOKEN, "https://discord.com.attacker.invalid"),
                                      (local_bridge.TOKEN, "null")):
                    async with client.get(url, params={"bridge": token}, headers={"Origin": origin}) as response:
                        self.assertEqual(response.status, 403)
                async with client.ws_connect(url + "?bridge=" + local_bridge.TOKEN, origin="https://discord.com") as websocket:
                    self.assertEqual(await websocket.receive_json(), {"ok": True})
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    unittest.main()
