"""Run names (#578): `P<priority>-<#issue|core>[-<n>]` (the counter only when the base exists), derived by `runs.py submit`, pure functions."""

from __future__ import annotations

import re
import subprocess
from typing import Iterable

_BENCH = re.compile(r"(?:^|[\/\s\"'])benchmark\.py(?=$|[\s\"'])")
_CORE_SET = re.compile(r"--set(?:=|\s+)[\"']?core14(?=$|[\s\"'])")
_TAG = re.compile(r"--tag(?:=|\s+)(\"[^\"]*\"|'[^']*'|\S+)")
_ISSUE = re.compile(r"--issue(?:=|\s+)#?(\d+)")


def _line(cmd: str | list[str] | tuple[str, ...]) -> str:
    return cmd if isinstance(cmd, str) else subprocess.list2cmdline(list(cmd))


def is_benchmark_command(cmd: str | list[str]) -> bool:
    return bool(_BENCH.search(_line(cmd)))


def is_core_command(cmd: str | list[str]) -> bool:
    line = _line(cmd)
    return bool(_BENCH.search(line) and _CORE_SET.search(line))


def _suffixed(base: str, existing: Iterable[str]) -> str:
    top = 0
    for tag in existing:
        if tag == base:
            top = max(top, 1)
        elif tag.startswith(base + "-") and tag[len(base) + 1:].isdigit():
            top = max(top, int(tag[len(base) + 1:]))
    return base if top == 0 else f"{base}-{top + 1}"


def derive_name(priority: str, issue: int | None, core: bool, existing: Iterable[str]) -> str:
    x = "core" if core else f"#{issue}"
    return _suffixed(f"{priority}-{x}", existing)


def import_name(cmd: str, existing: Iterable[str]) -> str:
    if is_core_command(cmd):
        x = "core"
    else:
        m = _ISSUE.search(cmd)
        x = f"#{m.group(1)}" if m else "untracked"
    return _suffixed(f"P2-{x}", existing)


def with_benchmark_tag(cmd: str | list[str], name: str) -> str | list[str]:
    """The benchmark command with `--tag <name>` set; any other command unchanged."""
    if isinstance(cmd, str):
        if not is_benchmark_command(cmd):
            return cmd
        if _TAG.search(cmd):
            return _TAG.sub(lambda _m: f"--tag {name}", cmd, count=1)
        return f"{cmd} --tag {name}"
    argv = list(cmd)
    if len(argv) == 1:
        return [with_benchmark_tag(argv[0], name)]
    if not is_benchmark_command(argv):
        return argv
    for i, a in enumerate(argv):
        if a == "--tag" and i + 1 < len(argv):
            argv[i + 1] = name
            return argv
        if a.startswith("--tag="):
            argv[i] = f"--tag={name}"
            return argv
    return [*argv, "--tag", name]
