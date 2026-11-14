"""Vesktop on Windows: Steamcord's own private copy.

On Linux Steamcord runs the user's flatpak or native Vesktop under a systemd
unit (vesktop.py). Windows has neither, so Steamcord keeps its own copy:

* a pinned private runtime derived from official Vesktop (localized arRPC scan guard),
  pinned and checked against its SHA-256, unpacked into Steamcord's data folder
  under homebrew. Nothing is installed into Windows, no administrator prompt,
  and a Vesktop the user runs on the desktop is never touched;
* one data folder per Steam account (VENCORD_USER_DATA_DIR + --user-data-dir),
  so each Steam account keeps its own Discord login, as on Linux;
* "our" Vesktop is every process whose executable lives inside that private
  copy, which is exact: the user's own Vesktop lives somewhere else.

Importable on any OS (the tests do); only the calls that start or inspect
Windows processes need Windows.
"""

import hashlib
import json
import os
import ntpath
import stat
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from asyncio import get_running_loop, sleep
from pathlib import Path

from decky import logger  # type: ignore

import host
import windows_identity

VERSION = "1.6.8"
X64_RUNTIME_VERSION = "1.6.8-playhub.1"
# Pinned private x64 derivative; ARM64 retains its official release pin.
BUILDS = {
    "x64": ("Vesktop-1.6.8-playhub.1-win.zip",
            "97829d8c2d317db0ba3ac965e721f24846b027fcdec1230e141a1c57a370707f"),
    "arm64": ("Vesktop-1.6.8-arm64-win.zip",
              "09a29c4872a3f92da056d85a71d91c66b9751e6dc519c734f970d79c12411a5e"),
}
VENCORD_FILES = {
    "vencordDesktopMain.js": "247b1f60e85ed59f272c0637d2d33437c780009430461e4b80d8f117ffd3799f",
    "vencordDesktopPreload.js": "0777509a732afc2f9d316468fd90900b1ff5ba2844156747d5e9707d221f78f7",
    "vencordDesktopRenderer.css": "6ede6d03ff7d6e3200c5460b455b3c81b2aeecf3ce53ea465782392b1f467cbc",
    "vencordDesktopRenderer.js": "f4fea8ff7365504000c7949aea79b147bcfffd0d603ed1696d9c3f1ee85e7eec"
}
LEGACY_VENCORD_FILES = {
    "vencordDesktopMain.js": "f5f70942ad798f56097ab4c95b2090b058b9eb8f99d5366468ae083a48edd8cc",
    "vencordDesktopPreload.js": "0777509a732afc2f9d316468fd90900b1ff5ba2844156747d5e9707d221f78f7",
    "vencordDesktopRenderer.js": "391b3709f25ac7642dc5c32e1638c2e55a79d2806d84cb6ddad095686df54bc7",
    "vencordDesktopRenderer.css": "f2dc03726e81af8ef67b017f6e441432580c088758a4dcd8c78b07686f650254"
}
RELEASE_URL = "https://github.com/Vencord/Vesktop/releases/download/v{version}/{asset}"
CDP_PORT = 9223  # same debugging port as the Linux unit
_STEAM_EPOCH = 76561197960265728

# Windows process creation flags.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_SW_SHOWMINNOACTIVE = 7


def _arch():
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def root():
    return Path(host.data_dir()) / "vesktop"


def install_dir():
    version = X64_RUNTIME_VERSION if _arch() == "x64" else VERSION
    return root() / f"{version}-{_arch()}"


def exe():
    return install_dir() / "Vesktop.exe"


def installed():
    # The marker is written last: a copy cut short by a crash is not "installed".
    return exe().is_file() and (install_dir() / ".steamcord-complete").is_file()


# ── installing the private copy ─────────────────────────────────────────────
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _no_links(path):
    for entry in (Path(path).absolute(), *Path(path).absolute().parents):
        try:
            attributes = entry.lstat()
            if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked runtime directory refused")
        except FileNotFoundError:
            pass


def _managed_extension_upgrade_needed(profile):
    state_path=profile/'vesktop/state.json'
    _no_links(state_path)
    if not state_path.is_file() or json.loads(state_path.read_text('utf-8')).get('vencordDir'):
        return False
    destination=profile/'vesktop/sessionData/vencordFiles'
    _no_links(destination)
    for name,expected in VENCORD_FILES.items():
        target=destination/name
        _no_links(target)
        if target.is_file() and expected!=LEGACY_VENCORD_FILES.get(name) and _sha256(target)==LEGACY_VENCORD_FILES.get(name):
            return True
    return False


