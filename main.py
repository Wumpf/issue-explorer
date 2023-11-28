from attr import dataclass
import rerun as rr
import argparse
import github
from datetime import datetime

def utc_to_epoch(time: datetime) -> float:
    return int(time.strftime("%s"))

def state_to_color(state: str) -> rr.datatypes.Rgba32Like:
    if state == "open":
        return (255, 255, 255, 255)
    elif state == "closed":
        return (0, 255, 0, 255)
    else:
        print(f"unknown state {state}")
        return (0, 0, 255, 255)

@dataclass
class Issue:
    created_at: datetime
    closed_at: datetime
    number: int

def main() -> None:
    parser = argparse.ArgumentParser(description="Visualizes statistics about github issues in Rerun.")
    parser.add_argument(
        "--repo", type=str, required=True, help="Name of the respository. E.g. rerun-io/rerun"
    )
    parser.add_argument(
        "--access-token",
        default=None,
        type=str,
        help="Personal access token. Generate it via Github 'Developer Settings'",
    )

    rr.script_add_args(parser)
    args = parser.parse_args()
    rr.script_setup(args, f"github issues - {args.repo}")

    g = github.Github(args.access_token)
    repo = g.get_repo(args.repo)

    issues = []

    print("Querying issues and logging the basics...")

    for issue in repo.get_issues(state="all", sort="updated"):
        rr.set_time_seconds("time", utc_to_epoch(issue.created_at))
        rr.log(f"issues/#{issue.number}", rr.TextLog(issue.title, color=state_to_color(issue.state), level=issue.state))

        issues.append(Issue(created_at=issue.created_at, closed_at=issue.closed_at, number=issue.number))

    print("Done querying and logging basics.")
    print("Plotting changes over time...")

    created_closed_events = [(issue.created_at, 1) for issue in issues] + [(issue.closed_at, -1) for issue in issues if issue.closed_at is not None]
    created_closed_events.sort(key=lambda x: x[0])
    num_open = 0
    num_total = 0
    num_closed = 0
    for time, delta in created_closed_events:
        rr.set_time_seconds("time", utc_to_epoch(time))
        num_open += delta
        rr.log("plot/open", rr.TimeSeriesScalar(num_open, color=(255, 255, 255, 255)))

        if delta == 1:
            num_total += 1
            rr.log("plot/total", rr.TimeSeriesScalar(num_total, color=(50, 50, 255, 255)))
        elif delta == -1:
            num_closed += 1
            rr.log("plot/closed", rr.TimeSeriesScalar(num_closed, color=(50, 255, 50, 255)))

    rr.script_teardown(args)

if __name__ == "__main__":
    main()