"""A tiny suite stand-in for test_agentops_merge.py: sleeps an optional number of seconds
(3rd argv, default 0 -- so it holds the merge lock's critical section that long), bumps a
counter file, exits 1 if a flag file exists, 0 otherwise. Not a test module itself (no
test_ prefix).

A 5th argv (the name of an env var) makes it also write that var's value (or "" if unset) to a
sibling file next to `counter`, suffixed `.env-<name>` -- issue #198's `merge_suite_env` proof:
a test can read that file back to confirm the suite process actually saw the injected env."""

import os
import sys
import time
import pathlib

counter = pathlib.Path(sys.argv[1])
flag = pathlib.Path(sys.argv[2])
sleep_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
env_probe_name = sys.argv[4] if len(sys.argv) > 4 else None
if sleep_seconds:
    time.sleep(sleep_seconds)
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
if env_probe_name:
    probe_path = counter.with_name(counter.name + f".env-{env_probe_name}")
    probe_path.write_text(os.environ.get(env_probe_name, ""), encoding="utf-8")
sys.exit(1 if flag.exists() else 0)
