"""#246 rows 3-4: `scripts/probe_console_windows.py`'s `count_windows_on_desktop` treats
`EnumDesktopWindows` returning FALSE with `GetLastError()==0` as a valid "0 windows" (the callback
was simply never invoked), never as a failure -- confirmed by a live repro (creating one window on
the same desktop makes the very next call return TRUE with that window counted; destroying it goes
back to FALSE/err==0). Any other error code is still a real failure.

These tests fake `EnumDesktopWindows`/`GetClassNameW`/`GetWindowTextLengthW` at the `user32`
handle the module holds, so they never open a real desktop or spawn anything; they are cheap and
run in the default suite."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="module raises on import off Windows")


def _import_module():
    import importlib.util
    import sys as _sys

    spec = importlib.util.spec_from_file_location(
        "probe_console_windows", ROOT / "scripts" / "probe_console_windows.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    _sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_false_with_last_error_zero_is_zero_windows_not_a_failure(monkeypatch):
    mod = _import_module()

    def fake_enum_no_windows(handle, callback, lparam):
        ctypes.set_last_error(0)
        return False  # the callback is never invoked: nothing to enumerate

    monkeypatch.setattr(mod.user32, "EnumDesktopWindows", fake_enum_no_windows)

    assert mod.count_windows_on_desktop(123) == []


def test_false_with_a_real_error_still_raises(monkeypatch):
    mod = _import_module()

    def fake_enum_access_denied(handle, callback, lparam):
        ctypes.set_last_error(5)  # ERROR_ACCESS_DENIED
        return False

    monkeypatch.setattr(mod.user32, "EnumDesktopWindows", fake_enum_access_denied)

    with pytest.raises(mod.ProbeError):
        mod.count_windows_on_desktop(123)


def test_true_with_one_window_counts_its_class_and_title(monkeypatch):
    mod = _import_module()

    def fake_get_class_name(hwnd, buf, size):
        buf.value = "ConsoleWindowClass"
        return len(buf.value)

    def fake_window_text_length(hwnd):
        return 0

    def fake_enum_one_window(handle, callback, lparam):
        callback(42, lparam)
        return True

    monkeypatch.setattr(mod.user32, "EnumDesktopWindows", fake_enum_one_window)
    monkeypatch.setattr(mod.user32, "GetClassNameW", fake_get_class_name)
    monkeypatch.setattr(mod.user32, "GetWindowTextLengthW", fake_window_text_length)

    assert mod.count_windows_on_desktop(123) == [("ConsoleWindowClass", "")]
