# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Andrea Sgarro (LoZazaMastro).
"""Derive corresponding Vencord source without its optional Translate plugin.

No credential is embedded in this script. The exact upstream source archive is
verified, Translate is omitted before any file is written, and all retained
source is checked for Google client-key literals. No runtime is executed.
"""
import argparse
import copy
import gzip
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import tarfile

UPSTREAM_SHA256 = '4adcd253519f253f65a7868080fe30bb5e09ce0a6bc9e167866faaaeeea176ee'
COMMIT = 'd07030c0968e31e41caa0c35fda0ef8ae63a079e'
ROOT = 'Vencord-' + COMMIT
SCAN = re.compile(rb'AIza[0-9A-Za-z_-]{35}')
OLD_SORT = b'const files = await readdir(fullDir, { withFileTypes: true });'
NEW_SORT = b'const files = (await readdir(fullDir, { withFileTypes: true })).sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);'
NOTES = b'''# Playhub Vencord build changes

Base: Vendicated/Vencord, commit d07030c0968e31e41caa0c35fda0ef8ae63a079e.
License: GPL-3.0-or-later; original copyright and license files are retained.

1. Omit src/plugins/translate completely. This optional message-translation
   feature is not needed for the Playhub Discord voice/message integration.
   Its bundled third-party Google client credential is not distributed.
2. Sort plugin directory entries by ordinal filename in scripts/build/common.mjs.
   This makes Windows plugin ordering match the original upstream build. With
   Translate present, the original four desktop outputs reproduce byte-exactly.

Build: pnpm 12.15.0, pnpm install --frozen-lockfile --ignore-scripts.
Set VENCORD_HASH=d07030c, VENCORD_REMOTE=Vendicated/Vencord, and
SOURCE_DATE_EPOCH=1794368152563. Then run:
node --require=./scripts/suppressExperimentalWarnings.js scripts/build/build.mjs --standalone

The archive is derived by runtime/patches/derive-vencord-no-translate.py from
the exact upstream source archive recorded by that script. It has no user
credentials, does not modify Discord profiles, and does not start Electron.
'''


def derive(upstream, output):
    raw = Path(upstream).read_bytes()
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('upstream_source_hash_mismatch')
    kept, omitted, sort_count = [], 0, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for original in archive.getmembers():
            path = PurePosixPath(original.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != ROOT:
                raise ValueError('source_path_invalid')
            if not (original.isdir() or original.isfile()):
                raise ValueError('source_entry_invalid')
            relative = '/'.join(path.parts[1:])
            if relative == 'src/plugins/translate' or relative.startswith('src/plugins/translate/'):
                omitted += 1
                continue
            data = archive.extractfile(original).read() if original.isfile() else b''
            if relative == 'scripts/build/common.mjs':
                if data.count(OLD_SORT) != 1:
                    raise ValueError('build_generator_changed')
                data = data.replace(OLD_SORT, NEW_SORT)
                sort_count += 1
            if SCAN.search(data):
                raise ValueError('source_client_credential_remaining')
            member = copy.copy(original)
            member.uid = member.gid = 0
            member.uname = member.gname = ''
            member.pax_headers = {}
            member.size = len(data) if member.isfile() else 0
            kept.append((member, data))
    if omitted < 2 or sort_count != 1:
        raise ValueError('optional_plugin_layout_changed')
    note = tarfile.TarInfo(ROOT + '/PLAYHUB-PATCHES.md')
    note.mode = 0o644
    note.size = len(NOTES)
    note.mtime = 0
    kept.append((note, NOTES))
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('wb') as target:
        with gzip.GzipFile(filename='', fileobj=target, mode='wb', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for member, data in kept:
                    archive.addfile(member, io.BytesIO(data) if member.isfile() else None)
    return {'sha256': hashlib.sha256(destination.read_bytes()).hexdigest().upper(),
            'bytes': destination.stat().st_size, 'omittedEntries': omitted, 'remainingGoogleKeyMatches': 0}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(derive(args.upstream, args.output), indent=2))
