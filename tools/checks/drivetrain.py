"""Swerve module comparison, steering effort, robot speed, heading-hold, and unwanted rotation.

The core idea: all four modules are told to do similar things, so compare them. One module that
differs is a module problem. All four struggling together is a limit, battery, or floor problem.
"""

import math

from .common import Result, pct, wrap_deg


def _module_omega(states, positions):
    """Robot rotation rate implied by four module states [(speed, angle_rad), ...]."""
    total = 0.0
    for (speed, angle), (x, y) in zip(states, positions):
        vx, vy = speed * math.cos(angle), speed * math.sin(angle)
        total += (x * vy - y * vx) / (x * x + y * y)
    return total / len(positions)


def check(ctx):
    r = Result("Drivetrain")
    log, dt, th = ctx.log, ctx.robot["drivetrain"], ctx.th
    prefix = dt["module_prefix"]
    drive = ctx.driving_grid()
    if len(drive) < 50:
        r.lines.append("- Not enough driving in this log to compare modules.")
        return r
    r.metric("driving_s", len(drive) * ctx.STEP)

    # Robot speed.
    speeds = log.out("Drive/MeasuredSpeeds")
    v = [math.hypot(*speeds.at(t)[:2]) for t in drive if speeds.at(t)]
    r.metric("speed_p50_mps", pct(v, 0.5))
    r.metric("speed_p90_mps", pct(v, 0.9))
    r.metric("speed_max_mps", max(v) if v else None)
    r.lines.append(f"- Driving {len(drive) * ctx.STEP:.0f} s; robot speed typical {pct(v, .5):.2f} m/s, "
                   f"90th percentile {pct(v, .9):.2f} m/s, max {max(v):.2f} m/s "
                   f"(top speed setting {dt['max_speed_mps']} m/s)")

    rows = []
    steer_med = {}
    for m in dt["modules"]:
        p = prefix + m + "/"
        tgt, meas = log.series(p + "TargetSpeedMetersPerSec"), log.series(p + "MeasuredSpeedMetersPerSec")
        ds, dsu = log.series(p + "Drive/StatorCurrentAmps"), log.series(p + "Drive/SupplyCurrentAmps")
        se, ss = log.series(p + "Steer/ErrorDegrees"), log.series(p + "Steer/StatorCurrentAmps")
        sf, df = log.series(p + "Steer/Faults"), log.series(p + "Drive/Faults")
        dtemp, stemp = log.series(p + "Drive/TempCelsius"), log.series(p + "Steer/TempCelsius")
        ratio = [abs(meas.at(t) or 0) / abs(tgt.at(t)) for t in drive if abs(tgt.at(t) or 0) > 1.0]
        d_stat = [abs(ds.at(t) or 0) for t in drive]
        d_sup = [abs(dsu.at(t) or 0) for t in drive]
        s_err = [abs(se.at(t) or 0) for t in drive]
        s_cur = [abs(ss.at(t) or 0) for t in drive]
        s_lim = 100 * sum("StatorCurrentLimit" in (sf.at(t) or "") for t in drive) / len(drive)
        d_lim = 100 * sum("SupplyCurrentLimit" in (df.at(t) or "") for t in drive) / len(drive)
        steer_med[m] = pct(s_err, 0.5)
        vals = {
            "speed_ratio_p50": pct(ratio, 0.5), "drive_stator_p50_a": pct(d_stat, 0.5),
            "drive_supply_p50_a": pct(d_sup, 0.5), "drive_supply_limit_pct": d_lim,
            "steer_error_p50_deg": pct(s_err, 0.5), "steer_error_p90_deg": pct(s_err, 0.9),
            "steer_stator_p50_a": pct(s_cur, 0.5), "steer_limit_pct": s_lim,
            "drive_temp_max_c": max(dtemp.values) if dtemp else None,
            "steer_temp_max_c": max(stemp.values) if stemp else None,
        }
        for k, x in vals.items():
            r.metric(f"{m}.{k}", x)
        rows.append([m, vals["speed_ratio_p50"], vals["drive_stator_p50_a"], vals["drive_supply_p50_a"],
                     f"{d_lim:.0f}%", vals["steer_error_p50_deg"], vals["steer_error_p90_deg"],
                     vals["steer_stator_p50_a"], f"{s_lim:.0f}%", vals["drive_temp_max_c"]])
        if vals["drive_temp_max_c"] and vals["drive_temp_max_c"] > 80:
            r.problem(f"{m} drive motor reached {vals['drive_temp_max_c']:.0f} C (it weakens above ~90 C).")

    r.table(["Module", "speed/target", "drive stator A", "drive supply A", "on supply limit",
             "steer err p50 deg", "steer err p90 deg", "steer stator A", "on steer limit", "drive max C"], rows)

    # One module unlike the others?
    ratios = {m: r.metrics.get(f"{m}.speed_ratio_p50") for m in dt["modules"]}
    good = [x for x in ratios.values() if x]
    if good:
        med = pct(good, 0.5)
        for m, x in ratios.items():
            if x is not None and med and x < 0.6 * med:
                r.problem(f"{m} reaches much less of its target speed ({x:.2f}) than the others ({med:.2f}): "
                          f"that drive motor is weak, binding, or not responding.")
    worst = max(steer_med, key=lambda k: steer_med[k] or 0)
    if (steer_med[worst] or 0) > th.get("steer_error_warn_deg", 10):
        r.watch(f"Wheels lag their target angles (typical error up to {steer_med[worst]:.0f} deg, worst {worst}). "
                f"Lagging wheels make the robot curve/rotate on its own.")
    limit_pcts = [r.metrics.get(f"{m}.steer_limit_pct", 0) for m in dt["modules"]]
    if max(limit_pcts) > th.get("steer_limit_warn_pct", 40):
        r.watch(f"Steer motors sat on their {dt['steer_stator_limit_a']} A limit up to {max(limit_pcts):.0f}% of "
                f"driving. If they turn freely on blocks, this is carpet grip and the limit is too low.")

    _heading_hold(ctx, r, drive)
    _rotation_drift(ctx, r)
    return r


