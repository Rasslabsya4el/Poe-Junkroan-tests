#!/usr/bin/env bash
# Run as the first command of a Claude Code cloud session: bash scripts/cloud_setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

start=$(date +%s)
stamp=.venv/.junkroan_setup_stamp
want=$(sha256sum pyproject.toml | cut -d' ' -f1)

if [ ! -x .venv/bin/python ]; then
    python3.12 -m venv .venv
fi

.venv/bin/python --version
if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
    echo "pip: skipped (.venv up to date with pyproject.toml)"
else
    .venv/bin/python -m pip install -q -e '.[dev]'
    echo "$want" > "$stamp"
    echo "pip: installed -e '.[dev]'"
fi
echo "took $(( $(date +%s) - start )) s"