def _seed_vencord(profile):
    source = Path(__file__).resolve().parent.parent / "runtime" / "vencord"
    state = json.loads((profile / "vesktop" / "state.json").read_text(encoding="utf-8"))
    # Vesktop's supported custom installation belongs to the existing profile.
    # Never replace it or adopt an extension from another application.
    if state.get("vencordDir"):
        return
    destination = profile / "vesktop" / "sessionData" / "vencordFiles"
    _no_links(destination)
    for name, expected in VENCORD_FILES.items():
        if _sha256(source / name) != expected:
            raise ValueError("Packaged Discord extension checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in VENCORD_FILES.items():
        target = destination / name
        _no_links(target)
        # Upgrade only our exact previously bundled build. A custom extension
        # remains owned by the user, including Vesktop's custom vencordDir.
        old_managed = target.is_file() and _sha256(target) == LEGACY_VENCORD_FILES.get(name)
        if old_managed and expected != LEGACY_VENCORD_FILES.get(name):
            handle, filename = tempfile.mkstemp(prefix='.discord-extension-', suffix='.tmp', dir=destination)
            temporary = Path(filename)
            try:
                with (source / name).open('rb') as original, os.fdopen(handle, 'wb') as output:
                    shutil.copyfileobj(original, output)
                if _sha256(temporary) != expected:
                    raise ValueError('Discord extension update checksum mismatch')
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        elif not target.exists():
            with (source / name).open("rb") as original, target.open("xb") as output:
                shutil.copyfileobj(original, output)
    try:
        with (destination / "package.json").open("x", encoding="utf-8") as output:
            output.write("{}")
    except FileExistsError:
        pass
    settings = profile / "vesktop" / "settings"
    _no_links(settings)
    settings.mkdir(exist_ok=True)
    try:
        with (settings / "settings.json").open("x", encoding="utf-8") as output:
            json.dump({"autoUpdate": False, "autoUpdateNotification": False}, output)
    except FileExistsError:
        pass


def _unpack(archive, target):
    """Extract into a sibling folder, then rename it into place (all or nothing).
    The official zip may or may not wrap everything in one top-level folder."""
    target = Path(target)
    _no_links(target)
    staging = Path(tempfile.mkdtemp(prefix=".unpack-", dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as z:
            if len(z.infolist()) > 512 or sum(info.file_size for info in z.infolist()) > 600 * 1024 * 1024:
                raise ValueError("Vesktop archive exceeds the runtime size limit")
            for info in z.infolist():
                member = info.filename
                # ZIP uses '/', but Windows also interprets backslashes, drives
                # and alternate data streams. Validate on both test hosts.
                parts = member.replace("\\", "/").split("/")
                if (ntpath.splitdrive(member)[0] or member.startswith(("/", "\\"))
                        or any(p == ".." or ":" in p for p in parts)
                        or stat.S_ISLNK(info.external_attr >> 16)):
                    raise ValueError(f"unsafe path in Vesktop archive: {member}")
                resolved = (staging / member).resolve()
                if not resolved.is_relative_to(staging.resolve()):
                    raise ValueError(f"unsafe path in Vesktop archive: {member}")
            z.extractall(staging)
        top = staging
        entries = list(staging.iterdir())
        if not (staging / "Vesktop.exe").is_file() and len(entries) == 1 and entries[0].is_dir():
            top = entries[0]
        if not (top / "Vesktop.exe").is_file():
            raise ValueError("Vesktop.exe missing from the archive")
        (top / ".steamcord-complete").write_text(VERSION, encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        top.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _checked_unpack(archive, target, expected):
    if _sha256(archive) != expected:
        raise ValueError("checksum mismatch for Vesktop archive")
    _unpack(archive, target)


def _remove_old_copies():
    """Older versions of OUR copy only (never the profiles, never anything else)."""
    keep = install_dir().name
    for entry in root().iterdir():
        if entry.is_dir() and entry.name != keep and re.fullmatch(r"\d+(\.\d+)+(?:-playhub\.\d+)?-(x64|arm64)", entry.name):
            if host.pids_under(entry):
                continue  # still running (a plugin update mid-call): next start removes it
            shutil.rmtree(entry, ignore_errors=True)


async def install():
    """Prepare the pinned runtime included in the Playhub package, without a download."""
    if installed():
        return
    asset, expected = BUILDS[_arch()]
    archive = Path(__file__).resolve().parent.parent / "runtime" / asset
    root().mkdir(parents=True, exist_ok=True)
    try:
        if not archive.is_file():
            raise FileNotFoundError("The packaged Windows runtime is missing")
        loop = get_running_loop()
        await loop.run_in_executor(None, _checked_unpack, archive, install_dir(), expected)
        logger.info(f"[win-vesktop] Vesktop {VERSION} ready")
        _remove_old_copies()
    except Exception as e:
        logger.warning(f"[win-vesktop] could not set up Vesktop {VERSION}: {e!r}")


# ── one Discord login per Steam account ─────────────────────────────────────
def steam_account_id():
    """32-bit AccountID of the signed-in Steam user, or "default".

    Steam publishes the active user under HKCU\\Software\\Valve\\Steam\\ActiveProcess
    while it runs; loginusers.vdf (auto-login, then the newest session) covers
    the moment Steam has not written it yet."""
    if host.WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as k:
                active = int(winreg.QueryValueEx(k, "ActiveUser")[0])
            if active:
                return str(active)
        except (OSError, ValueError):
            pass
    steam = host.steam_dir()
    if not steam:
        return "default"
    try:
        data = (Path(steam) / "config" / "loginusers.vdf").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "default"
    auto, newest, newest_time = None, None, -1
    for sid, block in re.findall(r'"(\d{17})"\s*\{(.*?)\}', data, re.S):
        if auto is None and re.search(r'"(?:AutoLogin|MostRecent)"\s+"1"', block):
            auto = sid
        stamp = re.search(r'"Timestamp"\s+"(\d+)"', block)
        if stamp and int(stamp.group(1)) > newest_time:
            newest_time, newest = int(stamp.group(1)), sid
    sid = auto or newest
    return str(int(sid) - _STEAM_EPOCH) if sid else "default"


def profile_dir(account):
    safe = re.sub(r"[^0-9A-Za-z_.-]", "_", account) or "default"
    path = Path(host.settings_dir()) / "vesktop-profiles" / safe
    _no_links(path)
    path.mkdir(parents=True, exist_ok=True)
    vesktop = path / "vesktop"
    vesktop.mkdir(exist_ok=True)
    # Vesktop's first-run tour blocks Discord from loading. Initialise only
    # this new private profile, without importing another Vencord installation
    # or registering an application at Windows startup.
    for name, data in (("state.json", {"firstLaunch": False,
                                      "updater": {"snoozeUntil": 8640000000000000}}),
                       ("settings.json", {"discordBranch": "stable", "minimizeToTray": True,
                                          "autoStartMinimized": True})):
        try:
            with (vesktop / name).open("x", encoding="utf-8") as f:
                json.dump(data, f)
        except FileExistsError:
            pass
    return path


def _state_file():
    return Path(host.settings_dir()) / "vesktop-profiles" / "current.json"


def running_account():
    try:
        return json.loads(_state_file().read_text(encoding="utf-8")).get("account", "")
    except (OSError, ValueError):
        return ""


def _remember_account(account, identity=None):
    try:
        _state_file().parent.mkdir(parents=True, exist_ok=True)
        _state_file().write_text(json.dumps({"account": account, "owner": identity}), encoding="utf-8")
    except OSError as e:
        logger.warning(f"[multisession] cannot record account: {e!r}")


# ── our Vesktop's processes ─────────────────────────────────────────────────
def our_pids():
    return host.pids_under(root()) if root().is_dir() else []


def is_running():
    return bool(our_pids())


def owns_cdp():
    try:
        record = json.loads(_state_file().read_text(encoding="utf-8"))
        identity = record.get("owner")
        return (record.get("account") == steam_account_id() and windows_identity.matches(identity, exe())
                and host.listening_pids(CDP_PORT) == {identity["pid"]})
    except (OSError, ValueError, TypeError, AttributeError):
        return False


async def stop(tag):
    """Stop every process of our copy. True once none is left."""
    loop = get_running_loop()
    for pid in our_pids():
        await loop.run_in_executor(None, host.kill_tree, pid)
    for _ in range(10):
        if not is_running():
            return True
        await sleep(1)
    logger.warning(f"{tag} Vesktop is still running after taskkill")
    return False


def _command(account, extra_flags=()):
    profile = profile_dir(account)
    _seed_vencord(profile)
    return [
        str(exe()),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        # Chromium's own profile, and with it the single-instance lock: without
        # it, a Vesktop the user already runs would swallow our launch.
        f"--user-data-dir={profile / 'chromium'}",
        # Keep Discord's timers (gateway heartbeat) running while minimised.
        "--disable-background-timer-throttling",
        "--start-minimized",
        *extra_flags,
    ], profile


def _environment(profile):
    env = dict(os.environ)
    # Variables Decky's embedded Python sets for itself; an Electron child must not inherit them.
    for name in ("ELECTRON_RUN_AS_NODE", "PYTHONHOME", "PYTHONPATH", "PYTHONSAFEPATH",
                 "PYTHONNOUSERSITE", "PYTHONUTF8"):
        env.pop(name, None)
    # Vesktop keeps the Discord session, Vencord settings and themes here.
    env["VENCORD_USER_DATA_DIR"] = str(profile / "vesktop")
    return env


def _spawn(command, env):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = _SW_SHOWMINNOACTIVE  # minimised, never takes focus from Big Picture
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=env, startupinfo=startup, close_fds=True)
    flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    try:
        # Outlive a reload of the plugin, like the systemd unit does on Linux.
        return subprocess.Popen(command, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **options)
    except OSError:
        return subprocess.Popen(command, creationflags=flags, **options)


async def launch(is_up):
    """Start our Vesktop for the signed-in Steam account; True once CDP answers.
    `is_up` is vesktop.is_up, passed in to avoid an import cycle."""
    if not installed():
        logger.warning("[win-vesktop] Vesktop is not set up")
        return False
    account = steam_account_id()
    if is_running():
        if running_account() == account and _managed_extension_upgrade_needed(profile_dir(account)):
            logger.info('[win-vesktop] applying the bundled Discord extension update')
            if not await stop('[win-vesktop]'):
                return False
        elif running_account() == account:
            for _ in range(15):
                if owns_cdp() and await is_up():
                    return True
                await sleep(1)
            logger.info("[recover] our Vesktop runs but its debugging port stays closed: restarting it")
        elif is_running():
            logger.info("[multisession] switching the private Discord profile")
        if is_running():
            await stop("[win-vesktop]")
    if host.listening_pids(CDP_PORT) or await is_up():
        logger.warning(f"[win-vesktop] port {CDP_PORT} is already used by another program")
        return False
    # Proxy (Settings ▸ Proxy): same Chromium flags as on Linux. Windows has no
    # systemd unit, but the local bridge is plain asyncio and runs here too.
    proxy_flags = []
    try:
        from discord_client import netproxy
        proxy_flags = await netproxy.chromium_flags_for_launch()
        if proxy_flags:
            logger.info(f"[win-vesktop] launching through {netproxy.describe()}")
    except Exception as e:
        logger.warning(f"[proxy] proxy flags unavailable, launching without: {e!r}")
    command, profile = _command(account, proxy_flags)
    logger.info(f"[win-vesktop] starting the private Vesktop {VERSION} client")
    try:
        process = await get_running_loop().run_in_executor(None, _spawn, command, _environment(profile))
    except OSError as e:
        logger.warning(f"[win-vesktop] cannot start Vesktop: {e!r}")
        return False
    identity = windows_identity.capture(process.pid, exe(), os.getpid())
    if identity is None:
        logger.warning("[win-vesktop] private client identity could not be verified")
        return False
    _remember_account(account, identity)
    for second in range(60):
        if owns_cdp() and await is_up():
            logger.info(f"[launchdiag] Vesktop CDP {CDP_PORT} up after ~{second}s")
            return True
        if process.poll() is not None and not is_running():
            logger.warning(f"[launchdiag] Vesktop exited ({process.returncode}) before CDP opened")
            return False
        await sleep(1)
    logger.warning(f"[launchdiag] Vesktop started but CDP {CDP_PORT} never opened after 60s")
    return False
