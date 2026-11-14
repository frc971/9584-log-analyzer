"""Short commands for the log tools, so nobody has to remember the long ones. No AI needed.

    python analyze.py                  full report on the newest log in logs/, and record it
    python analyze.py q38              full report on the log whose name contains "q38"
    python analyze.py drivetrain       just one part of the report (newest log; see the list below)
    python analyze.py drivetrain q38   ...or for a chosen log
    python analyze.py vision           vision report + replay of the robot's vision filter
    python analyze.py trend magnet     how a number changed across every recorded log
    python analyze.py list             the logs in logs/, newest first

Parts of the report: timeline, power, comms, devices, drivetrain (or drive), intake, shooting,
vision, cameras, loop. Use "python3" instead of "python" on Mac/Linux if needed.

"Newest" goes by the time in the file name (akit_YY-MM-DD_HH-MM-SS...), not the file's date:
copying logs onto a laptop resets file dates, so they cannot be trusted. Files without that time in
the name fall back to their file date. The log being used is always printed first: check it.

Only the full report saves numbers to history/metrics.csv. A single part does not, because it would
replace the log's saved row with a partial one. Add --no-record to the full report to skip saving.

This file only runs the scripts in tools/ (match_report.py, history.py, vision_replay.py); it does
no analysis itself. Anything after the log, like --robot robot/2026.toml, is passed through.
"""

import csv
import datetime
import os
import re
import subprocess
import sys
import tomllib

REPO = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(REPO, "logs")
TOOLS = os.path.join(REPO, "tools")
METRICS_CSV = os.path.join(REPO, "history", "metrics.csv")

SECTIONS = ["timeline", "power", "comms", "devices", "drivetrain", "intake", "shooting",
            "vision", "cameras", "loop"]
ALIASES = {"drive": "drivetrain", "swerve": "drivetrain", "battery": "power", "camera": "cameras"}
COMMANDS = {"report", "trend", "list", "help"} | set(SECTIONS) | set(ALIASES)

_STAMP = re.compile(r"akit_(\d\d-\d\d-\d\d_\d\d-\d\d-\d\d)")


def log_time(path):
    """When the log was made: the time in its AdvantageKit name if it has one, else the file date."""
    m = _STAMP.search(os.path.basename(path))
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%y-%m-%d_%H-%M-%S").timestamp()
        except ValueError:
            pass
    return os.path.getmtime(path)


def list_logs(folder=LOGS):
    """Every .wpilog in the folder, newest first."""
    if not os.path.isdir(folder):
        return []
    paths = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".wpilog")]
    return sorted(paths, key=lambda p: (log_time(p), os.path.basename(p)), reverse=True)


def find_log(selector=None, folder=LOGS):
    """(path, note) for a selector: None = newest log; an existing path; or text in the file name.
    Raises SystemExit with a message a student can act on."""
    if selector and os.path.isfile(selector):
        return selector, ""
    logs = list_logs(folder)
    if not logs:
        raise SystemExit(f"No .wpilog files in {os.path.relpath(folder, REPO)}/. Copy a log from the "
                         "robot's USB stick there first (see README, 'Getting a log').")
    if not selector:
        return logs[0], "newest log"
    matches = [p for p in logs if selector.lower() in os.path.basename(p).lower()]
    if not matches:
        raise SystemExit(f"No log in logs/ has '{selector}' in its name. Run: python analyze.py list")
    if len(matches) > 1:
        return matches[0], f"newest of {len(matches)} logs matching '{selector}'"
    return matches[0], f"matches '{selector}'"


def recorded_logs():
    if not os.path.exists(METRICS_CSV):
        return set()
    with open(METRICS_CSV, newline="") as f:
        return {row["log"] for row in csv.DictReader(f)}


def _run(script, *args):
    return subprocess.call([sys.executable, os.path.join(TOOLS, script), *args], cwd=REPO)


def _robot_heading_limit(log_path, extra):
    """The robot's own vision heading limit, from the robot file match_report would pick."""
    sys.path.insert(0, TOOLS)
    from match_report import load_robot, pick_robot  # noqa: E402
    from wpilog import Log  # noqa: E402
    robot_path = extra[extra.index("--robot") + 1] if "--robot" in extra else pick_robot(Log(log_path))
    return load_robot(robot_path)["vision"].get("max_heading_error_deg")


def _split(args):
    """[selector] + passthrough flags: the first word not starting with '-' is the log."""
    selector = next((a for a in args if not a.startswith("-")), None)
    rest = list(args)
    if selector:
        rest.remove(selector)
    return selector, rest


def _announce(path, note):
    print(f"Using log: {os.path.relpath(path, REPO)}" + (f"  ({note})" if note else ""))
    print()
    sys.stdout.flush()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0).lower() if argv and argv[0].lower() in COMMANDS else "report"
    cmd = ALIASES.get(cmd, cmd)

    if cmd == "help" or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    if cmd == "list":
        done = recorded_logs()
        logs = list_logs()
        if not logs:
            print("No .wpilog files in logs/.")
        for i, p in enumerate(logs):
            name = os.path.basename(p)
            print(("newest  " if i == 0 else "        ") + ("recorded  " if name in done else "          ") + name)
        return 0

    if cmd == "trend":
        if not argv:
            print("Which number? For example: python analyze.py trend magnet")
            print("Every name you can use:\n")
        return _run("history.py", *argv)

    selector, extra = _split(argv)
    path, note = find_log(selector)
    _announce(path, note)

    if cmd == "report":
        record = "--no-record" not in extra
        extra = [a for a in extra if a != "--no-record"]
        code = _run("match_report.py", path, *extra, *(["--record"] if record else []))
        if record and code == 0:
            print(f"\nSaved this log's numbers to history/metrics.csv. "
                  f"Compare with earlier matches: python analyze.py trend <name>")
        return code

    code = _run("match_report.py", path, "--only", cmd, *extra)
    if cmd == "vision" and code == 0:
        limit = _robot_heading_limit(path, extra)
        print("## Vision filter replay (the robot's heading rule"
              + (f": reject if off the gyro by more than {limit:g} deg)" if limit else ")"))
        print("Try other rules with tools/vision_replay.py; see its --help.\n")
        sys.stdout.flush()
        robot = extra[extra.index("--robot"):extra.index("--robot") + 2] if "--robot" in extra else []
        code = _run("vision_replay.py", path, *robot,
                    *(["--max-heading-error", f"{limit:g}"] if limit else []))
    return code


if __name__ == "__main__":
    sys.exit(main())
