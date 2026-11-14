"""Short commands for the log tools, so nobody has to remember the long ones. No AI needed.

    python analyze.py                  full report on the newest log in logs/, and record it
    python analyze.py q38              full report on the log whose name contains "q38"
    python analyze.py drivetrain       just one part of the report (newest log; see the list below)
    python analyze.py drivetrain q38   ...or for a chosen log
    python analyze.py vision           vision report + replay of the robot's vision filter
    python analyze.py trend magnet     how a number changed across every recorded log
    python analyze.py list             the logs in logs/, newest first
    python analyze.py fetch            copy the newest log off the robot into logs/
    python analyze.py fetch --as q68 --report   ...add "_q68" to its name, then run the full report

Getting the log off the robot (fetch): plug a laptop into the robot with an Ethernet cable (fastest;
use this in the pits) or a USB cable, or connect to the robot's Wi-Fi in the shop. Wi-Fi to the
robot is not allowed at events. fetch tries 10.95.84.2, then roboRIO-9584-FRC.local, then
172.22.11.2 (USB), and prints which one worked and how fast it was. --address picks one yourself,
--team changes the team number. It needs the ssh and scp commands, which come with Mac, Linux and
Windows 10/11. If it asks for a password, press Enter: the robot's lvuser account has none. If the
robot code is running, the newest log is still being written; the copy has everything up to now.

Parts of the report: timeline, power, comms, devices, drivetrain (or drive), intake, shooting,
vision, cameras, loop. Use "python3" instead of "python" on Mac/Linux if needed.

"Newest" goes by the time in the file name (akit_YY-MM-DD_HH-MM-SS...), not the file's date:
copying logs onto a laptop resets file dates, so they cannot be trusted. Files without that time in
the name fall back to their file date. The log being used is always printed first: check it.

Only the full report saves numbers to history/metrics.csv. A single part does not, because it would
replace the log's saved row with a partial one. Add --no-record to the full report to skip saving.

This file only runs the scripts in tools/ (match_report.py, history.py, vision_replay.py) and copies
logs off the robot; it does no analysis itself. Anything after the log, like --robot robot/2026.toml, is passed through.
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
COMMANDS = {"report", "trend", "list", "fetch", "help"} | set(SECTIONS) | set(ALIASES)

TEAM = 9584
# How to reach each kind of robot controller, in the order fetch tries the addresses.
#   roboRIO (2026): 10.TE.AM.2 over the radio or a static Ethernet tether, its mDNS name, and
#     172.22.11.2 over a USB-B cable. User lvuser, no password. 9584's Robot.java writes the stick's
#     root (/media/sda1); AdvantageKit's default is /U/logs (/U is the same stick); /home/lvuser/logs
#     is WPILib's no-stick fallback.
#   SystemCore (2027): from WPILib's 2027 docs and AdvantageScope's code as of 2026-11, NOT yet
#     tried on a real one. robot.local (mDNS; also how a direct Ethernet tether works, since that
#     gets a 169.254 address), 10.TE.AM.2 through the radio, and USB-C networking, whose address the
#     sources disagree on (172.26/172.27 newer, 172.28/172.29 older). User and password: systemcore.
# The same file can show up under two folders (/U is /media/sda1): see _remote_logs.
PROFILES = {
    "roborio": {
        "user": "lvuser",
        "password": None,
        "addresses": ["10.{te}.{am}.2", "roboRIO-{team}-FRC.local", "172.22.11.2"],
        "dirs": ["/media/sda1", "/U/logs", "/media/sda1/logs", "/home/lvuser/logs"],
    },
    "systemcore": {
        "user": "systemcore",
        "password": "systemcore",
        "addresses": ["robot.local", "10.{te}.{am}.2", "172.27.0.1", "172.26.0.1", "172.29.0.1",
                      "172.28.0.1"],
        "dirs": ["/U/logs", "/u/logs", "/U", "/u", "/home/systemcore/logs"],
    },
}

_STAMP = re.compile(r"akit_(\d\d-\d\d-\d\d_\d\d-\d\d-\d\d)")


def name_time(name):
    """The time in an AdvantageKit log name (akit_YY-MM-DD_HH-MM-SS...), or None."""
    m = _STAMP.search(os.path.basename(name))
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%y-%m-%d_%H-%M-%S").timestamp()
        except ValueError:
            pass
    return None


def log_time(path):
    """When the log was made: the time in its AdvantageKit name if it has one, else the file date."""
    t = name_time(path)
    return t if t is not None else os.path.getmtime(path)


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


# ---- fetch: copy the newest log off the robot -------------------------------------------------

def robot_addresses(profile, team):
    te, am = divmod(team, 100)
    return [a.format(te=te, am=am, team=team) for a in PROFILES[profile]["addresses"]]


def _ssh_options(profile):
    opts = ["-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no",
            # The robot's host key changes every time it is reimaged: do not remember it.
            "-o", f"UserKnownHostsFile={os.devnull}", "-o", "LogLevel=ERROR",
            "-o", "NumberOfPasswordPrompts=1"]
    if PROFILES[profile]["password"] is None:
        # No password: do not offer the laptop's own keys (a laptop with many keys gets
        # "Too many authentication failures" before the empty password is tried).
        opts += ["-o", "PubkeyAuthentication=no"]
    return opts


def _list_command(dirs):
    loop = " ".join(dirs)
    return (f"for d in {loop}; do for f in \"$d\"/*.wpilog; do "
            "[ -f \"$f\" ] && stat -c '%Y %s %n' \"$f\"; done; done; exit 0")


def _remote_logs(stat_output):
    """[(name, remote_path, size, mtime)] from the robot's stat lines. The same file can be listed
    twice (/U/logs and /media/sda1/logs are one folder), so keep one per name and size."""
    seen, logs = set(), []
    for line in stat_output.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        mtime, size, path = int(parts[0]), int(parts[1]), parts[2]
        name = path.rsplit("/", 1)[-1]
        if (name, size) in seen:
            continue
        seen.add((name, size))
        logs.append((name, path, size, mtime))
    return logs


def newest_remote(logs):
    """The newest log, preferring AdvantageKit's (akit_...) over WPILib DataLogManager's (FRC_...),
    because this repo's checks read AdvantageKit signals. Time from the name if it has one."""
    akit = [lg for lg in logs if lg[0].startswith("akit_")]
    pool = akit or logs
    if not pool:
        return None
    return max(pool, key=lambda lg: (name_time(lg[0]) or lg[3], lg[3], lg[0]))


