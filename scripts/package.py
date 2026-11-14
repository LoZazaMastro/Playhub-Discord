"""Build the self-contained Discord plugin ZIP from an already compiled frontend."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def build():
    subprocess.run(["node", "node_modules/typescript/bin/tsc", "--noEmit"], cwd=ROOT, check=True)
    subprocess.run(["node", "node_modules/rollup/dist/bin/rollup", "-c"], cwd=ROOT, check=True)
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["name"] != "Discord":
        raise ValueError("Unexpected plugin identity")
    if not (ROOT / "dist/index.js").is_file():
        raise ValueError("Compile the frontend before packaging")
    payload = ROOT / "runtime/Vesktop-1.6.8-playhub.1-win.zip"
    if digest(payload) != "97829d8c2d317db0ba3ac965e721f24846b027fcdec1230e141a1c57a370707f":
        raise ValueError("Portable runtime checksum mismatch")
    vencord = json.loads((ROOT / "runtime/vencord/manifest.json").read_text(encoding="utf-8"))
    for entry in vencord["files"]:
        path = ROOT / "runtime/vencord" / entry["file"]
        if digest(path) != entry["sha256"] or path.stat().st_size != entry["size"]:
            raise ValueError("Vencord runtime checksum mismatch")
    files = [ROOT / name for name in ("main.py", "plugin.json", "package.json", "LICENSE", "CREDITS.md",
                                      "README.md", "CHANGELOG.md", "NOTICE.md", "FRONTEND-NOTICES.txt")]
    for folder in ("defaults", "dist", "py_modules", "runtime"):
        files.extend(path for path in (ROOT / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".map", ".so"}
                     and path.name != "Vesktop-1.6.8-win.zip")
    files = sorted(set(files))
    spec=importlib.util.spec_from_file_location('discord_secret_guard',ROOT/'scripts/check-secrets.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    guard.check(ROOT,files)
    records = []
    for path in files:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(ROOT) or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked package path refused")
        records.append({"file": path.relative_to(ROOT).as_posix(), "size": path.stat().st_size, "sha256": digest(path)})
    output = ROOT / "out"
    output.mkdir(exist_ok=True)
    archive = output / ("Discord_Installer-" + package["version"] + ".zip")
    manifest = {"plugin": "Discord", "version": package["version"],
                "upstream": {"repository": "Necrosiak/Steamcord", "version": "1.45.1",
                             "commit": "65b183e39e31c253dad7cb9b42c799d67f878f2f"}, "files": records}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for path in files:
            # A ZIP inside this ZIP is already compressed.
            target.write(path, "Discord/" + path.relative_to(ROOT).as_posix(),
                         compress_type=zipfile.ZIP_STORED if path.suffix in {".zip", ".gz"} else zipfile.ZIP_DEFLATED)
        target.writestr("Discord/PACKAGE-MANIFEST.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(archive) as verify:
        corrupt = verify.testzip()
        if corrupt:
            raise ValueError("Corrupt package member: " + corrupt)
        for entry in records:
            if hashlib.sha256(verify.read("Discord/" + entry["file"])).hexdigest() != entry["sha256"]:
                raise ValueError("Package verification failed: " + entry["file"])
    release = {"plugin": "Discord", "version": package["version"], "file": archive.name,
               "size": archive.stat().st_size, "sha256": digest(archive), "files": len(records)}
    (output / "release-info.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(release, indent=2))


if __name__ == "__main__":
    build()
