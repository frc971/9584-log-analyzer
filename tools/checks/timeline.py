"""When the robot was enabled, in which mode, and whether auto ran its full length."""

from .common import Result

MATCH_TYPES = {0: "none", 1: "practice", 2: "qualification", 3: "elimination"}
AUTO_LENGTH_S = 20.0   # 2026 REBUILT; change if the game changes


def check(ctx):
    r = Result("Match timeline")
    log = ctx.log
    r.metric("match_number", ctx.match_number)
    r.metric("fms", int(ctx.fms))
    auto_s = sum(b - a for a, b in ctx.auto_windows)
    teleop_s = sum(b - a for a, b in ctx.teleop_windows)
    r.metric("auto_enabled_s", auto_s)
    r.metric("teleop_enabled_s", teleop_s)
    r.lines.append(f"- Match: {MATCH_TYPES.get(ctx.match_type, ctx.match_type)} {ctx.match_number}, "
                   f"FMS {'attached' if ctx.fms else 'not attached'}, log length {log.end_time:.0f} s")
    r.lines.append(f"- Enabled: auto {auto_s:.1f} s, teleop {teleop_s:.1f} s, "
                   f"{len(ctx.enabled_windows)} enabled period(s)")

    # Auto disabled early while the match clock kept running (seen in p8, q8 and q19 at mttd).
    if ctx.fms and ctx.auto_windows:
        a, b = ctx.auto_windows[0]
        if b - a < AUTO_LENGTH_S - 1:
            clock = log.series("/DriverStation/MatchTime")
            left = clock.at(b + 0.5)
            if left is not None and left > 1:
                r.problem(f"Auto was disabled after {b - a:.1f} s while the match clock kept running "
                          f"({left:.0f} s left). Not a code crash: someone or something disabled it "
                          f"(A-stop, field, or drive team).")
    if ctx.fms and not ctx.auto_windows:
        r.watch("No autonomous period was enabled in this FMS match.")
    return r
