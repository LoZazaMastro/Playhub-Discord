"""Derive the private x64 runtime from the pinned official ZIP, without executing it.

Only the arRPC scan error boundary and its source map change. The original
executables, licenses, all other ASAR payloads and all other ZIP payloads stay exact.
"""
import argparse
import copy
import difflib
import hashlib
import json
from pathlib import Path
import struct
import tarfile
import zipfile

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2] if SCRIPT.parent.name == 'patches' and SCRIPT.parent.parent.name == 'runtime' else SCRIPT.parents[1]
BASE_SHA = '8ffa8d3778c287551ee0b302b3396acd2fac45931282071048bb881b67c88286'
OUTPUT = 'Vesktop-1.6.8-playhub.1-win.zip'
WORKER = 'dist/js/arRpcWorker.js'
MAP = WORKER + '.map'
BEFORE = '    const processes = await Native.getProcesses();'
AFTER = '''    let processes;
    try {
      processes = await Native.getProcesses();
    } catch {
      // A failed OS snapshot must not terminate the RPC worker or report games as closed.
      // Retry on the existing five-second scan; do not log private process data.
      log('process enumeration unavailable; retrying on the next scan');
      return;
    }'''
JS_BEFORE = 'let e=await Rs.getProcesses(),s=[];'
JS_AFTER = 'let e;try{e=await Rs.getProcesses()}catch{A("process enumeration unavailable; retrying on the next scan");return}let s=[];'
ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack_asar(data):
    _, header_size, _, json_size = struct.unpack('<4I', data[:16])
    header = json.loads(data[16:16 + json_size])
    files = {}
    def walk(node, prefix=''):
        for name, item in node.get('files', {}).items():
            key = prefix + name
            if 'files' in item:
                walk(item, key + '/')
            else:
                if 'link' in item or item.get('unpacked'):
                    raise ValueError('Unexpected external ASAR member')
                start = 8 + header_size + int(item['offset'])
                files[key] = (item, data[start:start + item['size']])
                if len(files[key][1]) != item['size']:
                    raise ValueError('Truncated ASAR member')
    walk(header)
    return header, files


def pack_asar(header, files):
    chunks, offset = [], 0
    for _, (item, data) in sorted(files.items(), key=lambda pair: int(pair[1][0]['offset'])):
        item.update(size=len(data), offset=str(offset))
        integrity = item.get('integrity')
        if integrity:
            if integrity.get('algorithm') != 'SHA256':
                raise ValueError('Unexpected integrity algorithm')
            block = integrity['blockSize']
            integrity.update(hash=sha(data), blocks=[sha(data[i:i + block]) for i in range(0, len(data), block)])
        chunks.append(data)
        offset += len(data)
    encoded = json.dumps(header, separators=(',', ':'), ensure_ascii=False).encode()
    padded = encoded + b'\0' * (-len(encoded) % 4)
    pickle = struct.pack('<II', 4 + len(padded), len(encoded)) + padded
    return struct.pack('<II', 4, len(pickle)) + pickle + b''.join(chunks)


def decode_vlq(segment):
    values, number, shift = [], 0, 0
    for char in segment:
        v = ALPHABET.index(char)
        number |= (v & 31) << shift
        if v & 32:
            shift += 5
        else:
            values.append(-(number >> 1) if number & 1 else number >> 1)
            number = shift = 0
    if shift:
        raise ValueError('Truncated source map')
    return values


def encode_vlq(values):
    result = ''
    for value in values:
        number = (-value << 1) | 1 if value < 0 else value << 1
        while True:
            digit, number = number & 31, number >> 5
            result += ALPHABET[digit | (32 if number else 0)]
            if not number:
                break
    return result


def adjust_map(source_map, source_index, old_line, added_lines, gen_line, start, end):
    # Decode absolute positions; adjust the one edited source and generated span.
    lines, source, line, col, name = [], 0, 0, 0, 0
    for i, encoded_line in enumerate(source_map['mappings'].split(';')):
        segments, generated = [], 0
        for encoded in filter(None, encoded_line.split(',')):
            values = decode_vlq(encoded)
            generated += values[0]
            absolute = [generated]
            if len(values) > 1:
                source += values[1]; line += values[2]; col += values[3]
                absolute += [source, line, col]
                if len(values) == 5:
                    name += values[4]; absolute.append(name)
            if i == gen_line and start <= generated < end:
                continue
            if i == gen_line and generated >= end:
                absolute[0] += len(JS_AFTER) - len(JS_BEFORE)
            if len(absolute) > 1 and absolute[1] == source_index and absolute[2] > old_line:
                absolute[2] += added_lines
            segments.append(absolute)
        if i == gen_line:
            segments.append([start, source_index, old_line, 4])
            segments.sort(key=lambda row: row[0])
        lines.append(segments)
    encoded_lines, source, line, col, name = [], 0, 0, 0, 0
    for segments in lines:
        generated, encoded = 0, []
        for row in segments:
            values = [row[0] - generated]; generated = row[0]
            if len(row) > 1:
                values += [row[1] - source, row[2] - line, row[3] - col]
                source, line, col = row[1:4]
                if len(row) == 5:
                    values.append(row[4] - name); name = row[4]
            encoded.append(encode_vlq(values))
        encoded_lines.append(','.join(encoded))
    source_map['mappings'] = ';'.join(encoded_lines)


