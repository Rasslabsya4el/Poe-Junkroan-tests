"""The bin tests' project pin, as a pytest plugin (#973; the root ``pytest.ini`` loads it with ``-p pob_slots_pin``).

The collector finds its project from the working directory; the pin sets ``MONITOR_ROOT`` to this checkout as soon
as a file of this folder is collected, whatever the cwd is. It is a plugin and not a ``conftest.py``: a ``conftest``
module here shadowed ``tests/conftest.py`` for ``from conftest import pc_only`` in a run that selects both kinds of
tests (32 collection errors on the merge of #962).
"""
import os
from pathlib import Path

_BIN = Path(__file__).resolve().parent
_ROOT = Path(__file__).resolve().parents[3]


def pytest_collect_file(file_path, parent):
    """Pin before a file of this folder is imported; never for a file elsewhere (a tests/-only run sets nothing)."""
    if Path(file_path).resolve().is_relative_to(_BIN):
        os.environ["MONITOR_ROOT"] = str(_ROOT)
    return None
