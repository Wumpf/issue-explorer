import json
import subprocess
from collections import defaultdict
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
TODO_CACHE_FILE = DATA_DIR / "todo_cache.json"

TODO_CACHE = {}


def load_cache():
    global TODO_CACHE
    if TODO_CACHE_FILE.exists():
        TODO_CACHE = json.loads(TODO_CACHE_FILE.read_bytes())


def save_cache():
    global TODO_CACHE
    TODO_CACHE_FILE.write_text(json.dumps(TODO_CACHE))


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


def log_commits(branch_name: str):
    print("Logging all commits and their TODO count...")
    repo = Repo(GIT_REPO)
    main_branch = repo.heads[branch_name]

    all_commits = list(reversed(list(repo.iter_commits(main_branch.name))))

    commit_count_per_author = defaultdict(lambda: 0)
    for i, commit in enumerate(all_commits):
        # this is expensive, so we cache it
        if commit.hexsha in TODO_CACHE:
            todo_count = TODO_CACHE[commit.hexsha]
        else:
            todo_count = 0
            for blob in commit.tree.traverse():
                if blob.type == "blob":  # blobs are files
                    todo_count += (
                        blob.data_stream.read().decode(errors="ignore").count("TODO(")
                    )
            TODO_CACHE[commit.hexsha] = todo_count

        commit_count_per_author[commit.author.name] += 1

        rr.set_time_sequence("commit_idx", i)
        rr.set_time_seconds("time", commit.authored_datetime.timestamp())

        rr.log(
            f"commit/sha_{commit.hexsha[:7]}",
            rr.TextLog(f"{commit.hexsha} - {commit.author.name} - {commit.summary}"),
        )
        rr.log("plot/commits/todos", rr.TimeSeriesScalar(scalar=todo_count))
        rr.log("plot/commits/count", rr.TimeSeriesScalar(scalar=i))

        for author, cnt in commit_count_per_author.items():
            rr.log(f'plot/commits/authors/"{author}"', rr.TimeSeriesScalar(scalar=cnt))


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
    def created_at_timestamp(self) -> float:
        return self.created_at.timestamp()

    @property
    def closed_at_timestamp(self) -> float | None:
        if self.closed_at is None:
            return None
        return self.closed_at.timestamp()

    @property
    def state_color(self) -> rr.datatypes.Rgba32Like:
        if self.state == "open":
            return 255, 255, 255, 255
        elif self.state == "closed":
            return 0, 255, 0, 255
        else:
            print(f"unknown state {self.state}")
            return 0, 0, 255, 255


def log_issues():
    issues_data = json.loads(ISSUE_DATA_FILE.read_text())
    issues = []

    print("Logging issues...")

    for i, issue_data in enumerate(issues_data):
        issue = Issue.from_json(issue_data)

        rr.set_time_sequence("issue_num", issue.number)
        rr.set_time_seconds("time", issue.created_at_timestamp)
        rr.log(
            f"issues/#{issue.number}",
            rr.TextLog(issue.title, color=issue.state_color, level=issue.state),
        )

        issues.append(issue)

    print("Logging change over time...")

    created_closed_events = [(issue.created_at_timestamp, 1) for issue in issues] + [
        (issue.closed_at_timestamp, -1)
        for issue in issues
        if issue.closed_at_timestamp is not None
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

    load_cache()

    log_issues()
    log_commits(args.branch)

    save_cache()

    rr.script_teardown(args)


if __name__ == "__main__":
    main()
