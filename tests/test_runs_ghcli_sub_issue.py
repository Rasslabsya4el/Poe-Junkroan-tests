"""#164: the sub-issue attach sends the child's id as an integer (`gh api -F`), not a string (`-f`).

The live backfill of 2026-10-01 created #414-#416 but attached none under #404: GitHub's
`POST /issues/{n}/sub_issues` rejects a string `sub_issue_id`.
"""

import subprocess

from junkroan.runs import daemon


def test_add_sub_issue_sends_the_id_as_an_integer(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        out = "5661938422\n" if argv[:2] == ["gh", "api"] and "-X" not in argv else "{}"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(daemon, "run_bounded", fake_run)  # #521: the gh calls go through the tree-killing runner
    assert daemon.GhCli(cwd=tmp_path).add_sub_issue(404, 414) is True
    post = calls[-1]
    assert post[:5] == ["gh", "api", "-X", "POST", "repos/{owner}/{repo}/issues/404/sub_issues"]
    i = post.index("sub_issue_id=5661938422")
    assert post[i - 1] == "-F"
