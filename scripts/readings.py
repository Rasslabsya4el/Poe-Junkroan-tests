"""Reading queue: artifacts/readings/queue.json (issue #591). No PoB, no network."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUEUE = ROOT / "artifacts" / "readings" / "queue.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("rows", [])


def _save(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"updated": _now(), "rows": rows}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def _key(r: dict) -> tuple:
    return (r["run_dir"], r["ref"], r["seed"], r["variant"])


def upload_code(code: str) -> str:
    """One pobb.in upload the way benchmark.py --pobbin-backfill does it (retry on 429)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "src"))
    import benchmark
    return benchmark._upload_waiting_on_429(code)


def _report_rank_row(report: Path, rank: int) -> dict:
    """The rank's row of the report's rank table, as {column: cell}."""
    head = None
    for line in report.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            head = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = cells if cells[:1] == ["rank"] else None
        elif head and cells[0] == str(rank):
            return dict(zip(head, cells))
    raise ValueError(f"rank {rank} not in the rank table of {report}")


def cmd_add_build(a, qpath: Path) -> int:
    """A finished `junkroan build` request folder: one row for the build of rank --rank."""
    build = Path(a.build)
    build_abs = build if build.is_absolute() else ROOT / build
    rr = _report_rank_row(build_abs / "report.md", a.rank)
    js = sorted(build_abs.glob(f"{a.rank:02d} *.json"))
    if len(js) != 1:
        print(f"error: want one '{a.rank:02d} *.json' in {build_abs}, found {len(js)}", file=sys.stderr)
        return 2
    d = json.loads(js[0].read_text(encoding="utf-8"))
    txt = js[0].with_suffix(".pob.txt")
    m = re.search(r"Removing it: (\w+)", d["explanation"]) or re.search(r"ramp \(\d+ s\): (\w+)", d["summary"])
    code = txt.read_bytes().decode("utf-8")
    pid = upload_code(code).strip()
    row = {
        "run_dir": a.build.replace("\\", "/"),
        "run_name": a.run_name,
        "ref": d["stem"],
        "seed": d["seed"],
        "variant": "",
        "pobbin_id": pid,
        "author_pobbin_id": None,
        "ratio_pct": None,
        "metric": m.group(1),
        "ours": round(d["value"]),
        "author": None,
        "life": int(d["final"]["Life"]),
        "stop": None,
        "rank": a.rank,
        "audit": rr.get("audit"),
        "floors": rr.get("floors"),
        "note": " ".join(a.note.split()),
        "added_at": _now(),
        "added_by": a.by,
    }
    rows = [r for r in _load(qpath) if _key(r) != _key(row)]
    rows.append(row)
    _save(qpath, rows)
    return 0


def _audit_text(audit) -> str | None:
    """A row file's `audit` list as a request row's text, '<E> errors / <W> warnings'; None when there is no list."""
    if not isinstance(audit, list):
        return None
    e = sum(1 for x in audit if str(x).startswith("[error]"))
    w = sum(1 for x in audit if str(x).startswith("[warning]"))
    return f"{e} errors / {w} warnings"


def cmd_add(a, qpath: Path) -> int:
    if a.build:
        if a.rank is None:
            print("error: --build needs --rank", file=sys.stderr)
            return 2
        return cmd_add_build(a, qpath)
    if not (a.run and a.ref and a.seed is not None):
        print("error: add needs --build + --rank, or --run + --ref + --seed", file=sys.stderr)
        return 2
    run = Path(a.run)
    run_abs = run if run.is_absolute() else ROOT / run
    suffix = f"-{a.variant}" if a.variant else ""
    rf = run_abs / "rows" / f"{a.ref}-s{a.seed}{suffix}.json"
    if not rf.is_file():
        print(f"error: row file not found: {rf}", file=sys.stderr)
        return 2
    d = json.loads(rf.read_text(encoding="utf-8"))
    pid = d.get("pobbin_id") or None
    if pid is None:
        print(f"warning: no pobbin_id in {rf}", file=sys.stderr)
    url = d.get("author_pobbin_url")
    aid = url.rstrip("/").rsplit("/", 1)[-1] if url else None
    row = {
        "run_dir": a.run.replace("\\", "/"),
        "run_name": a.run_name,
        "ref": a.ref,
        "seed": a.seed,
        "variant": a.variant,
        "pobbin_id": pid,
        "author_pobbin_id": aid,
        "ratio_pct": round(d["ratio_lane"] * 100),
        "metric": d["stat"],
        "ours": round(d["ours"]),
        "author": round(d["author_lane"]),
        "life": int(d["ours_life"]),
        "stop": d["loop_stop"],
        "audit": _audit_text(d.get("audit")),
        "floors": None,  # a benchmark row has no request-style floors result; the pane reads None as not known
        "note": " ".join(a.note.split()),
        "added_at": _now(),
        "added_by": a.by,
    }
    rows = [r for r in _load(qpath) if _key(r) != _key(row)]
    rows.append(row)
    _save(qpath, rows)
    return 0


