"""The catalogue record of #1147: one canonical JSON line per (bundle, stand) measurement.

A record is written by the measuring code and read by nothing here. The gain is derived from the two PoB numbers,
never supplied. `import_code_for` imports the PoB session lazily so this module loads without PoB.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

CATALOGUE_PATH = Path(__file__).resolve().parents[3] / "artifacts" / "catalogue" / "day1.jsonl"

METRICS = ("CombinedDPS", "FullDPS")
VERDICTS = ("take", "drop", "climbing", "does_not_fit")
DOES_NOT_FIT = "does_not_fit"

# Fields a does_not_fit record must leave null (no PoB call was made).
_NULL_WHEN_DOES_NOT_FIT = ("value", "base_value", "gain", "import_code")


def _strictly_sorted(bundle: Sequence[Any]) -> bool:
    return all(earlier < later for earlier, later in zip(bundle, bundle[1:]))


@dataclasses.dataclass(frozen=True)
class CatalogueRecord:
    bundle: list
    edge: dict | None
    stand: str
    stand_sha256: str
    metric: str
    base_value: float | None
    value: float | None
    verdict: str
    reason: str
    seconds: float
    seed: int
    passes: int
    commit: str
    import_code: str | None
    gain: float | None = dataclasses.field(default=None, init=False)

    def __post_init__(self) -> None:
        for name in ("bundle", "stand", "stand_sha256", "metric", "verdict", "reason", "seconds", "seed",
                     "passes", "commit"):
            if getattr(self, name) is None:
                raise ValueError(f"catalogue record field {name} is missing")
        if not isinstance(self.bundle, (list, tuple)) or not self.bundle:
            raise ValueError("catalogue record bundle must be a non-empty list of node ids")
        if not _strictly_sorted(self.bundle):
            raise ValueError(f"catalogue record bundle must be sorted and unique: {self.bundle!r}")
        if self.metric not in METRICS:
            raise ValueError(f"catalogue record metric must be one of {METRICS}: {self.metric!r}")
        if self.verdict not in VERDICTS:
            raise ValueError(f"catalogue record verdict must be one of {VERDICTS}: {self.verdict!r}")
        object.__setattr__(self, "bundle", list(self.bundle))

        if self.verdict == DOES_NOT_FIT:
            for name in _NULL_WHEN_DOES_NOT_FIT:
                if getattr(self, name) is not None:
                    raise ValueError(f"a does_not_fit catalogue record has no PoB call: {name} must be null")
            if self.seconds != 0:
                raise ValueError("a does_not_fit catalogue record has seconds 0")
            return

        for name in ("base_value", "value", "import_code"):
            if getattr(self, name) is None:
                raise ValueError(f"a measured catalogue record needs {name}")
        if self.base_value != 0:
            object.__setattr__(self, "gain", (self.value - self.base_value) / self.base_value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle": list(self.bundle),
            "edge": self.edge,
            "stand": self.stand,
            "stand_sha256": self.stand_sha256,
            "metric": self.metric,
            "base_value": self.base_value,
            "value": self.value,
            "gain": self.gain,
            "verdict": self.verdict,
            "reason": self.reason,
            "seconds": float(self.seconds),
            "seed": self.seed,
            "passes": self.passes,
            "commit": self.commit,
            "import_code": self.import_code,
        }

    def to_line(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def same_apart_from_seconds(first: str, second: str) -> bool:
    """Whether two record lines are the same measurement, ignoring the wall-clock `seconds`."""

    left, right = json.loads(first), json.loads(second)
    left.pop("seconds", None)
    right.pop("seconds", None)
    return left == right


def append(path: Path | str, record: CatalogueRecord) -> None:
    """Append one record as one line, creating the folder on the first write."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(record.to_line() + "\n")


def stand_sha256(path: Path | str) -> str:
    """SHA-256 of a stand file's bytes, as the record stores it."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def import_code_for(pob: Any) -> str:
    """The pasteable import code of a PoB session's build."""

    from junkroan.pob.session import encode_import_code

    return encode_import_code(pob.export_xml())


__all__ = [
    "CATALOGUE_PATH",
    "CatalogueRecord",
    "METRICS",
    "VERDICTS",
    "append",
    "import_code_for",
    "same_apart_from_seconds",
    "stand_sha256",
]
