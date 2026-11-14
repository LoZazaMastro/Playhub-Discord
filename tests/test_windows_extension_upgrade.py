"""Synthetic profiles exercise the real migration; no processes are started."""
import asyncio
import hashlib
import importlib.util
import logging
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

DEFAULTS = Path(__file__).resolve().parents[1] / 'defaults'


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEFAULTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtensionUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.host = load('host')
        with patch.dict(sys.modules, {
            'host': self.host, 'windows_identity': load('windows_identity'),
            'decky': types.SimpleNamespace(logger=logging.getLogger(__name__)),
        }):
            self.win = load('vesktop_win')
        self.source = self.base / 'plugin/runtime/vencord'
        self.source.mkdir(parents=True)
        self.profile = self.base / 'profile'
        (self.profile / 'vesktop').mkdir(parents=True)
        (self.profile / 'vesktop/state.json').write_text('{}')
        self.files = self.profile / 'vesktop/sessionData/vencordFiles'
        self.files.mkdir(parents=True)
        current, legacy = {}, {}
        for name in self.win.VENCORD_FILES:
            new, old = ('new-' + name).encode(), ('old-' + name).encode()
            (self.source / name).write_bytes(new)
            (self.files / name).write_bytes(old)
            current[name] = hashlib.sha256(new).hexdigest()
            legacy[name] = hashlib.sha256(old).hexdigest()
        for name, value in (
            ('__file__', str(self.base / 'plugin/defaults/vesktop_win.py')),
            ('VENCORD_FILES', current), ('LEGACY_VENCORD_FILES', legacy),
        ):
            replacement = patch.object(self.win, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.target = self.files / next(iter(current))

    def test_exact_legacy_assets_update_without_changing_session_or_custom_files(self):
        self.target.write_bytes(b'custom extension')
        session = self.profile / 'vesktop/sessionData/Cookies'
        session.write_bytes(b'synthetic-session')
        self.assertTrue(self.win._managed_extension_upgrade_needed(self.profile))
        self.win._seed_vencord(self.profile)
        self.assertEqual(self.target.read_bytes(), b'custom extension')
        self.assertEqual(session.read_bytes(), b'synthetic-session')
        for name in self.win.VENCORD_FILES:
            if name != self.target.name:
                self.assertEqual((self.files / name).read_bytes(), (self.source / name).read_bytes())
        self.assertFalse(self.win._managed_extension_upgrade_needed(self.profile))

    def test_custom_directory_is_not_migrated_or_marked_for_restart(self):
        (self.profile / 'vesktop/state.json').write_text('{"vencordDir":"C:/custom"}')
        before = {path.name: path.read_bytes() for path in self.files.iterdir()}
        self.assertFalse(self.win._managed_extension_upgrade_needed(self.profile))
        self.win._seed_vencord(self.profile)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.files.iterdir()})

    def test_custom_target_replacing_legacy_during_copy_is_preserved(self):
        original = self.win.shutil.copyfileobj

        def copy(source, output, *args, **kwargs):
            result = original(source, output, *args, **kwargs)
            if Path(source.name).name == self.target.name:
                self.target.write_bytes(b'custom installed during copy')
            return result

        with patch.object(self.win.shutil, 'copyfileobj', side_effect=copy):
            self.win._seed_vencord(self.profile)
        self.assertEqual(self.target.read_bytes(), b'custom installed during copy')
        self.assertEqual(list(self.files.glob('.discord-extension-*.tmp')), [])

    def test_interrupted_new_asset_copy_leaves_no_partial_and_can_retry(self):
        self.target.unlink()

        def fail_copy(source, output, *args, **kwargs):
            output.write(b'partial')
            raise OSError('synthetic interrupted copy')

        with patch.object(self.win.shutil, 'copyfileobj', side_effect=fail_copy):
            with self.assertRaises(OSError):
                self.win._seed_vencord(self.profile)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.files.glob('.discord-extension-*.tmp')), [])
        self.win._seed_vencord(self.profile)
        self.assertEqual(self.target.read_bytes(), (self.source / self.target.name).read_bytes())

    def test_new_custom_target_created_during_copy_is_not_replaced(self):
        self.target.unlink()
        original = self.win.shutil.copyfileobj

        def copy(source, output, *args, **kwargs):
            result = original(source, output, *args, **kwargs)
            if Path(source.name).name == self.target.name:
                self.target.write_bytes(b'new custom extension')
            return result

        with patch.object(self.win.shutil, 'copyfileobj', side_effect=copy):
            self.win._seed_vencord(self.profile)
        self.assertEqual(self.target.read_bytes(), b'new custom extension')
        self.assertEqual(list(self.files.glob('.discord-extension-*.tmp')), [])

    def test_interrupted_upgrade_preserves_legacy_and_removes_temporary_file(self):
        before = self.target.read_bytes()

        def fail_copy(source, output, *args, **kwargs):
            output.write(b'partial')
            raise OSError('synthetic interrupted copy')

        with patch.object(self.win.shutil, 'copyfileobj', side_effect=fail_copy):
            with self.assertRaises(OSError):
                self.win._seed_vencord(self.profile)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(list(self.files.glob('.discord-extension-*.tmp')), [])

    def test_failed_private_restart_never_spawns_or_migrates(self):
        before = {path.name: path.read_bytes() for path in self.files.iterdir()}
        with patch.object(self.win, 'installed', return_value=True), \
             patch.object(self.win, 'steam_account_id', return_value='fixture'), \
             patch.object(self.win, 'running_account', return_value='fixture'), \
             patch.object(self.win, 'is_running', return_value=True), \
             patch.object(self.win, 'profile_dir', return_value=self.profile), \
             patch.object(self.win, 'stop', new=AsyncMock(return_value=False)) as stop, \
             patch.object(self.win, '_spawn') as spawn:
            self.assertFalse(asyncio.run(self.win.launch(AsyncMock(return_value=False))))
            stop.assert_awaited_once()
            spawn.assert_not_called()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.files.iterdir()})

    def test_running_custom_profile_does_not_trigger_security_restart(self):
        (self.profile / 'vesktop/state.json').write_text('{"vencordDir":"C:/custom"}')
        with patch.object(self.win, 'installed', return_value=True), \
             patch.object(self.win, 'steam_account_id', return_value='fixture'), \
             patch.object(self.win, 'running_account', return_value='fixture'), \
             patch.object(self.win, 'is_running', return_value=True), \
             patch.object(self.win, 'profile_dir', return_value=self.profile), \
             patch.object(self.win, 'owns_cdp', return_value=True), \
             patch.object(self.win, 'stop', new=AsyncMock()) as stop, \
             patch.object(self.win, '_spawn') as spawn:
            self.assertTrue(asyncio.run(self.win.launch(AsyncMock(return_value=True))))
            stop.assert_not_awaited()
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
