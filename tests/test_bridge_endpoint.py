"""Owned loopback fixtures; never load a Discord profile or launch a client."""
import ast
import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, ClientConnectorError, web
import aiohttp_cors

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "defaults"))
import local_bridge


class EndpointTests(unittest.TestCase):
    def test_windows_never_falls_back_to_reserved_fixed_port(self):
        for port in (None, 0, -1, 65536, True, "55000", 1.5):
            with self.assertRaises(RuntimeError):
                local_bridge.client_bootstrap("windows", port)
        self.assertEqual(local_bridge.endpoint_port(None, False), 65123)
        self.assertIn("STEAMCORD_BRIDGE_PORT = 55000", local_bridge.client_bootstrap("windows", 55000))
        self.assertEqual(local_bridge.http_url("/clip?t=fixture", 55000, True), "http://127.0.0.1:55000/clip?t=fixture")
        for path in ("//foreign.invalid/clip", "https://foreign.invalid/", None):
            with self.assertRaises(ValueError):
                local_bridge.http_url(path, 55000, True)


class LoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def make_bridge(self):
        bridge = local_bridge.BridgeServer()
        app = web.Application()

        async def socket(request):
            if not local_bridge.authorized(request):
                return web.Response(status=403)
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            bridge.clients.add(ws)
            try:
                await ws.send_json({"fixture": True})
                async for _ in ws:
                    pass
            finally:
                bridge.clients.discard(ws)
            return ws

        app.router.add_get("/socket", socket)
        await bridge.start(app, windows=True)
        return bridge

    async def test_real_os_selected_loopback_port_and_authenticated_websocket(self):
        bridge = await self.make_bridge()
        port = bridge.port
        try:
            self.assertGreater(port, 0)
            self.assertEqual(bridge.runner.addresses, [("127.0.0.1", port)])
            base = local_bridge.http_url("/socket", port, True)
            async with ClientSession() as client:
                async with client.get(base) as response:
                    self.assertEqual(response.status, 403)
                async with client.get(base + "?bridge=" + local_bridge.TOKEN,
                                      headers={"Origin": "https://foreign.invalid"}) as response:
                    self.assertEqual(response.status, 403)
                async with client.ws_connect(base + "?bridge=" + local_bridge.TOKEN,
                                             origin="https://discord.com") as socket:
                    self.assertEqual(await socket.receive_json(), {"fixture": True})
                    await asyncio.wait_for(bridge.close(), 4)
                    self.assertIn((await socket.receive()).type, (web.WSMsgType.CLOSE, web.WSMsgType.CLOSED))
                with self.assertRaises(ClientConnectorError):
                    await client.get(base)
            self.assertIsNone(bridge.port)
        finally:
            await bridge.close()

    async def test_two_owned_listeners_negotiate_independent_ports(self):
        first, second = await self.make_bridge(), await self.make_bridge()
        try:
            self.assertNotEqual(first.port, second.port)
            second_port = second.port
            await first.close()
            self.assertEqual(second.port, second_port)
        finally:
            await first.close()
            await second.close()

    async def test_win10013_cleans_runner_and_does_not_publish_an_endpoint(self):
        runner = types.SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock())
        site = types.SimpleNamespace(start=AsyncMock(side_effect=PermissionError(13, "fixture WinError 10013")), stop=AsyncMock())
        bridge = local_bridge.BridgeServer()
        with patch.object(local_bridge, "AppRunner", return_value=runner), patch.object(local_bridge, "TCPSite", return_value=site) as factory:
            with self.assertRaises(PermissionError):
                await bridge.start(object(), True)
        factory.assert_called_once_with(runner, "127.0.0.1", 0)
        site.stop.assert_awaited_once()
        runner.cleanup.assert_awaited_once()
        self.assertIsNone(bridge.port)
        self.assertIsNone(bridge.runner)

    async def test_cancelled_startup_cleans_before_returning_cancellation(self):
        entered = asyncio.Event()
        async def setup():
            entered.set()
            await asyncio.Event().wait()
        runner = types.SimpleNamespace(setup=setup, cleanup=AsyncMock())
        bridge = local_bridge.BridgeServer()
        with patch.object(local_bridge, "AppRunner", return_value=runner):
            task = asyncio.create_task(bridge.start(object(), True))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        runner.cleanup.assert_awaited_once()
        self.assertIsNone(bridge.port)

    async def test_linux_keeps_its_existing_binding_and_port(self):
        runner = types.SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock(), addresses=[("0.0.0.0", 65123)])
        site = types.SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
        bridge = local_bridge.BridgeServer()
        with patch.object(local_bridge, "AppRunner", return_value=runner), patch.object(local_bridge, "TCPSite", return_value=site) as factory:
            try:
                self.assertEqual(await bridge.start(object(), False), 65123)
                factory.assert_called_once_with(runner, "0.0.0.0", 65123)
            finally:
                await bridge.close()

    async def test_unexpected_listener_address_is_rejected_and_closed(self):
        runner = types.SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock(), addresses=[("0.0.0.0", 55000)])
        site = types.SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
        bridge = local_bridge.BridgeServer()
        with patch.object(local_bridge, "AppRunner", return_value=runner), patch.object(local_bridge, "TCPSite", return_value=site):
            with self.assertRaises(RuntimeError):
                await bridge.start(object(), True)
        runner.cleanup.assert_awaited_once()
        self.assertIsNone(bridge.port)


class StartupOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_binds_before_any_discord_start_and_closes_on_failure(self):
        plugin = next(node for node in ast.parse((ROOT / "main.py").read_text(encoding="utf-8")).body
                      if isinstance(node, ast.ClassDef) and node.name == "Plugin")
        main = next(node for node in plugin.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_main")
        body = ast.Module(body=[ast.ClassDef(name="Fixture", bases=[], keywords=[], body=[main], decorator_list=[])], type_ignores=[])
        bridge = types.SimpleNamespace(close=AsyncMock(), port=None)
        namespace = {"local_bridge": types.SimpleNamespace(BridgeServer=lambda: bridge), "host": types.SimpleNamespace(WINDOWS=True), "current_task": asyncio.current_task,
                     "Application": web.Application, "aiohttp_cors": aiohttp_cors}
        exec(compile(ast.fix_missing_locations(body), "main-startup-fixture", "exec"), namespace)
        fixture = namespace["Fixture"]
        events = []
        async def start():
            events.append("bound")
            bridge.port = 55000
        async def run():
            self.assertEqual(bridge.port, 55000)
            events.append("client")
            raise RuntimeError("owned fixture failure after initialization")
        fixture._start_local_bridge = start
        fixture._run_main = run
        with self.assertRaises(RuntimeError):
            await fixture._main()
        self.assertEqual(events, ["bound", "client"])
        bridge.close.assert_awaited_once()

    def retry_fixture(self, port=55000, enabled=True):
        plugin = next(node for node in ast.parse((ROOT / "main.py").read_text(encoding="utf-8")).body
                      if isinstance(node, ast.ClassDef) and node.name == "Plugin")
        retry = next(node for node in plugin.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "retry_connection")
        body = ast.Module(body=[ast.ClassDef(name="Fixture", bases=[], keywords=[], body=[retry], decorator_list=[])], type_ignores=[])
        namespace = {"Lock": asyncio.Lock, "wait_for": asyncio.wait_for,
                     "create_task": asyncio.create_task, "discord_runtime": types.SimpleNamespace(enabled=enabled),
                     "_REHANDSHAKE_JS": "owned-handshake", "logger": types.SimpleNamespace(warning=lambda *args: None)}
        exec(compile(ast.fix_missing_locations(body), "main-retry-fixture", "exec"), namespace)
        fixture = namespace["Fixture"]
        fixture._retry_lock = None
        fixture._bridge = types.SimpleNamespace(port=port)
        fixture._bridge_failed = port is None
        fixture._main_task = None
        fixture.discord_tab = types.SimpleNamespace(evaluate=AsyncMock())
        return fixture

    async def test_retry_reuses_saved_session_and_never_reloads_or_logs_out(self):
        fixture = self.retry_fixture()
        account = types.SimpleNamespace(loaded=True, logged_in=True, me=object())
        fixture.evt_handler = account
        tab = fixture.discord_tab
        self.assertEqual(await fixture.retry_connection(), {"ok": True, "status": "connecting"})
        self.assertIs(fixture.discord_tab, tab)
        self.assertIs(fixture.evt_handler, account)
        self.assertTrue(account.logged_in)
        self.assertEqual(tab.evaluate.await_count, 2)
        scripts = [args.args[0] for args in tab.evaluate.await_args_list]
        self.assertIn("__sc_reconnectBridge", scripts[0])
        self.assertEqual(scripts[1], "owned-handshake")
        self.assertFalse(any("reload" in script or "logout" in script or "removeItem" in script for script in scripts))

    async def test_failed_bind_can_be_retried_once_before_any_client_work(self):
        fixture = self.retry_fixture(port=None)
        started, finish = asyncio.Event(), asyncio.Event()
        attempts = []
        async def main():
            attempts.append("bind")
            started.set()
            await finish.wait()
        fixture._main = main
        first = await fixture.retry_connection()
        await started.wait()
        second = await fixture.retry_connection()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(attempts, ["bind"])
        fixture.discord_tab.evaluate.assert_not_awaited()
        finish.set()
        await fixture._main_task

    async def test_paused_runtime_and_failed_client_call_do_not_claim_success(self):
        fixture = self.retry_fixture(enabled=False)
        self.assertFalse((await fixture.retry_connection())["ok"])
        fixture.discord_tab.evaluate.assert_not_awaited()
        fixture = self.retry_fixture()
        fixture.discord_tab.evaluate.side_effect = RuntimeError("owned fixture disconnect")
        self.assertFalse((await fixture.retry_connection())["ok"])


if __name__ == "__main__":
    unittest.main()
