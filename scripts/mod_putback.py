"""Put a mod install back from its backup folder (issue #837, put-back unit).

`tools/agentops/mods.py` `run_install` backs up each differing file before it overwrites it, into
`<install>/bin/.cache/backup-YYYYMMDD-HHMMSS/<rel path>` (or `<install>/.cache/backup-...` when
`<install>/bin` does not exist). This script copies those originals back over the install.

    python scripts/mod_putback.py <install_dir> [--backup <dir>] [--dry-run]

Default backup is the newest `backup-*` folder under the cache folder, chosen the way `run_install`
chooses it. `--dry-run` prints one `Copy-Item` line per file and copies nothing.

Files the install ADDED (no counterpart in the backup) are never deleted: `put_back` leaves them in
place and lists them under `added_by_install` when the caller passes `installed_names`. The CLI keeps
no install log, so it passes no names and reports no added files.

Stdlib only: no window and no child process.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

BACKUP_PREFIX = "backup-"
BACKUP_FORMAT = "%Y%m%d-%H%M%S"


def cache_dir(install_dir: Path) -> Path:
    """The folder `run_install` writes backups into: `bin/.cache` if `bin` exists, else `.cache`."""
    install_dir = Path(install_dir)
    return install_dir / "bin" / ".cache" if (install_dir / "bin").is_dir() else install_dir / ".cache"


def _stamp(folder: Path) -> datetime | None:
    try:
        return datetime.strptime(folder.name[len(BACKUP_PREFIX):], BACKUP_FORMAT)
    except ValueError:
        return None


def newest_backup(install_dir: Path) -> Path | None:
    """The `backup-*` folder with the newest timestamp in its name, or None when there is none."""
    cache = cache_dir(install_dir)
    if not cache.is_dir():
        return None
    best: tuple[datetime, Path] | None = None
    for folder in cache.glob(BACKUP_PREFIX + "*"):
        stamp = _stamp(folder) if folder.is_dir() else None
        if stamp is not None and (best is None or stamp > best[0]):
            best = (stamp, folder)
    return best[1] if best else None


def _rel_files(root: Path) -> list[str]:
    """Every file under root as a POSIX relative path, sorted."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def put_back(install_dir: Path, backup_dir: Path, installed_names: Iterable[str] | None = None) -> dict:
    """Copy every file under backup_dir back to install_dir/<same rel path>.

    Returns {"restored": n, "added_by_install": [...], "bytes_equal": bool}.
    - ``added_by_install``: only when ``installed_names`` is given, the names the install reported as
      copied that have no file in backup_dir (the install added them). Those files are LEFT in place,
      never deleted; the caller decides what to do with them.
    - ``bytes_equal``: True only when at least one file was restored and every restored file, re-read
      from the install, is byte-equal to its backup. An empty backup folder gives False (nothing proven).
    """
    install_dir, backup_dir = Path(install_dir), Path(backup_dir)
    names = _rel_files(backup_dir)
    restored = 0
    for rel in names:
        dst = install_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_dir / rel, dst)
        restored += 1
    added: list[str] = []
    if installed_names is not None:
        backed = set(names)
        reported = (Path(n).as_posix() for n in installed_names)
        added = [n for n in dict.fromkeys(reported) if n not in backed]
    equal = restored > 0 and all(
        (install_dir / rel).read_bytes() == (backup_dir / rel).read_bytes() for rel in names
    )
    return {"restored": restored, "added_by_install": added, "bytes_equal": equal}


def _copy_item_line(src: Path, dst: Path) -> str:
    def quote(p: Path) -> str:
        return "'" + str(p).replace("'", "''") + "'"
    return f"Copy-Item -LiteralPath {quote(src)} -Destination {quote(dst)} -Force"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Put a mod install back from its backup folder (#837).")
    ap.add_argument("install_dir", type=Path)
    ap.add_argument("--backup", type=Path, default=None,
                    help="backup folder to restore from (default: the newest backup-* under the cache)")
    ap.add_argument("--dry-run", action="store_true", help="print the Copy-Item lines, copy nothing")
    args = ap.parse_args(argv)

    install = args.install_dir
    backup = args.backup if args.backup is not None else newest_backup(install)
    if backup is None or not backup.is_dir():
        where = cache_dir(install) if args.backup is None else args.backup
        print(f"no backup folder found: {where}")
        return 1
    print(f"backup: {backup}")

    if args.dry_run:
        files = _rel_files(backup)
        for rel in files:
            print(_copy_item_line(backup / rel, install / rel))
        print(f"dry run: would restore {len(files)} files, nothing copied")
        return 0

    result = put_back(install, backup)
    print(f"restored {result['restored']} files, bytes_equal {result['bytes_equal']}")
    return 0 if result["bytes_equal"] else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
