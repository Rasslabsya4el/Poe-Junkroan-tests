"""#967 the 17 builds of the reading queue, opened in PoB as delivered: checks A, B and C of the build check's
duration warnings, the 17-build table, and the proof that no number moves and what the checks cost.

One PobSession. Every build is audited twice from the same loaded XML: once with `audit_duration` taken out of the
chain and once with it; `audit_errors` (the error findings) and `ours` (the row's metric, read after the audit) must
be equal, and the extra PoB worker calls of the second run are counted. The tree-leaf analysis (`tree_leaves`) is
fed empty in both runs: it is another check and a long one, and both runs get the same input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
QUEUE = PROJECT_ROOT / "artifacts" / "readings" / "queue.json"

A_BUILDS = {"03 marauder_chieftain_no_blood_magic_imperial_staff s2", "ignite_penance_brand s4"}
C_BUILDS = {"stormbrand s6", "hit_penance_brand s6", "ignite_penance_brand s4", "summon_raging_spirits s6"}


def _build_file(row: dict) -> Path:
    run_dir = PROJECT_ROOT / row["run_dir"]
    if row.get("rank"):
        return run_dir / f"{row['ref']}.pob.txt"  # the Volcanic Fissure rows
    variant = f"-{row['variant']}" if row.get("variant") else ""
    return run_dir / f"{row['ref']}-s{row['seed']}{variant}.pob.txt"


def _check_of(detail: str) -> str:
    if "applications at once" in detail:
        return "A"
    if "Uptime" in detail:
        return "B"
    if "recasting" in detail:
        return "C"
    return "?"


@pytest.mark.pob
@needs_pob
@pytest.mark.skipif(not QUEUE.is_file(), reason="reading queue not present")
def test_the_17_reading_queue_builds(tmp_path: Path, monkeypatch, capsys) -> None:
    from junkroan.optimizer import audit as audit_module
    from junkroan.optimizer.audit import audit_build
    from junkroan.pob.session import PobSession, decode_import_code

    rows = json.loads(QUEUE.read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 17
    real_audit_duration = audit_module.audit_duration
    table: list[tuple[str, dict[str, list[str]], int, int, float, float, int, dict[str, int]]] = []

    with PobSession(run_id="test-967-duration-17", artifacts_root=tmp_path) as pob:
        inner = pob._adapter._inner
        actions: list[str] = []
        real_call = inner._call_worker

        def counting_call(handle, payload, **kwargs):
            actions.append(str(payload.get("action")))
            return real_call(handle, payload, **kwargs)

        monkeypatch.setattr(inner, "_call_worker", counting_call)

        for row in rows:
            name = f"{row['ref']} s{row['seed']}"
            xml = decode_import_code(_build_file(row).read_text(encoding="utf-8").strip())
            runs = {}
            for label, fn in (("without", lambda _pob: []), ("with", real_audit_duration)):
                monkeypatch.setattr(audit_module, "audit_duration", fn)
                pob.load_xml(xml)
                actions.clear()
                findings = audit_build(pob, tree_leaves=[])
                calls = list(actions)
                ours = float(pob.stats([row["metric"]])[row["metric"]])
                errors = sorted(f"{f.check}: {f.detail}" for f in findings if f.severity == "error")
                runs[label] = (findings, calls, ours, errors)
            monkeypatch.setattr(audit_module, "audit_duration", real_audit_duration)

            found = {"A": [], "B": [], "C": []}
            for finding in runs["with"][0]:
                if finding.check == "duration":
                    assert finding.severity == "warning"
                    found[_check_of(finding.detail)].append(finding.detail)
            # no number moves: the same errors, the same metric
            assert runs["with"][3] == runs["without"][3], name
            assert runs["with"][2] == runs["without"][2], name
            # the findings other than the duration ones are the same
            assert [f for f in runs["with"][0] if f.check != "duration"] == runs["without"][0], name
            extra: dict[str, int] = {}
            for action in runs["with"][1]:
                extra[action] = extra.get(action, 0) + 1
            for action in runs["without"][1]:
                extra[action] = extra.get(action, 0) - 1
            extra = {action: n for action, n in extra.items() if n}
            table.append((name, found, len(runs["with"][3]), len(runs["without"][3]), runs["with"][2], runs["without"][2], len(runs["with"][1]) - len(runs["without"][1]), extra))

    with capsys.disabled():
        print("\nbuild | A | B | C | audit_errors with/without | ours with/without | extra worker calls")
        for name, found, errors_with, errors_without, ours_with, ours_without, extra_calls, extra in table:
            print(f"{name} | {len(found['A'])} | {len(found['B'])} | {len(found['C'])} | {errors_with}/{errors_without} | {ours_with:.0f}/{ours_without:.0f} | {extra_calls} {extra}")
            for check in "ABC":
                for detail in found[check]:
                    print(f"    {check}: {detail}")

    warned = {check: {name for name, found, *_ in table if found[check]} for check in "ABC"}
    assert warned["A"] == A_BUILDS  # row 1
    assert warned["B"] == set()  # row 2
    assert warned["C"] == C_BUILDS  # row 3
    assert all(extra_calls <= 1 for *_, extra_calls, _ in table)  # row 5: the one `read_active_skill_stats` call
