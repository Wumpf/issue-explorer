import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import rerun as rr
import argparse
from datetime import datetime

from git import Repo

DATA_DIR = Path(__file__).parent / "data"
ISSUE_DATA_FILE = DATA_DIR / "issues.json"
GIT_REPO = DATA_DIR / "repo"


if not DATA_DIR.exists():
    DATA_DIR.mkdir()


def download_issue_data(repo):
    print("Downloading issues from GitHub...")
    res = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "all",
            "--repo",
            repo,
            "-L",
            "100000",
            "--json",
            "number,title,state,author,createdAt,updatedAt,closedAt,labels,url",
        ],
        check=True,
        capture_output=True,
    )

    # save output to file
    ISSUE_DATA_FILE.write_bytes(res.stdout)


def download_commit_data(repo: str, branch_name="main"):
    print("Downloading repository from GitHub...")
    if not GIT_REPO.exists():
        repo = Repo.clone_from(f"https://github.com/{repo}.git", GIT_REPO)
    else:
        repo = Repo(GIT_REPO)

    origin = repo.remotes.origin
    origin.fetch()
    origin.pull()

    main_branch = repo.heads[branch_name]
    main_branch.checkout()


def utc_to_epoch(time: datetime | None) -> float | None:
    if time is None:
        return None
    return int(time.strftime("%s"))


def state_to_color(state: str) -> rr.datatypes.Rgba32Like:
    if state == "open":
        return 255, 255, 255, 255
    elif state == "closed":
        return 0, 255, 0, 255
    else:
        print(f"unknown state {state}")
        return 0, 0, 255, 255


@dataclass
class Issue:
    created_at: datetime
    closed_at: datetime | None
    number: int
    title: str
    state: str

    @classmethod
    def from_json(cls, obj: dict) -> Self:
        if obj["createdAt"] is None:
            print(obj)
        if obj["closedAt"] is None:
            closed_at = None
        else:
            closed_at = datetime.fromisoformat(obj["closedAt"])

        return cls(
            created_at=datetime.fromisoformat(obj["createdAt"]),
            closed_at=closed_at,
            number=obj["number"],
            title=obj["title"],
            state=obj["state"].lower(),
        )

    @property
    def created_at_epoch(self):
        return utc_to_epoch(self.created_at)

    @property
    def closed_at_epoch(self):
        return utc_to_epoch(self.closed_at)

    @property
    def state_color(self):
        return state_to_color(self.state)


def log_issues():
    """
       {
      "author": {
        "id": "MDQ6VXNlcjE2NjU2Nzc=",
        "is_bot": false,
        "login": "jprochazk",
        "name": "Jan Procházka"
      },
      "closedAt": null,
      "labels": [
        {
          "id": "LA_kwDOHJFhi88AAAABCMO3ug",
          "name": "🕸️ web",
          "description": "regarding running the viewer in a browser",
          "color": "bfdadc"
        },
        {
          "id": "LA_kwDOHJFhi88AAAABIU2s7Q",
          "name": "🧑‍💻 dev experience",
          "description": "developer experience (excluding CI)",
          "color": "1d76db"
        }
      ],
      "number": 4428,
      "state": "OPEN",
      "title": "Remove `build_demo_app.py`",
      "updatedAt": "2023-12-04T14:09:53Z",
      "url": "https://github.com/rerun-io/rerun/issues/4428"
    },
      :return:
    """
    issues_data = json.loads(ISSUE_DATA_FILE.read_text())
    issues = []

    print("Logging issues...")

    for issue_data in issues_data:
        issue = Issue.from_json(issue_data)

        rr.set_time_seconds("time", issue.created_at_epoch)
        rr.log(
            f"issues/#{issue.number}",
            rr.TextLog(issue.title, color=issue.state_color, level=issue.state),
        )

        issues.append(issue)

    # issues.sort(key=lambda issue: issue.created_at)

    print("Logging change over time...")

    created_closed_events = [(issue.created_at_epoch, 1) for issue in issues] + [
        (issue.closed_at_epoch, -1)
        for issue in issues
        if issue.closed_at_epoch is not None
    ]
    created_closed_events.sort(key=lambda x: x[0])
    num_open = 0
    num_total = 0
    num_closed = 0
    for time, delta in created_closed_events:
        rr.set_time_seconds("time", time)
        num_open += delta
        rr.log("plot/open", rr.TimeSeriesScalar(num_open, color=(255, 255, 255, 255)))

        if delta == 1:
            num_total += 1
            rr.log(
                "plot/total", rr.TimeSeriesScalar(num_total, color=(50, 50, 255, 255))
            )
        elif delta == -1:
            num_closed += 1
            rr.log(
                "plot/closed", rr.TimeSeriesScalar(num_closed, color=(50, 255, 50, 255))
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visualizes statistics about github issues in Rerun."
    )
    parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="Name of the repository. E.g. rerun-io/rerun",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default="main",
        help="Branch to consider, defaults to `main`",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        type=str,
        help="Personal access token. Generate it via GitHub 'Developer Settings'",
    )
    parser.add_argument("--no-download", action="store_true", help="Use existing data")

    rr.script_add_args(parser)
    args = parser.parse_args()
    rr.script_setup(args, f"repo explorer - {args.repo}")

    if not args.no_download:
        download_issue_data(args.repo)
        download_commit_data(args.repo, args.branch)

    log_issues()

    rr.script_teardown(args)


if __name__ == "__main__":
    main()