def _heading_hold(ctx, r, drive):
    """When the code holds heading, does the robot actually turn the way the correction asks?
    Uses target vs measured module states (no gyro needed)."""
    log, dt = ctx.log, ctx.robot["drivetrain"]
    tgt, meas = log.out("Drive/TargetStates"), log.out("Drive/MeasuredStates")
    state = log.out("Drive/Input/State")
    rot = log.out("Drive/Input/Rotation")
    pos = dt["module_positions"]
    tally = {"held": [0, 0], "manual": [0, 0]}
    for t in drive[::2]:
        ts, ms = tgt.at(t), meas.at(t)
        if not ts or not ms or len(ts) != 4 or len(ms) != 4:
            continue
        c, m = _module_omega(ts, pos), _module_omega(ms, pos)
        if abs(c) < 0.5:
            continue
        s = state.at(t)
        key = "held" if s == "DRIVING_WITH_LOCKED_HEADING" else ("manual" if abs(rot.at(t) or 0) > 0.05 else None)
        if key:
            tally[key][0 if c * m > 0 else 1] += 1
    for key, (same, opp) in tally.items():
        if same + opp:
            r.metric(f"heading_{key}_wrong_way_pct", 100 * opp / (same + opp))
    held, manual = r.metrics.get("heading_held_wrong_way_pct"), r.metrics.get("heading_manual_wrong_way_pct")
    if held is not None:
        r.lines.append(f"- Heading-hold: the robot turned opposite to the correction {held:.0f}% of the time"
                       + (f" (driver-commanded turns: {manual:.0f}%)" if manual is not None else ""))
        if held > ctx.th.get("heading_hold_wrong_way_warn_pct", 30):
            r.watch("Heading-hold is not controlling rotation well. Usually the wheels are not at their target "
                    "angles yet (steering lag, current limit, battery) or the robot is being pushed.")


def _rotation_drift(ctx, r):
    """Unwanted rotation from the gyro while translating with no rotation input. A bad module drifts
    one way; contact and steering lag drift both ways."""
    log, dt = ctx.log, ctx.robot["drivetrain"]
    gyro = log.out(ctx.robot["vision"]["gyro_yaw"])
    fw, lf, rot = log.out("Drive/Input/Forward"), log.out("Drive/Input/Left"), log.out("Drive/Input/Rotation")
    speeds = log.out("Drive/MeasuredSpeeds")
    if not gyro or not fw:
        return
    step = ctx.STEP
    errs = {m: log.series(dt["module_prefix"] + m + "/Steer/ErrorDegrees") for m in dt["modules"]}
    big = []
    onset = {m: 0 for m in dt["modules"]}
    prev = False
    for t in ctx.enabled_grid(ctx.teleop_windows):
        f, l, w = fw.at(t) or 0, lf.at(t) or 0, rot.at(t) or 0
        if math.hypot(f, l) < 0.3 or abs(w) > 1e-9:
            prev = False
            continue
        g0, g1 = gyro.at(t), gyro.at(t + step)
        if g0 is None or g1 is None:
            continue
        rate = wrap_deg(g1 - g0) / step
        sp = speeds.at(t)
        free = sp and math.hypot(sp[0], sp[1]) > 0.5 * min(math.hypot(f, l) * dt["max_speed_mps"], dt["max_speed_mps"])
        is_big = abs(rate) > 45
        if is_big:
            big.append((rate, free))
            if free and not prev:
                e = {m: abs(errs[m].at(t - 0.1) or 0) for m in errs}
                onset[max(e, key=e.get)] += 1
        prev = is_big and free
    if not big:
        return
    free_rates = [x for x, f in big if f]
    ccw = 100 * sum(1 for x in free_rates if x > 0) / max(1, len(free_rates))
    r.metric("drift_events_free", len(free_rates))
    r.metric("drift_ccw_pct", ccw)
    r.lines.append(f"- Unwanted rotation (>45 deg/s with no turn input): {len(big) * step:.0f} s total, "
                   f"{len(free_rates) * step:.0f} s while moving freely; free drift split CCW {ccw:.0f}% / CW {100 - ccw:.0f}%")
    if sum(onset.values()):
        r.lines.append("- Module furthest off its target angle when a free drift started: " +
                       ", ".join(f"{m} {n}" for m, n in sorted(onset.items(), key=lambda kv: -kv[1])))
    # Need enough free driving to call a direction (5 s of drifting samples).
    if len(free_rates) * step >= 5 and (ccw > 70 or ccw < 30):
        r.problem(f"Drift is mostly one direction ({ccw:.0f}% CCW). That points to one module: an encoder "
                  f"offset/calibration or magnet problem, or one weak module. Check the module listed most above.")
