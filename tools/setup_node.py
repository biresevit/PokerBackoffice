"""Install a verified portable Node 22 LTS release for the SWA deployment CLI."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

root=Path(__file__).resolve().parents[1]/"artifacts"/"tooling"
root.mkdir(parents=True,exist_ok=True)
releases=json.load(urllib.request.urlopen("https://nodejs.org/dist/index.json"))
version=next(r["version"] for r in releases if r["version"].startswith("v22.") and r["lts"])
name=f"node-{version}-win-x64"
archive=root/(name+".zip")
base=f"https://nodejs.org/dist/{version}/"
checks=urllib.request.urlopen(base+"SHASUMS256.txt").read().decode()
digest=next(line.split()[0] for line in checks.splitlines() if line.endswith(name+".zip"))
if not archive.exists():
    urllib.request.urlretrieve(base+archive.name,archive)
assert hashlib.sha256(archive.read_bytes()).hexdigest()==digest,"Node checksum mismatch"
if not (root/name/"node.exe").exists():
    with zipfile.ZipFile(archive) as z:
        z.extractall(root)
print(root/name)
