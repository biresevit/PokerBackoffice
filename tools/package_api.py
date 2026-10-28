"""Build Linux Python 3.11 dependencies for SWA CLI (which skips API builds)."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
req=ROOT/"api/requirements.txt"
target=(ROOT/"api/.python_packages").resolve()
assert target.parent==(ROOT/"api").resolve() and target.name==".python_packages"
digest=hashlib.sha256(req.read_bytes()).hexdigest()
stamp=target/"requirements.sha256"
if not stamp.exists() or stamp.read_text()!=digest:
    if target.exists(): shutil.rmtree(target)
    subprocess.run([sys.executable,"-m","pip","install","--disable-pip-version-check","--no-compile",
        "--platform","manylinux2014_x86_64","--implementation","cp","--python-version","3.11",
        "--only-binary=:all:","--target",str(target/"lib/site-packages"),"-r",str(req)],check=True)
    stamp.write_text(digest)
print("Linux Python 3.11 API dependencies packaged.")