def cmd_fill_audit(a, qpath: Path) -> int:
    """Fills `audit` in place on the queue rows of one benchmark run that lack it (added before it was written)."""
    run = Path(a.run)
    run_abs = run if run.is_absolute() else ROOT / run
    key = a.run.replace("\\", "/")
    rows = _load(qpath)
    filled = missing = 0
    for r in rows:
        if r["run_dir"] != key or r.get("audit") is not None:
            continue
        suffix = f"-{r['variant']}" if r.get("variant") else ""
        rf = run_abs / "rows" / f"{r['ref']}-s{r['seed']}{suffix}.json"
        if not rf.is_file():
            print(f"warning: row file not found: {rf}", file=sys.stderr)
            missing += 1
            continue
        text = _audit_text(json.loads(rf.read_text(encoding="utf-8")).get("audit"))
        if text is None:
            missing += 1
            continue
        r["audit"] = text
        filled += 1
    if filled:
        _save(qpath, rows)
    print(f"{filled} filled, {missing} not filled")
    return 0


def cmd_remove(a, qpath: Path) -> int:
    rows = _load(qpath)
    keep = []
    for r in rows:
        hit = (r["ref"] == a.ref
               and (a.seed is None or r["seed"] == a.seed)
               and (a.variant is None or r["variant"] == a.variant)
               and (a.run is None or r["run_dir"] == a.run.replace("\\", "/")))
        if not hit:
            keep.append(r)
    n = len(rows) - len(keep)
    if n:
        _save(qpath, keep)
    print(n)
    return 0


def cmd_list(a, qpath: Path) -> int:
    # newest first; rows added in the same second: the later-written one first
    rows = [r for _, r in sorted(enumerate(_load(qpath)), key=lambda t: (t[1]["added_at"], t[0]), reverse=True)]
    if rows:
        tab = [("ref", "seed", "% of author", "stop", "note")]
        for r in rows:
            s = f"{r['seed']}-{r['variant']}" if r["variant"] else str(r["seed"])
            tab.append((r["ref"], s, "-" if r["ratio_pct"] is None else str(r["ratio_pct"]),
                        r["stop"] or "-", r["note"]))
        w = [max(len(t[i]) for t in tab) for i in range(5)]
        for t in tab:
            print("  ".join(c.ljust(w[i]) for i, c in enumerate(t)).rstrip())
    print(f"{len(rows)} builds")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="readings")
    p.add_argument("--queue", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add")
    s.add_argument("--run")
    s.add_argument("--ref")
    s.add_argument("--seed", type=int)
    s.add_argument("--build", help="folder of a finished `junkroan build` request (with --rank)")
    s.add_argument("--rank", type=int)
    s.add_argument("--variant", default="")
    s.add_argument("--note", required=True)
    s.add_argument("--run-name", default="")
    s.add_argument("--by", default="brain")
    s = sub.add_parser("remove")
    s.add_argument("--ref", required=True)
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--variant", default=None)
    s.add_argument("--run", default=None)
    sub.add_parser("list")
    s = sub.add_parser("fill-audit", help="fill the missing audit of a benchmark run's queue rows, in place")
    s.add_argument("--run", required=True)
    a = p.parse_args(argv)
    qpath = Path(a.queue) if a.queue else DEFAULT_QUEUE
    return {"add": cmd_add, "remove": cmd_remove, "list": cmd_list, "fill-audit": cmd_fill_audit}[a.cmd](a, qpath)


if __name__ == "__main__":
    sys.exit(main())
