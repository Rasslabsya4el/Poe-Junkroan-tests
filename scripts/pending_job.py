"""``python scripts/pending_job.py <issue>``: exit 0 when a job of the issue is queued or running in this
host's runs store, 1 when none (the dispatcher's `pending_job_command`, #818)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from junkroan.runs.daemon import live_jobs_of_issue  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

if __name__ == "__main__":
    sys.exit(0 if live_jobs_of_issue(Store().jobs(), int(sys.argv[1])) else 1)
