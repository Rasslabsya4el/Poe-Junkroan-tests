"""#805 unit 3: a worker that DIED (stdout EOF, broken stdin, exited before the call) is ended like a timed-out one.

Run 20261010-1718-P1-#604-5, toxic_rain: stdout hit EOF in swap_subtrees -> "returned an empty protocol message"; the
dead worker stayed registered, so the attempt's restore wrote to its dead stdin and `OSError: [Errno 22]` replaced
the first error in report.md. Fake workers (a tiny python subprocess or a stub): no PoB starts.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from junkroan.optimizer.improvement_loop import Attempt, AttemptTools
from junkroan.pob import headless_runtime_adapter as hra
from junkroan.pob.host_runtime import PoBHeadlessHostContractError

EMPTY = "Headless PoB worker returned an empty protocol message."


def _spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _adapter(process):
    adapter = hra.PinnedPoBHeadlessRuntimeAdapter.__new__(hra.PinnedPoBHeadlessRuntimeAdapter)
    adapter._flask_flags_changed = False
    adapter._dropped_workers = {}
    adapter._workers = {"p": hra._WorkerProcess(process=process, request=None)}
    return adapter, SimpleNamespace(process_instance_id="p")


_DIES_AFTER_ONE_LINE = (
    "import sys\n"
    "sys.stdin.readline()\n"
    "sys.stderr.write('\\n'.join('noise %d' % i for i in range(20)) + '\\nlua: not enough memory\\n')\n"
    "sys.stderr.flush()\n"
    "sys.exit(3)\n"
)


def _swap_call(adapter, handle):
    return adapter._call_worker(handle, {"action": "load_snapshot"})


def _dead_by_eof():
    process = _spawn(_DIES_AFTER_ONE_LINE)
    adapter, handle = _adapter(process)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _swap_call(adapter, handle)
    return adapter, handle, process, info.value


def test_eof_reply_ends_the_worker_and_keeps_the_first_text_with_exit_code_and_stderr_tail() -> None:
    adapter, handle, process, error = _dead_by_eof()
    first = str(error)
    assert first.startswith(EMPTY) and error.failure_state == "runtime_protocol_failed"
    assert "Call load_snapshot" in first and "exit code 3" in first
    assert "lua: not enough memory" in first and "noise 19" in first
    assert "noise 0" not in first and "noise 14" not in first  # the last 5 lines only
    assert process.poll() is not None
    assert "p" not in adapter._workers
    assert adapter._dropped_workers == {"p": first}


def test_a_later_call_on_the_dead_handle_starts_with_the_first_text() -> None:
    adapter, handle, _process, error = _dead_by_eof()
    with pytest.raises(PoBHeadlessHostContractError) as info:
        adapter.load_build_xml(handle, "<PathOfBuilding/>")
    message = str(info.value)
    assert info.value.failure_state == "unknown_session"
    assert message.startswith(str(error))
    assert "later call load_build_xml" in message and "refused" in message
    assert "No live headless PoB worker" not in message


def test_a_worker_that_exited_before_the_call_is_ended_too() -> None:
    process = _spawn("import sys\nsys.stderr.write('died at start\\n')\nsys.exit(5)\n")
    process.wait(timeout=20)
    adapter, handle = _adapter(process)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _swap_call(adapter, handle)
    first = str(info.value)
    assert "exited before action 'load_snapshot'" in first and "exit code 5" in first and "died at start" in first
    assert "p" not in adapter._workers and adapter._dropped_workers == {"p": first}


class _BrokenStdin:
    def write(self, _text: str) -> None:
        raise OSError(22, "Invalid argument")

    def flush(self) -> None:  # pragma: no cover - the write already failed
        pass


class _StubProc:
    pid = 1

    def __init__(self) -> None:
        self.stdin, self.stdout, self.stderr = _BrokenStdin(), object(), None
        self.ended = False

    def poll(self):
        return 0 if self.ended else None

    def terminate(self) -> None:
        self.ended = True

    def kill(self) -> None:
        self.ended = True

    def wait(self, timeout=None) -> int:
        if not self.ended:
            raise subprocess.TimeoutExpired("stub", timeout)
        return 0


def test_a_write_to_a_dead_stdin_is_ended_like_the_eof_with_the_oserror_in_the_text() -> None:
    process = _StubProc()
    adapter, handle = _adapter(process)
    with pytest.raises(PoBHeadlessHostContractError) as info:
        _swap_call(adapter, handle)
    first = str(info.value)
    assert "OSError" in first and "Invalid argument" in first and "Call load_snapshot" in first
    assert process.ended and "p" not in adapter._workers
    assert adapter._dropped_workers == {"p": first}
    with pytest.raises(PoBHeadlessHostContractError) as later:
        adapter.read_state(handle)
    assert str(later.value).startswith(first)


def test_a_live_worker_is_untouched_by_the_failure_path() -> None:
    process = _spawn(
        "import sys\nfor line in sys.stdin:\n    print('{\"ok\": true, \"result\": {\"n\": 1}}', flush=True)\n"
    )
    try:
        adapter, handle = _adapter(process)
        assert _swap_call(adapter, handle)["result"] == {"n": 1}
        assert "p" in adapter._workers and adapter._dropped_workers == {}
    finally:
        process.kill()
        process.wait(timeout=20)


def _tools(restore) -> AttemptTools:
    return AttemptTools(
        st=SimpleNamespace(cur=1.0), snapshot=lambda: {}, restore=lambda _state, keep_rejections=False: restore(),
        rejudge=lambda: None, restore_mark=lambda *_a: None, score=lambda: 1.0, record=lambda *a, **k: None,
        note_drop=lambda _row: None, log=lambda _m: None, min_gain=0.0,
    )


def test_a_worker_killed_mid_move_leaves_the_first_error_in_the_escaping_exception() -> None:
    process = _spawn(_DIES_AFTER_ONE_LINE)
    adapter, handle = _adapter(process)

    def restore() -> None:
        adapter.load_build_xml(handle, "<xml/>")

    with pytest.raises(PoBHeadlessHostContractError) as info:
        with Attempt(_tools(restore), "loop pass 6 move swaps", ledger_name=None, started=0.0, before=None, armed=True):
            _swap_call(adapter, handle)
    row_text = f"{type(info.value).__name__}: {info.value}"  # scripts/benchmark.py: the row's `error`
    assert EMPTY in row_text and "exit code 3" in row_text and "lua: not enough memory" in row_text
    assert "OSError" not in row_text and "No live headless PoB worker" not in row_text


def test_a_restore_that_fails_on_its_own_text_still_escapes_and_carries_the_first_error() -> None:
    first = PoBHeadlessHostContractError("runtime_protocol_failed", EMPTY + " Call load_snapshot, exit code 3.")

    def restore() -> None:
        raise OSError(22, "Invalid argument")

    with pytest.raises(Exception) as info:  # the build still fails: not swallowed
        with Attempt(_tools(restore), "loop pass 6 move swaps", ledger_name=None, started=0.0, before=None, armed=True):
            raise first
    row_text = f"{type(info.value).__name__}: {info.value}"
    assert row_text.split(": ", 1)[1].startswith(str(first))
    assert "Invalid argument" in row_text  # the restore failure is named after the first error, not instead of it
    assert info.value.__cause__ is not None and isinstance(info.value.__cause__, OSError)
    assert info.value.__context__ is first
