#!/bin/sh
# #178 item 5: the two other ailment builds, one probe each, one PoB slot at a time.
# Each build waits for `machine_load --need 1 --role other` (GO, at most 14 min) before it opens
# a PobSession, and the second only starts after the first has ended.
cd /c/Coding/poe-junkroan-v2/artifacts/runs/snap/20260927-0246-ziz-tpl-main3-s4 || exit 1
PY="C:/Users/user/AppData/Local/Programs/Python/Python312/junkroan.exe"
PROBE="C:/Coding/poe-junkroan-v2/.claude/worktrees/agent-a61c4d30f306a86e1/scripts/diag178_probe.py"
OUT="C:/Coding/poe-junkroan-v2/artifacts/runs"

run_one() {
  slug="$1"
  i=0
  while [ "$i" -lt 14 ]; do
    if python C:/Coding/poe-junkroan-v2/scripts/machine_load.py --need 1 --role other >/dev/null 2>&1; then
      echo "=== $slug GO $(date +%H:%M:%S)"
      "$PY" "$PROBE" "$slug" 4 wishlist 0 "$OUT/diag178-$slug.json" "$OUT/diag178-$slug.log" - 2>&1 \
        | grep -E "^(SLUG|before_reconfigure|after_reconfigure|config inputs changed|written)|Traceback|Error"
      echo "=== $slug end $(date +%H:%M:%S)"
      return 0
    fi
    i=$((i + 1))
    sleep 60
  done
  echo "=== $slug NO-GO after 14 min"
  return 1
}

run_one bleed_perforate
run_one burning_arrow_snipe
echo "=== item 5 done $(date +%H:%M:%S)"
