"""Download a pinned, checksum-verified portable repak; no system installation."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if os.name != "nt":
        raise SystemExit("This bootstrap pins the Windows build. On another OS install repak 0.2.3 from its upstream release and set [tools].repak in config.local.toml.")
    lock = json.loads((ROOT / "tools/tools.lock.json").read_text())
    target = ROOT / f"work/tools/repak-v{lock['version']}"
    exe = target / "repak.exe"
    if exe.exists() and hashlib.sha256(exe.read_bytes()).hexdigest() == lock["windows_exe_sha256"]:
        print("repak executable verified")
        return
    archive = ROOT / "tools/downloads" / lock["windows_url"].rsplit("/", 1)[1]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != lock["windows_archive_sha256"]:
        with urllib.request.urlopen(lock["windows_url"], timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["windows_archive_sha256"]:
        raise SystemExit("repak archive checksum mismatch")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            dest = (target / info.filename).resolve()
            if not dest.is_relative_to(target.resolve()):
                raise SystemExit("Unsafe archive path")
        z.extractall(target)
    if hashlib.sha256(exe.read_bytes()).hexdigest() != lock["windows_exe_sha256"]:
        raise SystemExit("repak executable checksum mismatch")
    print("repak 0.2.3 downloaded and verified")


if __name__ == "__main__":
    main()