def local_name(remote_name, suffix=None):
    if not suffix:
        return remote_name
    stem = remote_name[:-len(".wpilog")] if remote_name.endswith(".wpilog") else remote_name
    return f"{stem}_{suffix.lstrip('_')}.wpilog"


def already_have(remote_name, size, folder=LOGS):
    """A log in logs/ that is this robot file already: same start of name and same size. A copy
    taken while the robot was still logging is smaller, so it gets replaced."""
    stem = remote_name[:-len(".wpilog")]
    for p in list_logs(folder):
        if os.path.basename(p).startswith(stem) and os.path.getsize(p) == size:
            return p
    return None


def _connect(profile, addresses, run):
    """(address, logs) for the first address that answers, or (None, tried)."""
    user = PROFILES[profile]["user"]
    command = _list_command(PROFILES[profile]["dirs"])
    for address in addresses:
        print(f"Trying {user}@{address} ...")
        sys.stdout.flush()
        result = run(["ssh", *_ssh_options(profile), f"{user}@{address}", command],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return address, _remote_logs(result.stdout)
    return None, addresses


def _copy(profile, address, remote_path, dest, run):
    user = PROFILES[profile]["user"]
    part = dest + ".part"   # list_logs ignores it, so a half-copied log is never "the newest"
    src = f"{user}@{address}:{remote_path}"
    code = run(["scp", *_ssh_options(profile), src, part]).returncode
    if code != 0:
        # Newer scp talks SFTP; fall back to the old protocol in case the robot lacks it.
        code = run(["scp", "-O", *_ssh_options(profile), src, part]).returncode
    if code != 0:
        if os.path.exists(part):
            os.remove(part)
        return False
    os.replace(part, dest)
    return True


def fetch(args, run=subprocess.run, folder=LOGS, clock=None):
    """python analyze.py fetch [--as q68] [--report] [--address A] [--team N] [--systemcore]"""
    import shutil
    import time
    clock = clock or time.monotonic
    opts = {"--as": None, "--address": None, "--team": str(TEAM)}
    flags = set()
    it = iter(args)
    for a in it:
        if a in opts:
            opts[a] = next(it, None)
            if opts[a] is None:
                raise SystemExit(f"{a} needs a value, e.g. fetch {a} {'q68' if a == '--as' else 'x'}")
        elif a in ("--report", "--systemcore", "--no-record"):
            flags.add(a)
        else:
            raise SystemExit(f"fetch does not know '{a}'. Run: python analyze.py help")
    if run is subprocess.run and not (shutil.which("ssh") and shutil.which("scp")):
        raise SystemExit("fetch needs the ssh and scp commands. Windows: Settings > Apps > Optional "
                         "features > add 'OpenSSH Client'. Or use AdvantageScope: File > Download Logs.")
    profile = "systemcore" if "--systemcore" in flags else "roborio"
    team = int(opts["--team"])
    addresses = [opts["--address"]] if opts["--address"] else robot_addresses(profile, team)
    if PROFILES[profile]["password"]:
        print(f"When asked for a password, type: {PROFILES[profile]['password']}")

    address, logs = _connect(profile, addresses, run)
    if address is None:
        raise SystemExit("Could not reach the robot at " + ", ".join(logs) + ".\nIs it on, and is "
                         "this laptop on its Ethernet cable, USB cable or Wi-Fi? In AdvantageScope, "
                         "File > Download Logs is another way to get the log.")
    pick = newest_remote(logs)
    if pick is None:
        raise SystemExit(f"Reached the robot at {address}, but it has no .wpilog files in "
                         + ", ".join(PROFILES[profile]["dirs"]) + ". Is the USB stick in?")
    name, remote_path, size, _ = pick
    print(f"Newest log on the robot: {name}  ({size / 1e6:.1f} MB, {remote_path})")

    have = already_have(name, size, folder)
    if have:
        print(f"Already copied: {os.path.relpath(have, REPO)}. Nothing to do.")
        dest = have
    else:
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, local_name(name, opts["--as"]))
        stem = name[:-len(".wpilog")]
        earlier = [p for p in list_logs(folder) if os.path.basename(p).startswith(stem)
                   and os.path.getsize(p) < size and os.path.abspath(p) != os.path.abspath(dest)]
        start = clock()
        if not _copy(profile, address, remote_path, dest, run):
            raise SystemExit("The copy failed. Try again, or use AdvantageScope: File > Download Logs.")
        for p in earlier:   # a copy taken while that log was still being written
            os.remove(p)
            print(f"Removed the earlier, shorter copy {os.path.relpath(p, REPO)}")
        secs = max(clock() - start, 1e-6)
        print(f"Copied to {os.path.relpath(dest, REPO)} in {secs:.1f} s ({size / 1e6 / secs:.1f} MB/s)")
        print("If the robot code is still running, this log is still being written: the copy has "
              "everything up to now, and fetch again later replaces it.")

    if "--report" in flags:
        print()
        _announce(dest, "fetched from the robot")
        record = "--no-record" not in flags
        return _run("match_report.py", dest, *(["--record"] if record else []))
    print(f"Next: python analyze.py {os.path.basename(dest)[:-len('.wpilog')]}")
    return 0


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

    if cmd == "fetch":
        return fetch(argv)

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
