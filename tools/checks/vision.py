"""Vision and localization: bad pose estimates, pose jumps, estimate quality, camera health.

What the 2026 robot logs (CommandSwerveDrivetrain.periodic): every MegaTag2 estimate it received
(Vision/Poses, TagCounts, AvgTagDists, StdDevsXY), the fused pose (Drive/Pose) and the gyro yaw.
It does NOT log which estimates were accepted, so "accepted" here means "passed today's filters
as reconstructed below". See GEMINI.md for logging to add next season.
"""

import math

from .common import Result, pct, wrap_deg


def estimates(ctx):
    """Every logged vision estimate as dicts: t, x, y, heading_deg, tags, dist, std_xy, gyro_deg."""
    log, cfg = ctx.log, ctx.robot["vision"]
    poses, tags = log.out(cfg["poses"]), log.out(cfg["tag_counts"])
    dists, stds = log.out(cfg["tag_dists"]), log.out(cfg["std_devs_xy"])
    gyro = log.out(cfg["gyro_yaw"])
    out, last = [], None
    for t, arr in zip(poses.times, poses.values):
        for i, p in enumerate(arr or []):
            key = (round(p[0], 4), round(p[1], 4), round(p[2], 4), i)
            # The robot republishes (and re-applies) the same estimate every loop until a new one
            # arrives. Keep one entry per estimate, counting the loops it was applied in.
            if key == last:
                if ctx.is_enabled(t):
                    out[-1]["loops"] += 1
                continue
            last = key
            tc, dd, sd = tags.at(t) or [], dists.at(t) or [], stds.at(t) or []
            out.append({
                "t": t, "x": p[0], "y": p[1], "heading_deg": math.degrees(p[2]),
                "tags": tc[i] if i < len(tc) else None, "dist": dd[i] if i < len(dd) else None,
                "std_xy": sd[i] if i < len(sd) else None, "gyro_deg": gyro.at(t),
                "loops": 1 if ctx.is_enabled(t) else 0,
            })
    return out


def check(ctx):
    r = Result("Vision and localization")
    log, cfg, th = ctx.log, ctx.robot["vision"], ctx.th
    est = estimates(ctx)
    en = [e for e in est if e["loops"] > 0]
    r.metric("vision_estimates_enabled", len(en))

    # Bad estimates: heading disagrees with the gyro (MegaTag2 echoes the gyro, so this is a bad
    # solve), or outside the field.
    def bad_heading(e):
        return e["gyro_deg"] is not None and abs(wrap_deg(e["heading_deg"] - e["gyro_deg"])) > cfg["max_heading_error_deg"]

    def off_field(e):
        return not (0 <= e["x"] <= cfg["field_length_m"] and 0 <= e["y"] <= cfg["field_width_m"])

    nbad = r.metric("vision_bad_heading", sum(e["loops"] for e in en if bad_heading(e)))
    noff = r.metric("vision_off_field", sum(e["loops"] for e in en if off_field(e)))
    single = [e for e in en if e["tags"] == 1]
    r.metric("vision_single_tag_pct", 100 * len(single) / len(en) if en else None)

    # Pose jumps in the fused pose: the estimate moved further in one loop than the robot can.
    pose = log.out("Drive/Pose")
    jumps = []
    for (t0, p0), (t1, p1) in zip(pose.window(0, log.end_time), pose.window(0, log.end_time)[1:]):
        if not ctx.is_enabled(t1) or t1 - t0 > 0.1:
            continue
        # Auto and teleop start by resetting the pose on purpose; that is not a vision jump.
        if any(a <= t1 <= a + 0.5 for a, _ in ctx.enabled_windows):
            continue
        d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if d > th.get("pose_jump_m", 0.5):
            jumps.append((t1, d))
    r.metric("pose_jumps", len(jumps))
    r.metric("pose_jump_max_m", max((d for _, d in jumps), default=0.0))

    # Where the robot thought it was just before auto (an unseeded pose sits at 0,0 or field center).
    if ctx.auto_windows:
        p = pose.at(ctx.auto_windows[0][0] - 0.05)
        if p:
            r.lines.append(f"- Pose just before auto: x {p[0]:.2f}, y {p[1]:.2f}, heading {math.degrees(p[2]):.0f} deg")

    r.lines.append(f"- Vision estimates while enabled: {len(en)}; single-tag {fmt_pct(r.metrics.get('vision_single_tag_pct'))}; "
                   f"tag distance typical {fmt_num(pct([e['dist'] for e in en], .5))} m; "
                   f"trust (std dev xy) typical {fmt_num(pct([e['std_xy'] for e in en], .5), 3)} m")
    r.lines.append(f"- Robot loops given an estimate whose heading was off the gyro by > {cfg['max_heading_error_deg']} deg: "
                   f"{nbad}; off the field: {noff}")
    r.lines.append(f"- Fused pose jumps > {th.get('pose_jump_m', 0.5)} m in one loop: {len(jumps)}"
                   + (f" (largest {max(d for _, d in jumps):.1f} m at {max(jumps, key=lambda j: j[1])[0]:.1f} s)" if jumps else ""))

    center = sum(e["loops"] for e in en if abs(e["x"] - cfg["field_length_m"] / 2) < 0.05
                 and abs(e["y"] - cfg["field_width_m"] / 2) < 0.05)
    r.metric("vision_field_center_loops", center)
    if nbad > 5:
        r.watch(f"For {nbad} robot loops the camera's estimate disagreed with the gyro heading"
                + (f" ({center} of them the known bad solve: exactly field center, facing 0 deg)" if center else "")
                + ". The robot's heading filter (added 11-07) rejects these; before it, they caused 5 m pose jumps.")
    if len(jumps) > 5:
        r.watch(f"{len(jumps)} pose jumps. Wrong pose -> wrong hub distance -> wrong shot RPM/hood; in auto, "
                f"a wrong path. Run tools/vision_replay.py to test filter rules against this log.")
    if not r.findings and en:
        r.ok("Vision estimates look consistent with the gyro and there are few pose jumps.")
    return r


def fmt_num(x, digits=2):
    return "-" if x is None else f"{x:.{digits}f}"


def fmt_pct(x):
    return "-" if x is None else f"{x:.0f}%"
