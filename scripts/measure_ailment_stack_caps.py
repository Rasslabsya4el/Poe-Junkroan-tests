"""Measure D78's conservative ailment-stack caps on benchmark authors.

Run with the pinned interpreter, one PoB session at a time:
  junkroan.exe scripts/measure_ailment_stack_caps.py
  junkroan.exe scripts/measure_ailment_stack_caps.py poison_spectral_throw

Each row prepares the author through benchmark.prepare_author twice: once with
the cap parameter off and once on. The output names every reference that moves
with its lane before/after/factor and the stacks the capped lane counts. Rows
without a stacking ailment must be byte-for-byte identical in their lane value.
"""

from __future__ import annotations

import argparse
import sys
from math import ceil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import FIXTURES, fixture_slugs, prepare_author  # noqa: E402
from junkroan.optimizer.config_rules import derive_config  # noqa: E402
from junkroan.optimizer.ramp import ramp_dps, ramp_context  # noqa: E402
from junkroan.optimizer.ramp_inputs import uncapped_ailment_stack_xml  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402


def _measure(pob: PobSession, slug: str, *, cap_ailment_stacks: bool) -> tuple[str, float, dict[str, int]]:
    prepared = prepare_author(
        pob,
        slug,
        log=lambda _line: None,
        cap_ailment_stacks=cap_ailment_stacks,
    )
    value = float(pob.stats((prepared.stat,))[prepared.stat])
    derived = derive_config(pob, prefer_rules=True, cap_ailment_stacks=cap_ailment_stacks)
    stacks = {name: cap.counted for name, cap in derived.ailment_stack_caps.items() if cap.limited}
    return prepared.stat, value, stacks


def _poison_states(pob: PobSession) -> None:
    """The three D78 states of Poison Spectral Throw under its benchmark lane."""

    prepared = prepare_author(pob, "poison_spectral_throw", log=lambda _line: None, cap_ailment_stacks=False)
    keys = ("PoisonStacks", "PoisonDPS", "TotalPoisonDPS", "CombinedDPS", "TotalDPS")
    before = pob.stats(keys)
    derived = derive_config(pob, prefer_rules=True, cap_ailment_stacks=True)
    poison = derived.ailment_stack_caps["poison"]
    less = int(ceil((1.0 - poison.counted / poison.steady) * 100.0 - 1e-9))
    from junkroan.optimizer.ramp_inputs import apply_custom_mods

    apply_custom_mods(pob, [(f"{less}% less Damage with Poison", "measurement: old D78 poison surrogate")], replace_ailment_stacks=True)
    surrogate = pob.stats(keys)
    prepare_author(pob, "poison_spectral_throw", log=lambda _line: None, cap_ailment_stacks=True)
    native = pob.stats(keys)
    print("\nPoison Spectral Throw, benchmark author under conservative lane:")
    print("| state | PoisonStacks | PoisonDPS | TotalPoisonDPS | CombinedDPS | TotalDPS |")
    print("|---|---:|---:|---:|---:|---:|")
    for label, stats in (("before cap", before), (f"old {less}% less surrogate", surrogate), ("native PoisonStackLimit", native)):
        print(f"| {label} | {stats['PoisonStacks']:.3f} | {stats['PoisonDPS']:,.1f} | {stats['TotalPoisonDPS']:,.1f} | {stats['CombinedDPS']:,.1f} | {stats['TotalDPS']:,.1f} |")
    print(f"native cap: {poison.counted} stacks of {poison.steady:.3f}; multiplierPoisonOnEnemy = {derived.conservative.inputs.get('multiplierPoisonOnEnemy', 'off')}")


def _pinnacle_line(pob: PobSession, slug: str) -> None:
    """The D78 report-only 10 s projection for a prepared benchmark author."""

    prepared = prepare_author(pob, slug, log=lambda _line: None, cap_ailment_stacks=True)
    ctx = ramp_context(prepared.objective)
    if ctx is None:
        print(f"{slug}: no ramp context")
        return
    snapshot = pob.export_xml()
    uncapped = uncapped_ailment_stack_xml(snapshot)
    if uncapped != snapshot:
        pob.load_xml(uncapped)
    stats = pob.stats(prepared.objective.stat_keys)
    pob.load_xml(snapshot)
    value = ramp_dps(stats, prepared.stat, 10.0, ctx)
    print(f"{slug}: pinnacle boss ramp (10 s, report only): {prepared.stat} {value:,.0f}" if value is not None else f"{slug}: no pinnacle projection")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slugs", nargs="*", help="reference slugs; defaults to all Tuadh fixtures")
    parser.add_argument("--poison-states", action="store_true", help="also print the uncapped, old-surrogate, and native poison-cap states")
    parser.add_argument("--pinnacle", action="store_true", help="also print report-only 10 s ramp lines for the selected references")
    args = parser.parse_args()
    slugs = args.slugs or fixture_slugs(FIXTURES)
    moved: list[tuple[str, str, float, float, dict[str, int]]] = []
    unchanged: list[str] = []
    with PobSession(run_id="measure-ailment-stack-caps") as pob:
        for slug in slugs:
            stat, before, _ = _measure(pob, slug, cap_ailment_stacks=False)
            capped_stat, after, stacks = _measure(pob, slug, cap_ailment_stacks=True)
            if capped_stat != stat:
                raise RuntimeError(f"{slug}: objective changed from {stat} to {capped_stat}")
            if abs(after - before) <= 1e-6 * max(1.0, abs(before)):
                unchanged.append(slug)
            else:
                moved.append((slug, stat, before, after, stacks))
    print("| reference | stat | before cap | with cap | factor | stacks counted |")
    print("|---|---:|---:|---:|---:|---|")
    for slug, stat, before, after, stacks in moved:
        counted = ", ".join(f"{name} {n}" for name, n in sorted(stacks.items())) or "none"
        print(f"| {slug} | {stat} | {before:,.0f} | {after:,.0f} | {after / before:.3f} | {counted} |")
    print(f"unchanged ({len(unchanged)}): {', '.join(unchanged)}")
    if args.poison_states:
        with PobSession(run_id="measure-poison-stack-states") as pob:
            _poison_states(pob)
    if args.pinnacle:
        with PobSession(run_id="measure-ailment-stack-pinnacle") as pob:
            for slug in slugs:
                _pinnacle_line(pob, slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
