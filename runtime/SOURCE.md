# Runtime source and build notes

The release package carries a private runtime derived from the official Vesktop
Windows x64 portable build and the four official Vencord desktop files. The
Electron executable is unchanged; two files inside the Vesktop ASAR (arRPC
worker and its source map) have a localized process-scan error guard. Only a
new, private profile is initialized: the
first-run tour is skipped, Vencord's automatic updates are off, and Vesktop's
update prompt is snoozed. Existing profiles and extension files are preserved.
Runtime updates are delivered through the Playhub plugin package.

## Vesktop 1.6.8

- Source: https://github.com/Vencord/Vesktop/tree/4bf170e0acaf6488d3b97b19dba53bbc3c1d655d
- Included archive: `sources/Vesktop-1.6.8-source.tar.gz`.
- Official Windows portable archive: https://github.com/Vencord/Vesktop/releases/download/v1.6.8/Vesktop-1.6.8-win.zip
- SHA-256: `8ffa8d3778c287551ee0b302b3396acd2fac45931282071048bb881b67c88286`.
- Upstream package manager: `pnpm@11.9.0`.
- Build entry point: `pnpm install --frozen-lockfile`, then `pnpm package --win --x64`.
  See the included `scripts`, `electron-builder` configuration and native
  `packages/libvesktop` source for platform prerequisites.

## Vencord

- Source: https://github.com/Vendicated/Vencord/tree/d07030c0968e31e41caa0c35fda0ef8ae63a079e
- Included archive: `sources/Vencord-source.tar.gz`.
- Upstream package manager: `pnpm@12.15.0`.
- Build entry point: `pnpm install --frozen-lockfile`, then `pnpm buildStandalone`.
  Set `VENCORD_HASH=d07030c` when building from the source tar without Git.
- `vencord/manifest.json` records every original asset URL, byte count and
  SHA-256. The binary header, not a subsequently moved devbuild tag, identifies
  the exact source commit included here.

The runtime package includes all four files in the private profile's
`vesktop/sessionData/vencordFiles` before first launch. It does not need to
download another executable or extension to start. Connecting to Discord
still requires an internet connection and the user's own sign-in.

## arRPC and dependency notices

arRPC's exact source is included in `sources/arrpc-source.tar.gz`. The
Vesktop lock pins that Git commit. The corresponding archive and all collected
dependency tarballs were verified against the lock's SHA-512 integrity.
`licenses/PROVENANCE.json` and `licenses/VENCORD-DEPENDENCY-PROVENANCE.json`
record their individual provenance. The `lazy-val` upstream package declares
MIT but omits its own license file; that omission is explicitly identified
in its notice rather than supplying an invented copyright owner or year.

These source archives can be redistributed and modified under their original
licenses. No installation key or permission from Playhub is required.

## Private x64 runtime revision 1.6.8-playhub.1

Playhub adds a catch around arRPC's existing Windows process enumeration call.
If PowerShell returns malformed JSON or the OS query fails, that single scan
returns without reporting games as closed. The existing five-second scan
interval retries; Discord RPC, voice, messages and user preferences are not
disabled. No raw process list or command line is logged.

The preferred modified arRPC source is `patches/arrpc-scan-guard/index.js`;
`scan-guard.patch` is the minimal change against the included MIT arRPC archive.
Vesktop's GPL source archive and all dependency licenses remain included.
The worker and its source map are the only changed ASAR payloads; all 74 other
ZIP payloads, including the Electron executable and license files, are exact.
`derived-runtime.json` records the base and derived SHA-256 values.

From the source tree, obtain the unmodified official ZIP using the URL and
SHA-256 above, then run (no Electron process is started):

```text
python -X utf8 -B scripts/derive-vesktop.py --base <official-Vesktop-1.6.8-win.zip>
node --experimental-vm-modules tests/test-arrpc-scan-guard.mjs
python -X utf8 -B scripts/package.py
```

The deterministic derivation verifies the official base hash, updates ASAR
member integrity and source mappings, and refuses any unexpected runtime
payload change. It does not change Electron fuses; embedded ASAR validation
is already disabled in this official base. No executable signature is altered.
The new x64 installation directory identifies this runtime revision so a normal
plugin update cannot silently keep using the old runtime. Existing profile
paths and saved sessions are unchanged. ARM64 is not modified by this patch.

The installer also includes the identical standalone derivation tool at
`runtime/patches/derive-vesktop.py`; it accepts the same arguments.

