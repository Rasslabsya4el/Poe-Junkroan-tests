"""Pinned release management for Path of Building Community.

The contract is intentionally thin:

- release metadata is pinned into ``locks/pob.lock.json``
- downloaded assets are cached under ``var/cache/pob/<tag>/downloads/``
- extracted runtimes live under ``var/cache/pob/<tag>/app/``

This keeps PoB versioned by upstream tag and avoids in-place overwrite of old
runtime caches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_REPO = "PathOfBuildingCommunity/PathOfBuilding"
DEFAULT_TAG = "v2.64.0"
DEFAULT_ASSET_NAME = "PathOfBuildingCommunity-Portable.zip"
FALLBACK_ASSET_NAME = "PathOfBuildingCommunity-Setup.exe"
GITHUB_API_BASE = "https://api.github.com/repos"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOCK_PATH = PROJECT_ROOT / "locks" / "pob.lock.json"
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "var" / "cache" / "pob"
DOWNLOADS_SUBDIR = "downloads"
DEFAULT_EXTRACT_SUBDIR = "app"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class LockContractError(RuntimeError):
    """Raised when the lock file or local cache violates the release contract."""


def utc_now_iso() -> str:
    """Return an ISO 8601 UTC timestamp with second precision."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso8601(value: str, field_name: str) -> None:
    """Raise ``LockContractError`` if an ISO 8601 value cannot be parsed."""

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LockContractError(f"{field_name} must be an ISO 8601 timestamp.") from exc


def validate_sha256(value: str, field_name: str) -> None:
    """Raise ``LockContractError`` when a digest is not a lowercase SHA-256 hex."""

    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise LockContractError(f"{field_name} must be a lowercase 64-character SHA-256 hex digest.")


def validate_url(value: str, field_name: str) -> None:
    """Raise ``LockContractError`` when a value is not a HTTPS URL."""

    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise LockContractError(f"{field_name} must be an https URL.")


