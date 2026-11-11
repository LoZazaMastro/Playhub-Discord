# Runtime source and build notes

The release package carries the official Vesktop Windows x64 portable build
and the four official Vencord desktop files. These executables are not rebuilt
or patched by Playhub. Only the new, private profile is initialized: the
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
