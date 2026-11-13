"""Compare numbers across logs from history/metrics.csv (filled by match_report.py --record).

    python tools/history.py                         # list the metric names
    python tools/history.py magnet                  # every metric whose name contains "magnet"
    python tools/history.py battery_path steer_limit
    python tools/history.py magnet --logs q51,q68   # only logs whose names contain q51 or q68
"""

import argparse
import csv
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS_CSV = os.path.join(REPO, "history", "metrics.csv")


def _label(log_name):
    """akit_26-11-08_18-23-38_mttd_q68.wpilog -> 'mttd_q68'; unnamed logs -> '11-08 18:23'."""
    parts = log_name.replace("akit_", "").replace(".wpilog", "").split("_")
    if len(parts) > 2:
        return "_".join(parts[2:])
    date = parts[0][3:] if len(parts[0]) == 8 else parts[0]
    return f"{date} {parts[1][:5].replace('-', ':')}" if len(parts) > 1 else parts[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patterns", nargs="*", help="text that metric names must contain (any of them)")
    ap.add_argument("--logs", help="comma-separated text; keep logs whose name contains any")
    a = ap.parse_args()
    if not os.path.exists(METRICS_CSV):
        sys.exit("No history yet. Run: python tools/match_report.py <log> --record")
    with open(METRICS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = [c for c in (reader.fieldnames or []) if c != "log"]
    if a.logs:
        keep = a.logs.split(",")
        rows = [r for r in rows if any(k in r["log"] for k in keep)]
    if not a.patterns:
        print("\n".join(fields))
        return
    cols = [c for c in fields if any(p in c for p in a.patterns)]
    if not cols:
        sys.exit("No metric names contain: " + ", ".join(a.patterns))
    # One metric per line, logs across: easier to read for many logs.
    names = [_label(r["log"]) for r in rows]
    width = max([8] + [len(n) for n in names])
    print("metric".ljust(48) + "".join(n.rjust(width + 2) for n in names))
    for c in cols:
        cells = []
        for r in rows:
            v = r.get(c, "")
            try:
                v = f"{float(v):.3g}"
            except ValueError:
                pass
            cells.append(str(v).rjust(width + 2))
        print(c[:47].ljust(48) + "".join(cells))


if __name__ == "__main__":
    main()
