"""Audit one or more builds (PoB XML or import code files) by machine: duplicate
mastery effects, legacy / out-of-rails uniques, gem levels, every missed floor
and relation with numbers.

    python scripts/audit_build.py artifacts/search-fireball/*.pob.txt
    python scripts/audit_build.py --skeleton "artifacts/search-x/01 name.json" "artifacts/replay/<run>/builds/01 name.xml"

The skeleton of a build is read from the sidecar JSON beside it (`01 name.pob.txt` -> `01 name.json`) or from `--skeleton`;
the empty-socket check needs it and is skipped, with a line saying so, when there is none (#1156).
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.audit import audit_build, skeleton_beside  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    explicit = None
    if "--skeleton" in args:
        at = args.index("--skeleton")
        if at + 1 >= len(args):
            print("error: --skeleton needs a file", file=sys.stderr)
            return 3
        explicit = Path(args[at + 1])
        del args[at:at + 2]
    paths = [Path(p) for arg in args for p in (glob.glob(arg) or [arg])]
    if explicit is not None and len(paths) != 1:
        print(f"error: --skeleton applies to exactly one build, got {len(paths)}", file=sys.stderr)
        return 3
    rails = Rails.load()
    worst = 0
    with PobSession(run_id="audit") as pob:
        for path in paths:
            text = path.read_text(encoding="utf-8").strip()
            pob.load_xml(text if text.startswith("<") else decode_import_code(text))
            skeleton = skeleton_beside(path, explicit)
            findings = audit_build(pob, rails=rails, skeleton=skeleton)
            print(f"== {path.name}: {len(findings)} findings")
            if skeleton is None:
                print("   no skeleton (no sidecar JSON, no --skeleton): the empty-socket check is skipped")
            for f in findings:
                print("  ", f)
                worst = max(worst, 2 if f.severity == "error" else 1)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
