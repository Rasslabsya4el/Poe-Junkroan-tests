"""#459: the extracted PoB app dir keeps its parent's inherited ACL (Windows)."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from junkroan.pob.release_manager import PoBReleaseManager

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")


def test_extracted_app_inherits_acl(tmp_path: Path) -> None:
    archive = tmp_path / "pob.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Launch.lua", "-- x")
        zf.writestr("sub/file.txt", "y")
    cache = tmp_path / "cache"
    cache.mkdir()
    app = cache / "app"
    # pytest's tmp dirs are 0o700-protected; give the cache dir the parent ACL a real host has.
    subprocess.run(["icacls", str(cache), "/grant", "*S-1-5-32-545:(OI)(CI)(RX)"], capture_output=True, check=True)

    manager = PoBReleaseManager(cache_root=cache)
    assert manager._ensure_extracted_archive(archive, app, force=False) is True

    out = subprocess.run(["icacls", str(app)], capture_output=True, text=True, check=True).stdout
    users = [line for line in out.splitlines() if "BUILTIN\\Users" in line]
    assert users and any("(I)" in line for line in users), out

    protected = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"(Get-Acl -LiteralPath '{app}').AreAccessRulesProtected"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert protected == "False"
    assert (app / "sub" / "file.txt").read_text() == "y"
