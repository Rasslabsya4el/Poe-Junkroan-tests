"""The run scheduler (issue #36 "keymaster"): host modes, slot reservations (#41), the job
store (#40) and the daemon that runs the jobs (#48).

Owner commands ("I play", "browser on the laptop") become one command each instead of hand-editing
``var/machine_budget.json`` by hand. See ``src/junkroan/runs/hosts.py``, ``src/junkroan/runs/store.py``,
``src/junkroan/runs/daemon.py`` and ``scripts/runs.py``.
"""