def validate_relative_subdir(value: str) -> PurePosixPath:
    """Return a normalized relative subdir path used inside the version cache."""

    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise LockContractError("extract_subdir must be a safe relative path.")
    return normalized


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest for a local file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class PoBReleaseLock:
    """Committed lock metadata for a specific PoB release asset."""

    repo: str
    tag: str
    published_at: str
    asset_name: str
    asset_url: str
    asset_sha256: str
    asset_size: int
    fetched_at: str
    extract_subdir: str
    release_id: int | None = None
    etag: str | None = None
    notes_url: str | None = None
    platform: str | None = None
    fallback_asset_name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PoBReleaseLock":
        required = {
            "repo",
            "tag",
            "published_at",
            "asset_name",
            "asset_url",
            "asset_sha256",
            "asset_size",
            "fetched_at",
            "extract_subdir",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise LockContractError(f"Lock file is missing required keys: {', '.join(missing)}")

        repo = str(data["repo"])
        if "/" not in repo or repo.startswith("/") or repo.endswith("/"):
            raise LockContractError("repo must match <owner>/<repo>.")

        tag = str(data["tag"])
        if not tag.startswith("v"):
            raise LockContractError("tag must start with 'v'.")

        published_at = str(data["published_at"])
        parse_iso8601(published_at, "published_at")

        asset_name = str(data["asset_name"])
        if not asset_name:
            raise LockContractError("asset_name must be a non-empty string.")

        asset_url = str(data["asset_url"])
        validate_url(asset_url, "asset_url")

        asset_sha256 = str(data["asset_sha256"])
        validate_sha256(asset_sha256, "asset_sha256")

        asset_size = data["asset_size"]
        if not isinstance(asset_size, int) or asset_size < 1:
            raise LockContractError("asset_size must be a positive integer.")

        fetched_at = str(data["fetched_at"])
        parse_iso8601(fetched_at, "fetched_at")

        extract_subdir = str(data["extract_subdir"])
        validate_relative_subdir(extract_subdir)

        notes_url = data.get("notes_url")
        if notes_url is not None:
            validate_url(str(notes_url), "notes_url")

        platform = data.get("platform")
        if platform is not None and platform != "windows":
            raise LockContractError("platform must be 'windows' when provided.")

        return cls(
            repo=repo,
            tag=tag,
            published_at=published_at,
            asset_name=asset_name,
            asset_url=asset_url,
            asset_sha256=asset_sha256,
            asset_size=asset_size,
            fetched_at=fetched_at,
            extract_subdir=extract_subdir,
            release_id=data.get("release_id"),
            etag=data.get("etag"),
            notes_url=str(notes_url) if notes_url is not None else None,
            platform=str(platform) if platform is not None else None,
            fallback_asset_name=str(data["fallback_asset_name"]) if data.get("fallback_asset_name") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the lock while dropping optional null values."""

        serialized = asdict(self)
        return {key: value for key, value in serialized.items() if value is not None}


@dataclass(frozen=True)
class CacheLayout:
    """Stable local cache paths for versioned PoB assets."""

    cache_root: Path

    def version_root(self, tag: str) -> Path:
        return self.cache_root / tag

    def downloads_dir(self, tag: str) -> Path:
        return self.version_root(tag) / DOWNLOADS_SUBDIR

    def archive_path(self, release_lock: PoBReleaseLock) -> Path:
        return self.downloads_dir(release_lock.tag) / release_lock.asset_name

    def extract_dir(self, release_lock: PoBReleaseLock) -> Path:
        relative = validate_relative_subdir(release_lock.extract_subdir)
        return self.version_root(release_lock.tag).joinpath(*relative.parts)


@dataclass(frozen=True)
class FetchReport:
    """Materialized local cache paths for the currently pinned release."""

    tag: str
    archive_path: Path
    extract_dir: Path
    downloaded: bool
    extracted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "archive_path": str(self.archive_path),
            "extract_dir": str(self.extract_dir),
            "downloaded": self.downloaded,
            "extracted": self.extracted,
        }


@dataclass(frozen=True)
class VerificationReport:
    """Observed state for a local asset verification pass."""

    tag: str
    archive_path: Path
    extract_dir: Path
    asset_sha256: str
    asset_size: int
    extracted_runtime_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "archive_path": str(self.archive_path),
            "extract_dir": str(self.extract_dir),
            "asset_sha256": self.asset_sha256,
            "asset_size": self.asset_size,
            "extracted_runtime_present": self.extracted_runtime_present,
        }


class PoBReleaseManager:
    """Fetch, pin, show, and verify a committed PoB release lock."""

    def __init__(
        self,
        lock_path: Path = DEFAULT_LOCK_PATH,
        cache_root: Path = DEFAULT_CACHE_ROOT,
        urlopen_fn: Callable[..., Any] = urlopen,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.cache_layout = CacheLayout(Path(cache_root))
        self._urlopen = urlopen_fn

    def load_lock(self) -> PoBReleaseLock:
        """Load and validate the committed lock file."""

        with self.lock_path.open("r", encoding="utf-8") as handle:
            return PoBReleaseLock.from_dict(json.load(handle))

    def write_lock(self, release_lock: PoBReleaseLock) -> Path:
        """Persist the release lock in a stable JSON format."""

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(release_lock.to_dict(), handle, indent=2)
            handle.write("\n")
        return self.lock_path

    def show_lock(self) -> dict[str, Any]:
        """Return the current committed lock as JSON-serializable data."""

        return self.load_lock().to_dict()

    def pin(self, version: str | None = None, latest_stable: bool = False) -> PoBReleaseLock:
        """Resolve GitHub release metadata and persist a committed lock."""

        if latest_stable == (version is not None):
            raise LockContractError("Choose exactly one of version or latest_stable.")

        if latest_stable:
            api_url = f"{GITHUB_API_BASE}/{DEFAULT_REPO}/releases/latest"
        else:
            api_url = f"{GITHUB_API_BASE}/{DEFAULT_REPO}/releases/tags/{version}"

        request = Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "poe-build-research",
            },
        )
        with self._urlopen(request, timeout=30) as response:
            payload = json.load(response)
            etag = response.headers.get("ETag")

        release_lock = self._lock_from_release_payload(payload, etag)
        self.write_lock(release_lock)
        return release_lock

    def fetch(self, force: bool = False) -> FetchReport:
        """Fetch and extract the pinned release into a versioned cache root."""

        release_lock = self.load_lock()
        archive_path = self.cache_layout.archive_path(release_lock)
        extract_dir = self.cache_layout.extract_dir(release_lock)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        extract_dir.parent.mkdir(parents=True, exist_ok=True)

        downloaded = force or not self._cached_archive_matches_lock(release_lock, archive_path)
        if downloaded:
            self._download_archive(release_lock, archive_path)

        extracted = False
        if release_lock.asset_name.lower().endswith(".zip"):
            extracted = self._ensure_extracted_archive(archive_path, extract_dir, force=force)

        return FetchReport(
            tag=release_lock.tag,
            archive_path=archive_path,
            extract_dir=extract_dir,
            downloaded=downloaded,
            extracted=extracted,
        )

    def verify(self) -> VerificationReport:
        """Verify the cached asset against the committed lock metadata."""

        release_lock = self.load_lock()
        archive_path = self.cache_layout.archive_path(release_lock)
        extract_dir = self.cache_layout.extract_dir(release_lock)
        digest = self._verify_archive(release_lock, archive_path)

        return VerificationReport(
            tag=release_lock.tag,
            archive_path=archive_path,
            extract_dir=extract_dir,
            asset_sha256=digest,
            asset_size=archive_path.stat().st_size,
            extracted_runtime_present=extract_dir.exists(),
        )

    def _lock_from_release_payload(self, payload: dict[str, Any], etag: str | None) -> PoBReleaseLock:
        asset = None
        fallback = None
        for candidate in payload.get("assets", []):
            if candidate.get("name") == DEFAULT_ASSET_NAME:
                asset = candidate
            if candidate.get("name") == FALLBACK_ASSET_NAME:
                fallback = candidate

        if asset is None:
            raise LockContractError(
                f"Release {payload.get('tag_name')} does not expose the required {DEFAULT_ASSET_NAME} asset."
            )

        digest_value = asset.get("digest")
        if not isinstance(digest_value, str) or not digest_value.startswith("sha256:"):
            raise LockContractError("GitHub release asset digest is missing or not a sha256 digest.")

        asset_sha256 = digest_value.split(":", maxsplit=1)[1]
        validate_sha256(asset_sha256, "asset_sha256")

        published_at = str(payload["published_at"])
        parse_iso8601(published_at, "published_at")

        return PoBReleaseLock(
            repo=DEFAULT_REPO,
            tag=str(payload["tag_name"]),
            published_at=published_at,
            asset_name=str(asset["name"]),
            asset_url=str(asset["browser_download_url"]),
            asset_sha256=asset_sha256,
            asset_size=int(asset["size"]),
            fetched_at=utc_now_iso(),
            extract_subdir=DEFAULT_EXTRACT_SUBDIR,
            release_id=int(payload["id"]),
            etag=etag,
            notes_url=str(payload.get("html_url")) if payload.get("html_url") else None,
            platform="windows",
            fallback_asset_name=str(fallback["name"]) if fallback is not None else None,
        )

    def _cached_archive_matches_lock(self, release_lock: PoBReleaseLock, archive_path: Path) -> bool:
        try:
            self._verify_archive(release_lock, archive_path)
        except (FileNotFoundError, LockContractError):
            return False
        return True

    def _download_archive(self, release_lock: PoBReleaseLock, archive_path: Path) -> None:
        temporary_path = archive_path.with_suffix(archive_path.suffix + ".part")
        if temporary_path.exists():
            temporary_path.unlink()

        request = Request(
            release_lock.asset_url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "poe-build-research",
            },
        )
        digest = hashlib.sha256()
        total_bytes = 0

        with self._urlopen(request, timeout=120) as response, temporary_path.open("wb") as handle:
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                handle.write(chunk)
                digest.update(chunk)
                total_bytes += len(chunk)

        if total_bytes != release_lock.asset_size:
            temporary_path.unlink(missing_ok=True)
            raise LockContractError(
                f"Downloaded asset size mismatch for {release_lock.asset_name}: "
                f"expected {release_lock.asset_size}, got {total_bytes}."
            )

        digest_hex = digest.hexdigest()
        if digest_hex != release_lock.asset_sha256:
            temporary_path.unlink(missing_ok=True)
            raise LockContractError(
                f"Downloaded asset digest mismatch for {release_lock.asset_name}: "
                f"expected {release_lock.asset_sha256}, got {digest_hex}."
            )

        temporary_path.replace(archive_path)

    def _ensure_extracted_archive(self, archive_path: Path, extract_dir: Path, force: bool) -> bool:
        if not force and extract_dir.exists() and any(extract_dir.iterdir()):
            return False

        # A plain mkdir (not tempfile's 0o700) so the directory, and the `app` it becomes,
        # inherits its parent's ACL (BUILTIN\Users read on Windows, #459).
        extract_dir.parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mktemp(prefix=".extract-", dir=str(extract_dir.parent)))
        temp_root.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    destination = (temp_root / member.filename).resolve()
                    if temp_root.resolve() not in destination.parents and destination != temp_root.resolve():
                        raise LockContractError("Archive contains an unsafe extraction path.")
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)

            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            temp_root.replace(extract_dir)
            return True
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def _verify_archive(self, release_lock: PoBReleaseLock, archive_path: Path) -> str:
        if not archive_path.exists():
            raise FileNotFoundError(f"Cached asset not found: {archive_path}")
        if archive_path.name != release_lock.asset_name:
            raise LockContractError(
                f"Cached asset name mismatch: expected {release_lock.asset_name}, got {archive_path.name}."
            )

        observed_size = archive_path.stat().st_size
        if observed_size != release_lock.asset_size:
            raise LockContractError(
                f"Cached asset size mismatch for {archive_path}: expected {release_lock.asset_size}, got {observed_size}."
            )

        digest = sha256_file(archive_path)
        if digest != release_lock.asset_sha256:
            raise LockContractError(
                f"Cached asset digest mismatch for {archive_path}: expected {release_lock.asset_sha256}, got {digest}."
            )
        return digest


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pbr")
    root_subparsers = parser.add_subparsers(dest="domain", required=True)

    pob_parser = root_subparsers.add_parser("pob", help="Manage the pinned Path of Building runtime.")
    pob_subparsers = pob_parser.add_subparsers(dest="command", required=True)

    pin_parser = pob_subparsers.add_parser("pin", help="Write a committed PoB lock from GitHub release metadata.")
    pin_group = pin_parser.add_mutually_exclusive_group(required=True)
    pin_group.add_argument("--version", help="Pin an explicit GitHub release tag.")
    pin_group.add_argument(
        "--latest-stable",
        action="store_true",
        help="Pin the latest GitHub release marked as stable.",
    )
    pin_parser.set_defaults(handler=_handle_pin)

    fetch_parser = pob_subparsers.add_parser("fetch", help="Fetch and extract the pinned release into local cache.")
    fetch_parser.add_argument("--force", action="store_true", help="Re-download and re-extract the local cache entry.")
    fetch_parser.set_defaults(handler=_handle_fetch)

    verify_parser = pob_subparsers.add_parser("verify", help="Verify the cached asset against the committed lock.")
    verify_parser.set_defaults(handler=_handle_verify)

    show_lock_parser = pob_subparsers.add_parser("show-lock", help="Show the current committed PoB lock.")
    show_lock_parser.set_defaults(handler=_handle_show_lock)

    return parser


def _handle_pin(manager: PoBReleaseManager, args: argparse.Namespace) -> dict[str, Any]:
    release_lock = manager.pin(version=args.version, latest_stable=args.latest_stable)
    return release_lock.to_dict()


def _handle_fetch(manager: PoBReleaseManager, args: argparse.Namespace) -> dict[str, Any]:
    return manager.fetch(force=args.force).to_dict()


def _handle_verify(manager: PoBReleaseManager, _: argparse.Namespace) -> dict[str, Any]:
    return manager.verify().to_dict()


def _handle_show_lock(manager: PoBReleaseManager, _: argparse.Namespace) -> dict[str, Any]:
    return manager.show_lock()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the pinned PoB release manager."""

    parser = build_parser()
    args = parser.parse_args(argv)
    manager = PoBReleaseManager()

    try:
        payload = args.handler(manager, args)
    except (FileNotFoundError, HTTPError, URLError, LockContractError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _print_json(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
