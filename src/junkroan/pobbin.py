"""Upload PoB import codes to pobb.in, with the benchmark run's policy (#572)."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = REPO_ROOT / "var" / "pobbin" / "ids.json"
UPLOAD_URL = "https://pobb.in/pob/"
USER_AGENT = "junkroan-benchmark"


class HttpStatusError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def page_url(build_id: str) -> str:
    return "https://pobb.in/" + build_id


def upload_code(code: str, *, timeout: float = 15.0) -> str:
    """One upload attempt, no retry. Returns the build id."""
    req = urllib.request.Request(
        UPLOAD_URL,
        data=code.encode("utf-8"),
        headers={"User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        raise HttpStatusError(e.code) from e
    if not body:
        raise ValueError("empty reply")
    return body


def _key(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _ok(build_id: str) -> dict:
    return {"pobbin_id": build_id, "pobbin_url": page_url(build_id)}


class PobbinRun:
    def __init__(self, upload: Callable[[str], str], cache_path: Path = DEFAULT_CACHE):
        self._upload = upload
        self.cache_path = Path(cache_path)
        self.offline: str | None = None
        self.calls = 0
        self._cache = self._read_cache()

    def _read_cache(self) -> dict[str, str]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _store(self, key: str, build_id: str) -> None:
        self._cache[key] = build_id
        try:
            merged = self._read_cache()
            merged[key] = build_id
            self._cache.update(merged)
            folder = self.cache_path.parent
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / f"{self.cache_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
            tmp.write_text(json.dumps(merged), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def _call(self, code: str) -> str:
        self.calls += 1
        return self._upload(code)

    def upload(self, code: str, stem: str) -> dict:
        key = _key(code)
        if key in self._cache:
            return _ok(self._cache[key])
        if self.offline:
            return {"pobbin_error": f"skipped: offline since {self.offline}"}
        try:
            try:
                build_id = self._call(code)
            except Exception as e:
                if (isinstance(e, HttpStatusError) and e.status >= 500) or (
                    isinstance(e, OSError)
                ):
                    build_id = self._call(code)
                else:
                    raise
        except Exception as e:
            if isinstance(e, HttpStatusError):
                reason = str(e)
            else:
                reason = f"{type(e).__name__}: {e}"
            reason = reason[:200]
            if isinstance(e, OSError):
                self.offline = f"{stem}: {reason}"
            return {"pobbin_error": reason}
        self._store(key, build_id)
        return _ok(build_id)

    def retry_pass(self, items: list[tuple[str, str]]) -> dict[str, dict]:
        fixed: dict[str, dict] = {}
        for stem, code in items:
            key = _key(code)
            if key in self._cache:
                fixed[stem] = _ok(self._cache[key])
                continue
            try:
                build_id = self._call(code)
            except Exception:
                break
            self._store(key, build_id)
            fixed[stem] = _ok(build_id)
        return fixed