def derive(base, output):
    if sha(base.read_bytes()) != BASE_SHA:
        raise ValueError('Official base ZIP checksum mismatch')
    with zipfile.ZipFile(base) as archive:
        original_asar = archive.read('resources/app.asar')
        header, files = unpack_asar(original_asar)
        original_payloads = {key: payload for key, (_, payload) in files.items()}
        worker = files[WORKER][1].decode()
        source_map = json.loads(files[MAP][1])
        index = next(i for i, name in enumerate(source_map['sources']) if name.endswith('/src/process/index.js'))
        original_source = source_map['sourcesContent'][index]
        if original_source.count(BEFORE) != 1 or worker.count(JS_BEFORE) != 1:
            raise ValueError('Pinned source/worker context differs')
        with tarfile.open(ROOT / 'runtime/sources/arrpc-source.tar.gz') as sources:
            member = next(m for m in sources.getmembers() if m.name.endswith('/src/process/index.js'))
            if sources.extractfile(member).read().decode() != original_source:
                raise ValueError('Corresponding source does not match worker')
        revised_source = original_source.replace(BEFORE, AFTER)
        position = worker.index(JS_BEFORE)
        gen_line = worker.count('\n', 0, position)
        gen_col = position - (worker.rfind('\n', 0, position) + 1)
        old_line = original_source[:original_source.index(BEFORE)].count('\n')
        adjust_map(source_map, index, old_line, AFTER.count('\n'), gen_line, gen_col, gen_col + len(JS_BEFORE))
        source_map['sourcesContent'][index] = revised_source
        files[WORKER] = (files[WORKER][0], worker.replace(JS_BEFORE, JS_AFTER).encode())
        files[MAP] = (files[MAP][0], json.dumps(source_map, separators=(',', ':'), ensure_ascii=False).encode())
        revised_asar = pack_asar(header, files)
        _, check = unpack_asar(revised_asar)
        changed = [key for key in original_payloads if original_payloads[key] != check[key][1]]
        if changed != [WORKER, MAP]:
            raise ValueError('Unexpected ASAR payload changes: ' + repr(changed))
        # Official Electron disables embedded ASAR validation; do not change any fuse/executable.
        executable = archive.read('vesktop.exe')
        sentinel = b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'
        fuse = executable.index(sentinel) + len(sentinel)
        if executable[fuse] != 1 or executable[fuse + 1] < 5 or executable[fuse + 2 + 4] != ord('0'):
            raise ValueError('ASAR modification not supported by pinned Electron fuse')
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w') as target:
            for info in archive.infolist():
                payload = revised_asar if info.filename == 'resources/app.asar' else archive.read(info)
                target.writestr(copy.copy(info), payload)
        with zipfile.ZipFile(output) as result:
            if result.testzip():
                raise ValueError('Derived runtime CRC failure')
            changed_zip = [name for name in archive.namelist() if archive.read(name) != result.read(name)]
            if changed_zip != ['resources/app.asar']:
                raise ValueError('Unexpected runtime payload changes')
        patches = ROOT / 'runtime/patches/arrpc-scan-guard'
        patches.mkdir(parents=True, exist_ok=True)
        (patches / 'index.js').write_text(revised_source, encoding='utf-8', newline='\n')
        (patches / 'scan-guard.patch').write_text(''.join(difflib.unified_diff(original_source.splitlines(True), revised_source.splitlines(True), fromfile='a/src/process/index.js', tofile='b/src/process/index.js')), encoding='utf-8', newline='\n')
        # Keep the derivation tool with corresponding source in the installer too.
        (ROOT / 'runtime/patches/derive-vesktop.py').write_bytes(SCRIPT.read_bytes())
        proof = {'runtime':'Vesktop 1.6.8-playhub.1 x64', 'baseSha256':BASE_SHA,
                 'derivedSha256':sha(output.read_bytes()), 'baseAsarSha256':sha(original_asar),
                 'derivedAsarSha256':sha(revised_asar), 'changedZipMembers':changed_zip,
                 'changedAsarMembers':changed, 'zipMembers':len(archive.infolist()), 'asarMembers':len(check),
                 'electronExecutableUnchanged':True,'embeddedAsarValidation':False,
                 'sourceSha256':sha(revised_source.encode()),
                 'behavior':'Skip failed OS process snapshot; preserve last activity; retry existing 5s scan. No profile access or feature disable.'}
        (ROOT / 'runtime/derived-runtime.json').write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
        return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / OUTPUT)
    args = parser.parse_args()
    print(json.dumps(derive(args.base, args.output), indent=2))
