"""A fake benchmark build for the yield tests (#621): no PoB. It walks named stages as short sleeps and calls
`yield_probe.check(stage)` between them, like the optimizer. Importable and picklable, so a real
ProcessPoolExecutor (spawn on Windows) can run it. Time is scaled by `JUNKROAN_BENCH_TIME_SCALE`
(fake seconds per real second), which `benchmark.armed_build` reads for its elapsed and the 10-minute rule."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
from junkroan.optimizer import yield_probe  # noqa: E402

STEP_FAKE_SECONDS = 30.0  # one stage = half a fake minute


def _log_event(out_dir: Path, kind: str, stem: str) -> None:
    # one file per event: two workers appending to one file lose lines on Windows (a text-mode "a" append is not atomic)
    events = out_dir / "events"
    events.mkdir(exist_ok=True)
    stamp = time.time()
    (events / f"{stamp:.6f}-{os.getpid()}-{kind}-{stem}.ev").write_text(f"{stamp:.4f} {kind} {stem}", encoding="utf-8")


def fake_build(slug: str, *, log_path: str, seed: int, n_stages: int, bench_root: str, keystone: str | None = None) -> dict:
    """Run `n_stages` stages of half a fake minute; the last one is `fixed point check`."""

    out_dir = Path(log_path).parent.parent
    variant = f"no {keystone}" if keystone else ""
    stem = benchmark.result_stem({"slug": slug, "seed": seed, "variant": variant})
    scale = benchmark.time_scale()
    _log_event(out_dir, "start", stem)

    def body() -> dict:
        t0 = time.perf_counter()
        for i in range(n_stages):
            name = "fixed point check" if i == n_stages - 1 else f"stage {i}"
            yield_probe.check(name)
            time.sleep(STEP_FAKE_SECONDS / scale)
        return {"ok": True, "slug": slug, "seed": seed, "variant": variant, "seconds": (time.perf_counter() - t0) * scale}

    r = benchmark.armed_build(slug, log_path=log_path, seed=seed, variant=variant, loop_seconds=None, body=body, bench_root=Path(bench_root))
    _log_event(out_dir, "deferred" if r.get("deferred") else "end", stem)
    return r


def warm(_: int = 0) -> int:
    return os.getpid()
