"""`junkroan` without installing the package (every other entry point lives here too).

    python scripts/junkroan.py build --skill "Storm Brand" --mode hit --ascendancy Inquisitor --level 80 --dry-run

`python -m junkroan.cli ...` needs `junkroan` on sys.path, i.e. `pip install -e .`
(which also puts the `junkroan` console script on PATH). This launcher is the same
CLI with `src/` prepended to sys.path, so a fresh checkout or worktree runs it as is.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if __name__ != "__main__":
    # Loaded as a module (scripts/ ahead of src/ on sys.path, #732): step aside. Replace this file in
    # sys.modules with the real package; the import system returns what sys.modules[name] holds after
    # this body ran, so `import junkroan` and `import junkroan.<sub>` resolve to src/junkroan/.
    import importlib.util

    _pkg = ROOT / "src" / "junkroan"
    _spec = importlib.util.spec_from_file_location(
        "junkroan", _pkg / "__init__.py", submodule_search_locations=[str(_pkg)]
    )
    _real = importlib.util.module_from_spec(_spec)
    sys.modules["junkroan"] = _real
    _spec.loader.exec_module(_real)
else:
    from junkroan.cli import main

    raise SystemExit(main())
