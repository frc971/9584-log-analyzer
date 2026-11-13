"""Season-specific mechanisms (2026: intake, feeder, shooter). Signal names come from robot/<season>.toml,
and every part is skipped if its signals are not in the log, so older logs still work."""

from .common import Result, pct, fmt


def _segments(setting, t_end):
    """[(value, start, end)] for each stretch a string setting held one value."""
    ch = setting.changes()
    return [(v, a, (ch[i + 1][0] if i + 1 < len(ch) else t_end)) for i, (a, v) in enumerate(ch)]


def check_intake(ctx):
    r = Result("Intake")
    log, cfg, th = ctx.log, ctx.robot.get("intake"), ctx.th
    if not cfg or not log.out(cfg["roller_setting"]):
        r.lines.append("- No intake signals in this log.")
        return r
    ang, tgt = log.out(cfg["pivot_angle"]), log.out(cfg["pivot_target"])
    rpm, rcur = log.out(cfg["roller_rpm"]), log.out(cfg["roller_stator"])
    pcur = log.out(cfg["pivot_stator"])
    segs = [s for s in _segments(log.out(cfg["roller_setting"]), log.end_time) if ctx.is_enabled(s[1])]
    intakes = [(a, b) for v, a, b in segs if v == "INTAKE"]
    outtakes = [(a, b) for v, a, b in segs if v == "OUTTAKE"]
    r.metric("intake_runs", len(intakes))
    r.metric("outtake_runs", len(outtakes))
    # Skip the first 0.8 s of each run: the pivot is still moving and the roller spinning up.
    grid = [a + 0.8 + ctx.STEP * i for a, b in intakes for i in range(max(0, int((b - a - 0.8) / ctx.STEP)))]
    r.lines.append(f"- Intake runs: {len(intakes)} ({sum(b - a for a, b in intakes):.0f} s); outtakes: {len(outtakes)}")
    if grid:
        if ang and tgt:
            short = [(tgt.at(t) or 0) - (ang.at(t) or 0) for t in grid if (tgt.at(t) or 0) > cfg["deployed_min_target_deg"]]
            deployed = [ang.at(t) for t in grid if (tgt.at(t) or 0) > cfg["deployed_min_target_deg"]]
            if short:
                s50 = r.metric("intake_short_of_target_p50_deg", pct(short, 0.5))
                r.metric("intake_deployed_p50_deg", pct(deployed, 0.5))
                pc = r.metric("intake_pivot_stator_p50_a", pct([abs(pcur.at(t) or 0) for t in grid], 0.5))
                r.lines.append(f"- Deployed angle typical {fmt(pct(deployed, .5))} deg (target "
                               f"{fmt(tgt.at(grid[0]))}); lift motor typical {fmt(pc)} A")
                if s50 > th.get("intake_short_deg", 5):
                    r.problem(f"The intake stopped {s50:.0f} deg short of its target with the lift motor at "
                              f"{fmt(pc)} A (limit {cfg['pivot_stator_limit_a']} A): something is physically in the way. "
                              f"A short stop at the same angle every time is a solid obstruction, not fuel.")
        if rpm:
            stall = r.metric("roller_stalled_pct", 100 * sum(1 for t in grid if abs(rpm.at(t) or 0) < th.get("roller_stall_rpm", 2000)) / len(grid))
            free = pct([abs(rpm.at(t) or 0) for t in grid], 0.9)
            r.metric("roller_rpm_p90", free)
            r.lines.append(f"- Rollers: free-running ~{fmt(free, 0)} RPM, stalled (< {th.get('roller_stall_rpm', 2000)} RPM) "
                           f"{stall:.0f}% of intaking time; roller current max {fmt(max((abs(x) for x in rcur.values_between(grid[0], grid[-1])), default=None))} A")
            if stall > th.get("roller_stall_warn_pct", 30):
                r.problem(f"Rollers were stalled {stall:.0f}% of intaking time: fuel jammed at the roller. "
                          f"If the intake also stopped short of its target, the roller sits too high and fuel wedges under it.")
    if outtakes:
        durs = [b - a for a, b in outtakes]
        rev = [min((x for x in rpm.values_between(a, b) if x is not None), default=0) for a, b in outtakes] if rpm else []
        r.metric("outtake_p50_s", pct(durs, 0.5))
        r.lines.append(f"- Outtakes lasted typical {pct(durs, .5):.2f} s; fastest reverse reached typical "
                       f"{fmt(pct(rev, .5), 0)} RPM")
        if pct(durs, 0.5) < 0.5:
            r.watch("Outtake presses are too short for the roller to reverse; jams will not clear.")
        if len(outtakes) >= 5:
            stopped = sum(1 for a, b in outtakes if abs(rpm.at(a - 0.2) or 0) < 100) if rpm else 0
            r.watch(f"{len(outtakes)} outtakes: the driver is clearing jams. {stopped} came while the rollers were "
                    f"stopped, i.e. jams the roller could not feel (hopper entrance or elsewhere).")
    # Boot offset: the pivot's zero is wherever it sat at power-on.
    if ang:
        r.metric("intake_boot_angle_deg", ang.values[0])
    return r


def check_shooting(ctx):
    r = Result("Feeding and shooting")
    log, fcfg, scfg = ctx.log, ctx.robot.get("feeder"), ctx.robot.get("shooter")
    if not fcfg:
        return r
    lines = ctx.console_lines()
    starts = [t for t, ln in lines if fcfg["feed_start_text"] in ln and ctx.is_enabled(t)]
    in_auto = sum(1 for t in starts if any(a <= t <= b for a, b in ctx.auto_windows))
    r.metric("feeds_auto", in_auto)
    r.metric("feeds_teleop", len(starts) - in_auto)
    feeder = log.out(fcfg["supply"])
    on = [x for x in feeder.values if x and x > 5]
    r.lines.append(f"- Feeds: {in_auto} in auto, {len(starts) - in_auto} in teleop")
    if on:
        f90 = r.metric("feeder_supply_p90_a", pct(on, 0.9))
        r.lines.append(f"- Feeder current while feeding: 90th percentile {f90:.1f} A (limit {fcfg['supply_limit_a']} A)")
        if f90 >= fcfg["supply_limit_a"] - 1:
            r.watch("The feeder sits on its current limit while feeding: it is the bottleneck for shooting rate.")
    for name in (scfg or {}).get("supply", []):
        s = log.out(name)
        if s:
            r.metric(name.split("/")[-1] + "_max_a", max(x for x in s.values if x is not None))
    if ctx.fms and ctx.teleop_windows and len(starts) - in_auto == 0:
        r.watch("No shots in teleop (defense, or the shoot buttons did not work?).")
    return r
