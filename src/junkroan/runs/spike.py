"""Deterministic spike ladder (#406): steps 0..3 from a sampled snapshot stream.

Step 1 = start no new filler, 2 = stop a running filler, 3 = hold queued jobs.
The ladder never says anything about counted jobs; that is the daemon's side.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from junkroan.report_format import human_duration

NON_POB = ("claude", "owner", "system", "other")
MAX_STEP = 3


@dataclass(frozen=True)
class Lines:
    ram_free_mb_hard: float
    cpu_pct_soft: float
    window_s: float

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "Lines | None":
        keys = ("ram_free_mb_hard", "cpu_pct_soft", "window_s")
        if not cfg or any(cfg.get(k) is None for k in keys):
            return None
        return cls(*(float(cfg[k]) for k in keys))


@dataclass(frozen=True)
class Decision:
    step: int
    cause: str | None
    reason: str
    changed: bool = False


def _g(snap: dict, group: str, key: str) -> float:
    return float((snap.get("groups", {}).get(group) or {}).get(key, 0.0))


class Ladder:
    def __init__(self, lines: Lines):
        self.lines = lines
        self.step = 0
        self._samples: deque[tuple[float, dict]] = deque()
        self._last_change_s: float | None = None
        self._last_cond_s: float | None = None

    def _push(self, snap: dict, now_s: float) -> bool:
        """Add a sample, drop the ones older than the window; True when the window is full."""
        s = self._samples
        s.append((now_s, snap))
        cutoff = now_s - self.lines.window_s
        while len(s) > 1 and s[1][0] <= cutoff:
            s.popleft()
        return s[0][0] <= cutoff

    def _cause(self, cond: str) -> tuple[str, float, float]:
        """(group, rss_mb at the last sample, mean cpu_pct) of the chosen non-PoB group."""
        snaps = [x for _, x in self._samples]
        first, last = snaps[0], snaps[-1]
        if cond == "ram":
            rise = {g: _g(last, g, "rss_mb") - _g(first, g, "rss_mb") for g in NON_POB}
            if max(rise.values()) > 0:
                pick = max(NON_POB, key=lambda g: rise[g])
            else:
                pick = max(NON_POB, key=lambda g: _g(last, g, "rss_mb"))
        else:
            pick = max(NON_POB, key=lambda g: sum(_g(x, g, "cpu_pct") for x in snaps))
        mean_cpu = sum(_g(x, pick, "cpu_pct") for x in snaps) / len(snaps)
        return pick, _g(last, pick, "rss_mb"), mean_cpu

    def observe(self, snapshot: dict, now_s: float) -> Decision:
        ln = self.lines
        full = self._push(snapshot, now_s)
        snaps = [x for _, x in self._samples]
        ram = full and all(x["free_ram_mb"] < ln.ram_free_mb_hard for x in snaps)
        cpu = full and all(x["cpu_pct"] > ln.cpu_pct_soft for x in snaps)
        cond = "ram" if ram else "cpu" if cpu else None
        if cond:
            self._last_cond_s = now_s

        def since(t: float | None) -> float:
            return float("inf") if t is None else now_s - t

        old = self.step
        waited = since(self._last_change_s) >= ln.window_s
        if cond == "ram":
            if waited and self.step < MAX_STEP:
                self.step += 1
        elif cond == "cpu":
            if waited and self.step != 1:
                self.step += 1 if self.step < 1 else -1
        elif self.step > 0 and waited and since(self._last_cond_s) >= ln.window_s:
            self.step -= 1
        changed = self.step != old
        if changed:
            self._last_change_s = now_s

        win = human_duration(ln.window_s)
        last = snaps[-1]
        free_gb = f"{last['free_ram_mb'] / 1024:.1f} GB"
        if cond is None:
            reason = f"no sustained condition (free RAM {free_gb}, cpu {last['cpu_pct']:.0f}%)"
            if self.step:
                reason += f"; stepping down from step {self.step}"
            return Decision(self.step, None, reason, changed)
        cause, rss, mean_cpu = self._cause(cond)
        pob = sum(_g(last, g, "rss_mb") for g in ("pob_counted", "pob_filler")) / 1024
        pob_cpu = sum(_g(last, g, "cpu_pct") for g in ("pob_counted", "pob_filler"))
        if cond == "ram":
            head = f"ram: free RAM {free_gb} below {ln.ram_free_mb_hard / 1024:.1f} GB for {win}"
        else:
            head = (f"cpu: whole-PC {last['cpu_pct']:.0f}% above {ln.cpu_pct_soft:.0f}% "
                    f"for {win}; free RAM {free_gb}")
        reason = (f"{head}; cause {cause} (rss {rss / 1024:.1f} GB, mean cpu {mean_cpu:.0f}%); "
                  f"PoB share rss {pob:.1f} GB, cpu {pob_cpu:.0f}%; step {self.step}")
        return Decision(self.step, cause, reason, changed)
