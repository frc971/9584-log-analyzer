"""Shared pieces for the checks: match timeline, sampling, percentiles, and the result format."""

import math


def pct(values, p):
    """p-th percentile (0-1) of a list, or None if empty."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    return v[min(len(v) - 1, int(p * len(v)))]


def wrap_deg(a):
    return (a + 180.0) % 360.0 - 180.0


def fmt(x, digits=1):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


class Result:
    """What one check returns.

    metrics:  flat name -> number, saved to history/metrics.csv
    findings: (severity, text) where severity is "problem", "watch" or "ok"
    lines:    markdown for the report section
    """

    def __init__(self, title):
        self.title = title
        self.metrics = {}
        self.findings = []
        self.lines = []

    def metric(self, name, value):
        if value is not None:
            self.metrics[name] = round(value, 4) if isinstance(value, float) else value
        return value

    def problem(self, text):
        self.findings.append(("problem", text))

    def watch(self, text):
        self.findings.append(("watch", text))

    def ok(self, text):
        self.findings.append(("ok", text))

    def table(self, header, rows):
        self.lines.append("| " + " | ".join(header) + " |")
        self.lines.append("|" + "---|" * len(header))
        for r in rows:
            self.lines.append("| " + " | ".join(fmt(c) for c in r) + " |")
        self.lines.append("")


class Context:
    """The log plus everything the checks share: robot config and when the robot was enabled."""

    STEP = 0.02  # robot loop period; checks sample signals on this grid

    def __init__(self, log, robot):
        self.log = log
        self.robot = robot
        self.th = robot.get("thresholds", {})
        enabled = log.series("/DriverStation/Enabled")
        auto = log.series("/DriverStation/Autonomous")
        self.enabled_windows = _windows(enabled, log.end_time)
        self.auto_windows = []
        self.teleop_windows = []
        for a, b in self.enabled_windows:
            (self.auto_windows if auto.at(a + 0.05) else self.teleop_windows).append((a, b))
        self.match_number = log.series("/DriverStation/MatchNumber").at(log.end_time, 0)
        self.match_type = log.series("/DriverStation/MatchType").at(log.end_time, 0)
        self.fms = any(v for v in log.series("/DriverStation/FMSAttached").values)
        self._state = log.out("Drive/Input/State")

    def enabled_grid(self, windows=None):
        out = []
        for a, b in (self.enabled_windows if windows is None else windows):
            n = int((b - a) / self.STEP)
            out.extend(a + self.STEP * i for i in range(n))
        return out

    def driving_grid(self):
        """Enabled times when the driver is commanding the drivetrain (not idling)."""
        return [t for t in self.enabled_grid() if self._state.at(t) not in (None, "IDLING")]

    def is_enabled(self, t):
        return any(a <= t <= b for a, b in self.enabled_windows)

    def console_lines(self, t0=0.0, t1=None):
        """(t, line) for every line the robot printed."""
        t1 = self.log.end_time if t1 is None else t1
        out = []
        for t, text in self.log.out("Console").window(t0, t1):
            for line in (text or "").splitlines():
                if line.strip():
                    out.append((t, line.strip()))
        return out


def _windows(bool_series, end):
    out, start = [], None
    for t, v in bool_series.changes():
        if v and start is None:
            start = t
        elif not v and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, end))
    return out


def seconds_where(series, predicate, t0, t1):
    """How many seconds between t0 and t1 the series value satisfied predicate (step-held)."""
    total = 0.0
    times, values = series.times, series.values
    if not times:
        return 0.0
    prev_t, prev_v = t0, series.at(t0)
    for t, v in series.window(t0, t1):
        if prev_v is not None and predicate(prev_v):
            total += t - prev_t
        prev_t, prev_v = t, v
    if prev_v is not None and predicate(prev_v):
        total += t1 - prev_t
    return total


def hypot(a, b):
    return math.hypot(a, b)
