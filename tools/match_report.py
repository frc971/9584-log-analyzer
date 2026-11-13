"""One-page report for a robot log. No AI needed.

    python tools/match_report.py logs/akit_..._q68.wpilog
    python tools/match_report.py logs/q68.wpilog --record          # also save numbers to history/metrics.csv
    python tools/match_report.py logs/q68.wpilog --only drivetrain,vision
    python tools/match_report.py logs/q68.wpilog --json            # machine-readable, for agents/scripts

Use "python3" instead of "python" on Mac/Linux if needed. Requires Python 3.11+, nothing else.
"""

import argparse
import csv
import json
import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checks import ALL  # noqa: E402
from checks.common import Context  # noqa: E402
from wpilog import Log  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROBOT = os.path.join(REPO, "robot", "2026.toml")
METRICS_CSV = os.path.join(REPO, "history", "metrics.csv")

ICON = {"problem": "PROBLEM", "watch": "WATCH", "ok": "ok"}


def load_robot(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def run(log_path, robot_path=DEFAULT_ROBOT, only=None):
    robot = load_robot(robot_path)
    ctx = Context(Log(log_path), robot)
    results = []
    for key, fn in ALL:
        if only and key not in only:
            continue
        try:
            results.append((key, fn(ctx)))
        except Exception as e:  # one broken check should not hide the others
            from checks.common import Result
            res = Result(key)
            res.watch(f"Check '{key}' crashed: {type(e).__name__}: {e}")
            results.append((key, res))
    return ctx, results


def to_markdown(log_path, ctx, results):
    out = [f"# Report: {os.path.basename(log_path)}", ""]
    summary = [(key, sev, text) for key, res in results for sev, text in res.findings if sev != "ok"]
    out.append("## Summary")
    if summary:
        for sev in ("problem", "watch"):
            for key, s, text in summary:
                if s == sev:
                    out.append(f"- **{ICON[sev]}** ({key}) {text}")
    else:
        out.append("- No problems found.")
    out.append("")
    for key, res in results:
        if not res.lines and not res.findings:
            continue  # a check with nothing to say for this log (e.g. no camera signals in a 2026 log)
        out.append(f"## {res.title}")
        out.extend(res.lines)
        for sev, text in res.findings:
            if sev == "ok":
                out.append(f"- {text}")
        out.append("")
    return "\n".join(out)


def record(log_path, results):
    """Append one row per log to history/metrics.csv (replacing an earlier row for the same log)."""
    row = {"log": os.path.basename(log_path)}
    for key, res in results:
        for name, value in res.metrics.items():
            row[f"{key}.{name}"] = value
    rows, fields = [], ["log"]
    if os.path.exists(METRICS_CSV):
        with open(METRICS_CSV, newline="") as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or ["log"])
            rows = [r for r in reader if r["log"] != row["log"]]
    for k in row:
        if k not in fields:
            fields.append(k)
    rows.append(row)
    rows.sort(key=lambda r: r["log"])
    os.makedirs(os.path.dirname(METRICS_CSV), exist_ok=True)
    with open(METRICS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+", help=".wpilog file(s)")
    ap.add_argument("--robot", default=DEFAULT_ROBOT, help="robot description (default robot/2026.toml)")
    ap.add_argument("--only", help="comma-separated checks: " + ",".join(k for k, _ in ALL))
    ap.add_argument("--record", action="store_true", help="save this log's numbers to history/metrics.csv")
    ap.add_argument("--json", action="store_true", help="print metrics and findings as JSON")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    for path in args.logs:
        ctx, results = run(path, args.robot, only)
        if args.record:
            record(path, results)
        if args.json:
            print(json.dumps({
                "log": os.path.basename(path),
                "metrics": {f"{k}.{n}": v for k, res in results for n, v in res.metrics.items()},
                "findings": [{"check": k, "severity": s, "text": t} for k, res in results for s, t in res.findings],
            }, indent=1))
        else:
            print(to_markdown(path, ctx, results))


if __name__ == "__main__":
    main()
