"""`scripts/mod_putback.py` (issue #837, put-back unit): restore a mod install from its backup folder.

Temp folders only (tmp_path); no PoB, no child process, no window, the owner's mods folder is never read.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mod_putback", Path(__file__).resolve().parents[1] / "scripts" / "mod_putback.py"
)
putback = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(putback)

_REAL_COPY2 = shutil.copy2

# 20 files of one install, nested; the first 17 get a backup, the last 3 are ADDED by the install.
NAMES = [
    "hooks/register.tsx", "test/x.test.tsx", "index.js", "package.json",
    "src/a.ts", "src/b.ts", "src/deep/c.ts", "src/deep/d.ts", "src/deep/er/e.ts",
    "lib/f.js", "lib/g.js", "lib/h.js", "lib/i.js", "lib/j.js",
    "assets/k.css", "assets/l.css", "assets/m.png",
    "docs/n.md", "docs/o.md", "p.json",
]
BACKED = NAMES[:17]
ADDED = NAMES[17:]
TIMESTAMP_DIR = "backup-20261012-101500"


def _orig(rel: str) -> bytes:
    return f"original {rel}\n".encode("utf-8")


def _build(tmp_path: Path) -> tuple[Path, Path]:
    """An install with 20 files, a backup of the 17 originals, the 17 then overwritten in the install."""
    install = tmp_path / "mod"
    backup = install / "bin" / ".cache" / TIMESTAMP_DIR
    for rel in NAMES:
        f = install / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_orig(rel))
    for rel in BACKED:
        b = backup / rel
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_bytes(_orig(rel))
    for rel in BACKED:
        (install / rel).write_bytes(f"changed by install {rel}\n".encode("utf-8"))
    return install, backup


def test_put_back_restores_17_files_byte_equal(tmp_path: Path) -> None:
    install, backup = _build(tmp_path)

    result = putback.put_back(install, backup)

    assert result["restored"] == 17
    assert result["bytes_equal"] is True
    assert result["added_by_install"] == []
    for rel in BACKED:
        assert (install / rel).read_bytes() == (backup / rel).read_bytes() == _orig(rel)
    # files without a backup are untouched
    for rel in ADDED:
        assert (install / rel).read_bytes() == _orig(rel)


def test_added_by_install_listed_and_kept(tmp_path: Path) -> None:
    install, backup = _build(tmp_path)

    result = putback.put_back(install, backup, installed_names=NAMES)

    assert result["restored"] == 17
    assert result["bytes_equal"] is True
    assert sorted(result["added_by_install"]) == sorted(ADDED)
    for rel in ADDED:
        assert (install / rel).is_file()
        assert (install / rel).read_bytes() == _orig(rel)


def test_newest_backup_by_timestamp_and_bin_rule(tmp_path: Path) -> None:
    # bin/.cache: three timestamp-named folders, the newest by timestamp is 20261012-080000
    install = tmp_path / "with_bin"
    cache = install / "bin" / ".cache"
    for name in ("backup-20261010-090000", "backup-20261012-080000", "backup-20261011-235959"):
        (cache / name).mkdir(parents=True)
    # a newer backup in the plain .cache must be ignored once bin exists
    (install / ".cache" / "backup-20261013-000000").mkdir(parents=True)

    assert putback.newest_backup(install) == cache / "backup-20261012-080000"

    # no bin folder: the plain .cache is used
    plain = tmp_path / "no_bin"
    (plain / ".cache" / "backup-20261009-120000").mkdir(parents=True)
    (plain / ".cache" / "backup-20261009-130000").mkdir(parents=True)
    assert putback.newest_backup(plain) == plain / ".cache" / "backup-20261009-130000"

    # nothing to find
    assert putback.newest_backup(tmp_path / "empty") is None


def test_no_backup_cli_exit_1_nothing_copied(tmp_path: Path, capsys) -> None:
    install = tmp_path / "mod"
    for rel in NAMES:
        f = install / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_orig(rel))
    before = {rel: (install / rel).read_bytes() for rel in NAMES}

    rc = putback.main([str(install)])

    assert rc == 1
    assert "no backup folder found" in capsys.readouterr().out
    after = {p.relative_to(install).as_posix(): p.read_bytes() for p in install.rglob("*") if p.is_file()}
    assert after == before


def test_dry_run_copies_nothing_exit_0(tmp_path: Path, capsys) -> None:
    install, backup = _build(tmp_path)
    changed = {rel: (install / rel).read_bytes() for rel in BACKED}

    rc = putback.main([str(install), "--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert out.count("Copy-Item -LiteralPath") == 17
    assert "nothing copied" in out
    for rel in BACKED:
        assert (install / rel).read_bytes() == changed[rel]


def test_bytes_not_equal_gives_false_and_exit_1(tmp_path: Path, monkeypatch, capsys) -> None:
    install, backup = _build(tmp_path)

    def torn_copy2(src, dst, *args, **kwargs):
        # a copy that ends different: one file gets other bytes after the real copy
        _REAL_COPY2(src, dst, *args, **kwargs)
        if Path(src).name == "index.js":
            Path(dst).write_bytes(b"torn copy\n")
        return dst

    monkeypatch.setattr(shutil, "copy2", torn_copy2)

    result = putback.put_back(install, backup)
    assert result["restored"] == 17
    assert result["bytes_equal"] is False

    rc = putback.main([str(install), "--backup", str(backup)])
    assert rc == 1
    assert "bytes_equal False" in capsys.readouterr().out
