"""Repeat-on-demand loop for #746: the hang of `test_two_concurrent_merges_serialize_through_the_lock`
(tests/test_agentops_merge.py:166-209), a merge that waits on a merge lock nobody holds.

The scenario is the test's own body (two threads of one pid, two `run_merge` calls on one lock path,
the same world helpers imported from the test module); only its bounds are parameters, so a hang shows
in under a minute: `--lock-timeout` (the test's 600 s) and `--stall` (a thread dead this long while its
sibling is still inside `MergeLock._acquire` = a hang). It changes no production code: three
`MergeLock`/`merge` functions are wrapped in-process to note what they returned.

    python scripts/repro_746.py --children 2 --burners 2 --stop-hangs 3 --minutes 30

On a hang a child writes one JSON record to ``--out`` (the lock file's state, the queue and batch
directories, the waiter's last `_is_head` / `holder_is_live` answers, the waiter's own stack) and exits;
the parent restarts it, and stops at ``--stop-hangs`` hangs, ``--minutes`` or ``--max-runs``.
Durations in the summary go through `junkroan.report_format.human_duration`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
sys.path.insert(0, str(ROOT / "tests"))  # test_agentops_merge imports as a plain module

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# -- the child: runs the scenario until the first hang -------------------------------------------

def _snapshot_file(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"state": "missing"}
    except OSError as exc:
        return {"state": f"present, OSError {exc!r}"}
    try:
        json.loads(text)
        return {"state": "present+readable", "content": text}
    except ValueError:
        return {"state": "present+unreadable", "content": text}


def _dir_snapshot(d: Path, pid_alive) -> list[dict]:
    out = []
    try:
        names = sorted(d.iterdir(), key=lambda t: t.name)
    except OSError as exc:
        return [{"error": repr(exc)}]
    for t in names:
        item = {"name": t.name}
        try:
            item["content"] = t.read_text(encoding="utf-8")
        except OSError as exc:
            item["content"] = f"<{exc!r}>"
        parts = t.name.split("-")
        if len(parts) > 1 and parts[1].isdigit():
            item["pid"] = int(parts[1])
            item["pid_alive"] = pid_alive(int(parts[1]))
        out.append(item)
    return out


def child_main(args) -> int:
    import test_agentops_merge as T  # the test module's own helpers (git world, suite command)
    from tools.agentops import merge as merge_module
    from tools.agentops.merge import MergeLock, run_merge
    from tools.agentops.util import pid_alive

    # what the test file's autouse fixtures do, once for the whole child
    scratch_root = Path(tempfile.mkdtemp(prefix=f"c{args.child}-", dir=args.out))
    merge_module.SUITE_OUTPUT_DIR = scratch_root / "_autoprotect_merge_suite"
    merge_module.MERGE_LOG_PATH = scratch_root / "_autoprotect_merge.log"
    green = f'"{sys.executable}" -c "pass"'
    merge_module.resolve_suite_cmd = lambda explicit=None: explicit or green

    # wrappers: note what the waiter's checks answered (production code is not edited)
    tstate: dict[int, dict] = {}  # thread ident -> {"phase", "ticket", "is_head", "live"}
    orig_acquire, orig_is_head = MergeLock._acquire, MergeLock._is_head
    orig_live = merge_module.holder_is_live

    def acquire(self, ticket, max_age_seconds):
        st = tstate.setdefault(threading.get_ident(), {})
        st.update(phase="in _acquire", ticket=str(ticket), lock=self, is_head=None, live=[], t0=time.time())
        try:
            return orig_acquire(self, ticket, max_age_seconds)
        finally:
            st["phase"] = "left _acquire"

    def is_head(self, ticket):
        r = orig_is_head(self, ticket)
        st = tstate.setdefault(threading.get_ident(), {})
        st["is_head"] = (r, time.time())
        return r

    def live(pid, started, **kw):
        r = orig_live(pid, started, **kw)
        st = tstate.setdefault(threading.get_ident(), {})
        st.setdefault("live", []).append((pid, started, r, time.time()))
        del st["live"][:-5]
        return r

    MergeLock._acquire, MergeLock._is_head, merge_module.holder_is_live = acquire, is_head, live

    # every failed unlink of a queue ticket (`_take`'s `finally` swallows an OSError there): noted, then re-raised
    unlink_errors: list[dict] = []
    orig_unlink = Path.unlink

    def unlink(self, *a, **kw):
        try:
            return orig_unlink(self, *a, **kw)
        except OSError as exc:
            if self.parent.name.endswith((".queue", ".batch")):
                unlink_errors.append({"file": self.name, "dir": self.parent.name, "exc": repr(exc),
                                      "thread": threading.current_thread().name, "t": time.time()})
            raise

    Path.unlink = unlink

    n = 0
    while True:
        n += 1
        tmp_path = Path(tempfile.mkdtemp(prefix=f"r{n}-", dir=scratch_root))
        bare, checkout = T._world(tmp_path)
        T._push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
        T._push_branch(bare, tmp_path, "worker-b", "feature-b", "b.py", "b = 1\n")
        T._git("fetch", "-q", "origin", cwd=checkout)
        lock_path = tmp_path / "merge.lock"
        results: dict[str, object] = {}
        tstate.clear()
        unlink_errors.clear()

        def run(name, branch):
            results[name] = run_merge(
                f"origin/{branch}", T.suite_cmd(tmp_path / f"counter-{name}.txt", tmp_path / f"flag-{name}.txt"),
                cwd=checkout, lock_path=lock_path, lock_timeout=args.lock_timeout)

        caps = {k: T._ThreadCapture(lambda k=k: run(k, f"feature-{k}")) for k in "ab"}
        threads = {k: threading.Thread(target=caps[k], name=f"merge-{k}", daemon=True) for k in "ab"}
        t_start = time.time()
        for t in threads.values():
            t.start()
        first_dead_at: float | None = None
        hang = False
        while True:
            alive = [t for t in threads.values() if t.is_alive()]
            if not alive:
                break
            if len(alive) < 2 and first_dead_at is None:
                first_dead_at = time.time()
            if first_dead_at is not None and time.time() - first_dead_at > args.stall:
                survivor = next(t for t in threads.values() if t.is_alive())
                # a hang = the survivor still waits inside `_acquire`; one that left it is a slow merge, not this bug
                if tstate.get(survivor.ident, {}).get("phase") == "in _acquire":
                    hang = True
                    break
            if time.time() - t_start > args.hard:
                hang = True
                break
            time.sleep(0.2)
        if not hang:
            for c in caps.values():
                c.reraise()
            ra, rb = results["a"], results["b"]
            assert ra.ok and rb.ok, (ra.message, rb.message)
            shutil.rmtree(tmp_path, ignore_errors=True)
            print(json.dumps({"child": args.child, "run": n, "seconds": round(time.time() - t_start, 1),
                              "hang": False}), flush=True)
            continue

        # ---- a hang: name the check that kept the survivor out, and the lock's state ----
        frames = sys._current_frames()
        rec: dict = {"child": args.child, "run": n, "hang": True, "tmp": str(tmp_path),
                     "seconds_since_start": round(time.time() - t_start, 1),
                     "threads": {}}
        lock_file = _snapshot_file(lock_path)
        queue_dir = lock_path.with_name(lock_path.name + ".queue")
        batch_dir = lock_path.with_name(lock_path.name + ".batch")
        rec["lock_file"] = lock_file
        rec["queue"] = _dir_snapshot(queue_dir, pid_alive)
        rec["batch"] = _dir_snapshot(batch_dir, pid_alive)
        rec["holding"] = _snapshot_file(lock_path.with_name(lock_path.name + ".holding"))
        rec["cwd_lock_file"] = _snapshot_file(lock_path.with_name(lock_path.name + ".cwd"))
        rec["own_pid"] = os.getpid()
        rec["unlink_errors_on_queue_or_batch"] = list(unlink_errors)
        for k, t in threads.items():
            st = tstate.get(t.ident, {})
            info = {"alive": t.is_alive(), "result": None if k not in results else str(results[k].message),
                    "exc": repr(caps[k].exc) if caps[k].exc else None}
            if st:
                info["phase"] = st.get("phase")
                info["ticket"] = Path(st.get("ticket", "")).name
                info["last_is_head"] = st.get("is_head")
                info["last_holder_is_live"] = st.get("live")
            if t.is_alive() and t.ident in frames:
                info["stack"] = "".join(traceback.format_stack(frames[t.ident])[-4:])
            rec["threads"][k] = info
            # re-evaluate the two checks at merge.py:687-690 for the survivor, without unlinking anything
            if t.is_alive() and st.get("phase") == "in _acquire":
                ticket = Path(st["ticket"])
                claim_file = batch_dir / f"{ticket.name}.claim"
                result_file = batch_dir / f"{ticket.name}.result"
                ev: dict = {"ticket_exists": ticket.exists(), "result_file_exists": result_file.exists(),
                            "claim_file_exists": claim_file.exists()}
                claimed = False
                if claim_file.exists():
                    try:
                        claim = json.loads(claim_file.read_text(encoding="utf-8"))
                        ev["claim"] = claim
                        claimed = isinstance(claim, dict) and bool(orig_live(claim.get("pid"), claim.get("started")))
                    except (OSError, ValueError) as exc:
                        ev["claim_unreadable"] = repr(exc)
                ev["claimed (merge.py:687)"] = claimed
                names = sorted(queue_dir.iterdir(), key=lambda x: x.name) if queue_dir.exists() else []
                ev["queue_order"] = [x.name for x in names]
                head = None
                for x in names:
                    try:
                        pid = int(x.name.split("-")[1])
                    except (IndexError, ValueError):
                        pid = 0
                    if x == ticket or pid_alive(pid):
                        head = x.name
                        break
                ev["head_ticket_by_replica (merge.py:689, live pids)"] = head
                ev["not_head (merge.py:689)"] = head is not None and head != ticket.name
                ev["blocking_check"] = ("claimed -> raise FileExistsError at merge.py:688" if claimed else
                                        "not _is_head(ticket) -> raise FileExistsError at merge.py:690"
                                        if ev["not_head (merge.py:689)"] else
                                        "neither (head and not claimed); lock file: " + lock_file["state"])
                rec["waiter_check"] = ev
        print("HANG " + json.dumps(rec, indent=1, default=str), flush=True)
        (args.out / f"hang-c{args.child}-r{n}.json").write_text(json.dumps(rec, indent=1, default=str),
                                                                 encoding="utf-8")
        sys.stdout.flush()
        os._exit(3)  # the hung daemon threads and the stuck run die with the process


# -- the parent -----------------------------------------------------------------------------------

BURNER = "import time\nwhile True:\n    sum(range(10000))\n"


def parent_main(args) -> int:
    from junkroan.report_format import human_duration

    args.out.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.minutes * 60
    t0 = time.time()
    burners = []
    for _ in range(args.burners):
        burners.append(subprocess.Popen([sys.executable, "-c", BURNER], creationflags=NO_WINDOW | 0x00004000))  # BELOW_NORMAL
    runs = hangs = 0
    children: dict[int, subprocess.Popen] = {}
    nextid = 0
    logs: dict[int, object] = {}
    try:
        while time.time() < deadline and hangs < args.stop_hangs and runs < args.max_runs:
            while len(children) < args.children:
                nextid += 1
                log = open(args.out / f"child-{nextid}.log", "w", encoding="utf-8")
                logs[nextid] = log
                children[nextid] = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--child", str(nextid), "--out", str(args.out),
                     "--lock-timeout", str(args.lock_timeout), "--stall", str(args.stall), "--hard", str(args.hard)],
                    stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW, cwd=str(ROOT))
            time.sleep(1.0)
            for cid, proc in list(children.items()):
                if proc.poll() is not None:
                    del children[cid]
                    logs[cid].close()
            runs = hangs = 0
            for f in args.out.glob("child-*.log"):
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith('{"child"'):
                        runs += 1
                    elif line.startswith("HANG "):
                        hangs += 1
                        runs += 1
    finally:
        for proc in children.values():
            proc.kill()
        for b in burners:
            b.kill()
    print(f"command: python scripts/repro_746.py --children {args.children} --burners {args.burners} "
          f"--stop-hangs {args.stop_hangs} --minutes {args.minutes} --lock-timeout {args.lock_timeout} "
          f"--stall {args.stall}")
    print(f"runs {runs}, hangs {hangs} ({hangs}/{runs}), elapsed {human_duration(time.time() - t0)}")
    print(f"hang records: {sorted(p.name for p in args.out.glob('hang-*.json'))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", type=int, default=0, help="internal: run as child number N")
    ap.add_argument("--children", type=int, default=2)
    ap.add_argument("--burners", type=int, default=2, help="busy-loop processes (below-normal priority)")
    ap.add_argument("--stop-hangs", type=int, default=3)
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--max-runs", type=int, default=300)
    ap.add_argument("--lock-timeout", type=float, default=60.0, help="the test's NO_LOAD_REACHES (600 s), shortened")
    ap.add_argument("--stall", type=float, default=20.0, help="seconds a survivor may wait after its sibling ended")
    ap.add_argument("--hard", type=float, default=120.0, help="seconds one run may take in all")
    ap.add_argument("--out", type=Path, default=ROOT / "tmp_746_repro")
    args = ap.parse_args()
    args.out = args.out.resolve()
    if args.child:
        return child_main(args)
    return parent_main(args)


if __name__ == "__main__":
    sys.exit(main())
