"""Collect the exact Vencord runtime dependency notices from its source lock.

Development tool only. Requires PyYAML; no code from downloaded packages runs.
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(tempfile.gettempdir()) / "Playhub-Discord-Runtime-Notices"
CACHE.mkdir(exist_ok=True)


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "Playhub-license-build"}), timeout=45) as response:
        data = response.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024:
        raise ValueError("Dependency archive exceeds size limit")
    return data


with tarfile.open(ROOT / "runtime/sources/Vencord-source.tar.gz") as source:
    member = next(item for item in source.getmembers() if item.name.split("/", 1)[-1] == "pnpm-lock.yaml")
    documents = list(yaml.safe_load_all(source.extractfile(member).read().decode()))
    lock = next(document for document in documents if document.get("catalogs"))

packages = lock["packages"]
snapshots = lock["snapshots"]
pending = [(name, value["version"]) for name, value in lock["importers"]["."]["dependencies"].items()]
seen = set()
records = []
notices = ["VENCORD RUNTIME DEPENDENCY NOTICES\n\n"
           "Collected from the exact dependency closure in the bundled Vencord source lock.\n"
           "Some optional/editor packages are loaded only when those features are used.\n"]
while pending:
    name, version = pending.pop(0)
    key = name + "@" + version
    if key in seen:
        continue
    seen.add(key)
    spec = packages.get(key) or packages.get(key.split("(")[0])
    if not spec:
        raise ValueError("Dependency missing from lock: " + key)
    integrity = spec.get("resolution", {}).get("integrity")
    if not integrity:
        raise ValueError("Dependency missing integrity: " + key)
    metadata = None
    if version.startswith("https://"):
        url = version
    else:
        exact = version.split("(")[0]
        metadata = json.loads(fetch("https://registry.npmjs.org/" + quote(name, safe="@") + "/" + exact))
        url = metadata["dist"]["tarball"]
    archive = fetch(url)
    algorithm, encoded = integrity.split("-", 1)
    if base64.b64encode(hashlib.new(algorithm, archive).digest()).decode() != encoded:
        raise ValueError("Dependency integrity mismatch: " + key)
    cached = CACHE / (hashlib.sha256(archive).hexdigest() + ".tar.gz")
    cached.write_bytes(archive)
    licenses = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for item in tar.getmembers():
            basename = item.name.rsplit("/", 1)[-1].lower()
            if (item.isfile() and item.size < 4 * 1024 * 1024
                    and re.match(r"^(licen[sc]e|copying|notice|thirdpartynotices)(\.|$|[-_])", basename)):
                licenses.append((item.name, tar.extractfile(item).read().decode("utf-8", errors="replace")))
    if not licenses:
        repository = (metadata or {}).get("repository", {})
        repository = repository.get("url", "") if isinstance(repository, dict) else repository
        match = re.fullmatch(r"git\+https://github\.com/([^/]+/[^/]+?)(?:\.git)?", repository)
        commit = (metadata or {}).get("gitHead", "")
        if match and re.fullmatch(r"[a-f0-9]{40}", commit):
            license_url = "https://raw.githubusercontent.com/" + match[1] + "/" + commit + "/LICENSE"
            try:
                licenses.append((license_url, fetch(license_url).decode("utf-8")))
            except Exception:
                pass
        if not licenses:
            raise ValueError("No full license found: " + key)
    notices.append("\n" + "=" * 78 + "\n" + key + "\nSource: " + url + "\n")
    for filename, text in licenses:
        notices.append("\n--- " + filename + " ---\n" + text + "\n")
    records.append({"package": name, "version": version, "url": url, "integrity": integrity,
                    "sha256": hashlib.sha256(archive).hexdigest(), "licenseFiles": [item[0] for item in licenses]})
    snapshot = snapshots.get(key) or snapshots.get(key.split("(")[0]) or {}
    pending.extend(snapshot.get("dependencies", {}).items())
    pending.extend(snapshot.get("optionalDependencies", {}).items())

output = ROOT / "runtime/licenses"
(output / "VENCORD-DEPENDENCY-NOTICES.txt").write_text("".join(notices), encoding="utf-8")
(output / "VENCORD-DEPENDENCY-PROVENANCE.json").write_text(json.dumps({
    "sourceCommit": "d07030c0968e31e41caa0c35fda0ef8ae63a079e", "packages": records}, indent=2), encoding="utf-8")
print("Collected and verified " + str(len(records)) + " dependency notices.")
