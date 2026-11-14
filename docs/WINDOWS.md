# Discord for Playhub on Windows

This is Playhub's Windows fork of Steamcord 1.45.1, maintained by LoZazaMastro.
The plugin and its installation folder are named **Discord**. Windows x64
with Steam Big Picture is the packaged target. See the [current README](../README.md)
for the fork's features and verification status.

## Installing

1. Install [Playhub](https://github.com/LoZazaMastro/Playhub) and use Steam Big Picture.
2. Install **Discord** from Playhub's catalog, or install
   `Discord_Installer-1.0.1.zip` from [this fork's releases](https://github.com/LoZazaMastro/Playhub-Discord/releases)
   through Playhub's plugin installer.
3. Open **Discord** from the Quick Access Menu. On first start it verifies and
   unpacks the private Vesktop runtime already included in the ZIP, then shows
   the QR code to sign in. No separate Vesktop installation or runtime download
   is required; Discord's service still needs an internet connection.

Start Decky from your Windows desktop session. Started
from a remote shell, Windows denies Discord access to the microphone.

## Your own Discord stays untouched

Discord uses a private, portable Vesktop from the official Vencord release,
bundled in the plugin ZIP and checked against a pinned SHA-256. Nothing is installed
into Windows, no administrator prompt is needed, and it is not added to
Windows startup. A Discord or Vesktop you already use is never stopped,
reused or imported.

Each Steam account gets its own Discord login, as on Linux.

## Windows features

These controls are provided by the Windows client. Live voice, calls and screen
sharing still need a hands-on test; see the [verification status](../README.md#verification-status).

- Voice chat: microphone, hearing others, mute and deafen
- Private messages, notifications and game activity (Rich Presence)
- Go Live with your screen and its sound, without echoing the call
- Watching other people's streams, with a preview of your own stream in the
  Quick Access Menu and the expanded view

## Linux-only features

These depend on Linux system components and are hidden on Windows: audio
device pickers and the game/voice balance (Windows' own sound settings
apply), sharing game audio as a separate source, the virtual camera, the
in-game voice and POV overlays, keeping the screen awake, and the
controller push-to-talk/mute shortcut.

## Reporting a problem

Logs are in `%USERPROFILE%\homebrew\logs\Discord`. Please include your
Windows and Playhub versions and the step that fails.
Never post tokens, passwords or QR codes, and check logs for personal
information before attaching them.

The Windows port was made possible by
[@SilvertongueRED](https://github.com/SilvertongueRED)'s
[fork](https://github.com/SilvertongueRED/Steamcord-for-Windows), which showed
the way.
