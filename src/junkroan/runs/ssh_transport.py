"""One shared way to send a PowerShell script over ``ssh <alias>`` (issues #81, #87).

``-Command "<script>"`` lets a shell along the way (ssh's own remote command line, the Windows
default shell) expand or re-tokenize the argument before the inner powershell ever sees it: a real
round trip against the laptop failed with `` "= : The term '=' is not recognized..." `` (#81's
follow-up) because its own ``$p`` was eaten before powershell got it. The fix, used everywhere a
script crosses ``ssh``: ``-EncodedCommand``, base64 of the script's UTF-16LE bytes -- a form no
shell layer along the way can touch.

:func:`build_ssh_argv` is the one place that builds this argv; ``hosts.run_on_host`` and
``remote_store.default_remote_transport`` both call it instead of keeping their own copy.
"""

from __future__ import annotations

import base64
from typing import Any, Mapping


def encode_command(script: str) -> str:
    """Base64 of ``script``'s UTF-16LE bytes, the exact form ``powershell -EncodedCommand`` wants."""

    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def build_ssh_argv(host_cfg: Mapping[str, Any], script: str) -> list[str]:
    """The exact ``ssh`` argv to run ``script`` on ``host_cfg``'s alias via ``-EncodedCommand``.

    Split out so a test can decode the ``-EncodedCommand`` argument back to ``script`` without a
    real subprocess call.
    """

    alias = host_cfg.get("ssh")
    if not alias:
        raise ValueError(f"host {host_cfg.get('name', host_cfg)!r} has no ssh alias (\"ssh\" is null); "
                         "it is local to its own daemon")
    return ["ssh", str(alias), "powershell", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", encode_command(script)]


def build_scp_argv(host_cfg: Mapping[str, Any], local_dir: str, remote_dir: str) -> list[str]:
    """The exact ``scp -r`` argv copying ``local_dir`` to ``remote_dir`` on ``host_cfg``'s ssh alias.

    ``remote_dir`` is the full destination path of the copied directory itself (its parent must exist), so
    the caller picks a ``.partial`` name and renames afterwards. Windows paths with backslashes are given
    with forward slashes, the form scp's remote side takes.
    """

    alias = host_cfg.get("ssh")
    if not alias:
        raise ValueError(f"host {host_cfg.get('name', host_cfg)!r} has no ssh alias (\"ssh\" is null); "
                         "it is local to its own daemon")
    remote = str(remote_dir).replace("\\", "/")
    return ["scp", "-r", "-q", "-o", "BatchMode=yes", str(local_dir), f"{alias}:{remote}"]


__all__ = ["build_scp_argv", "build_ssh_argv", "encode_command"]
