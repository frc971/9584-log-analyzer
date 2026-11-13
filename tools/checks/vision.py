"""Vision and localization: bad pose estimates, pose jumps, estimate quality, the robot's filter.

Two kinds of robot code write these logs, and this check handles both:

- **2026 robot** (9584-wcp-code-2026): logs every MegaTag2 estimate it received (Vision/Poses,
  TagCounts, AvgTagDists, StdDevsXY), the fused pose (Drive/Pose) and the gyro yaw. It does NOT log
  which estimates it accepted, so "accepted" here means "passed today's filters as reconstructed
  below".
- **Skeleton robot and later** (9584-skeleton-robot): also logs the robot's own verdict on every
  estimate (Vision/Accepted, Vision/RejectReasons, Vision/ResidualMeters), the raw wheel odometry
  pose (Drive/OdometryPose), the gyro drift check and Rewind video saves. When those are in the log
  the report uses them instead of guessing. See that repo's docs/logging.md.

Signal names come from the [vision] section of the robot file; the newer ones have defaults, so a
2026 robot file works on both kinds of log.
"""

import math

from .common import Result, pct, wrap_deg

# Names written by the skeleton robot. A robot file can override any of them under [vision].
RECORDED_DEFAULTS = {
    "accepted": "Vision/Accepted",
    "reject_reasons": "Vision/RejectReasons",
    "residual_m": "Vision/ResidualMeters",
    "estimate_cameras": "Vision/EstimateCameras",
    "odometry_pose": "Drive/OdometryPose",
    "vision_correction": "Drive/VisionCorrectionMeters",
    "gyro_drift": "Vision/GyroDriftDegrees",
    "rewind_count": "Vision/Rewind/SaveCount",
}


def _name(cfg, key):
    return cfg.get(key, RECORDED_DEFAULTS[key])


def estimates(ctx):
    """Every logged vision estimate as dicts: t, x, y, heading_deg, tags, dist, std_xy, gyro_deg,
    loops, and, when the robot recorded them, accepted, reason, residual_m, camera (else None)."""
    log, cfg = ctx.log, ctx.robot["vision"]
    poses, tags = log.out(cfg["poses"]), log.out(cfg["tag_counts"])
    dists, stds = log.out(cfg["tag_dists"]), log.out(cfg["std_devs_xy"])
    gyro = log.out(cfg["gyro_yaw"])
    acc, why = log.out(_name(cfg, "accepted")), log.out(_name(cfg, "reject_reasons"))
    res, cams = log.out(_name(cfg, "residual_m")), log.out(_name(cfg, "estimate_cameras"))
    out, last = [], None
    for t, arr in zip(poses.times, poses.values):
        for i, p in enumerate(arr or []):
            key = (round(p[0], 4), round(p[1], 4), round(p[2], 4), i)
            # The 2026 robot republishes (and re-applies) the same estimate every loop until a new
            # one arrives. Keep one entry per estimate, counting the loops it was applied in.
            if key == last:
                if ctx.is_enabled(t):
                    out[-1]["loops"] += 1
                continue
            last = key
            tc, dd, sd = tags.at(t) or [], dists.at(t) or [], stds.at(t) or []
            # The skeleton logs these arrays in the same loop as Vision/Poses, aligned by index.
            # AdvantageKit only writes a value when it changes, so read them AT this time rather
            # than counting their entries.
            ac, wy, rs, cm = acc.at(t) or [], why.at(t) or [], res.at(t) or [], cams.at(t) or []
            out.append({
                "t": t, "x": p[0], "y": p[1], "heading_deg": math.degrees(p[2]),
                "tags": tc[i] if i < len(tc) else None, "dist": dd[i] if i < len(dd) else None,
                "std_xy": sd[i] if i < len(sd) else None, "gyro_deg": gyro.at(t),
                "loops": 1 if ctx.is_enabled(t) else 0,
                "accepted": ac[i] if i < len(ac) else None,
                "reason": wy[i] if i < len(wy) else None,
                "residual_m": rs[i] if i < len(rs) else None,
                "camera": cm[i] if i < len(cm) else None,
            })
    return out


def has_recorded_decisions(est):
    return any(e["reason"] is not None for e in est)


def pose_jumps(ctx):
    """(t, distance) for each loop where the fused pose moved further than the robot can."""
    log, th = ctx.log, ctx.th
    pose = log.out("Drive/Pose")
    seq = pose.window(0, log.end_time)
    jumps = []
    for (t0, p0), (t1, p1) in zip(seq, seq[1:]):
        if not ctx.is_enabled(t1) or t1 - t0 > 0.1:
            continue
        # Auto and teleop start by resetting the pose on purpose; that is not a vision jump.
        if any(a <= t1 <= a + 0.5 for a, _ in ctx.enabled_windows):
            continue
        d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if d > th.get("pose_jump_m", 0.5):
            jumps.append((t1, d))
    return jumps


def check(ctx):
    r = Result("Vision and localization")
    log, cfg, th = ctx.log, ctx.robot["vision"], ctx.th
    est = estimates(ctx)
    en = [e for e in est if e["loops"] > 0]
    recorded = has_recorded_decisions(en)
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

    jumps = pose_jumps(ctx)
    r.metric("pose_jumps", len(jumps))
    r.metric("pose_jump_max_m", max((d for _, d in jumps), default=0.0))

    # Where the robot thought it was just before auto (an unseeded pose sits at 0,0 or field center).
    pose = log.out("Drive/Pose")
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

    def at_center(e):
        return abs(e["x"] - cfg["field_length_m"] / 2) < 0.05 and abs(e["y"] - cfg["field_width_m"] / 2) < 0.05

    center = r.metric("vision_field_center_loops", sum(e["loops"] for e in en if at_center(e)))
    # The summary's "N of them" must be a subset of nbad: count only center solves that also
    # disagreed with the gyro (a center solve can match the gyro when the robot faces ~0 deg).
    center_bad = sum(e["loops"] for e in en if at_center(e) and bad_heading(e))

    if recorded:
        _recorded_decisions(ctx, r, en, bad_heading, off_field, jumps)
    else:
        if nbad > 5:
            r.watch(f"For {nbad} robot loops the camera's estimate disagreed with the gyro heading"
                    + (f" ({center_bad} of them the known bad solve: exactly field center, facing 0 deg)" if center_bad else "")
                    + ". The robot's heading filter (added 11-07) rejects these; before it, they caused 5 m pose jumps.")
        if len(jumps) > 5:
            r.watch(f"{len(jumps)} pose jumps. Wrong pose -> wrong hub distance -> wrong shot RPM/hood; in auto, "
                    f"a wrong path. Run tools/vision_replay.py to test filter rules against this log.")
    if not r.findings and en:
        r.ok("Vision estimates look consistent with the gyro and there are few pose jumps.")
    return r


def _recorded_decisions(ctx, r, en, bad_heading, off_field, jumps):
    """The robot logged what its filter did with each estimate: report that instead of guessing."""
    log, cfg, th = ctx.log, ctx.robot["vision"], ctx.th
    acc = [e for e in en if e["accepted"]]
    rej = [e for e in en if e["accepted"] is False]
    r.metric("vision_accepted", len(acc))
    r.metric("vision_rejected", len(rej))
    reasons = {}
    for e in rej:
        reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
    for reason, n in reasons.items():
        r.metric(f"vision_reject.{reason}", n)
    r.lines.append(f"- Robot's vision filter (recorded by the robot): accepted {len(acc)}, rejected {len(rej)}"
                   + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])) + ")"
                      if reasons else ""))

    # Did anything the filter should have caught get through? These are filter bugs, not tuning.
    leaked_heading = r.metric("vision_bad_heading_accepted", sum(1 for e in acc if bad_heading(e)))
    leaked_off = r.metric("vision_off_field_accepted", sum(1 for e in acc if off_field(e)))
    if leaked_heading or leaked_off:
        r.problem(f"The robot's filter ACCEPTED {leaked_heading} estimate(s) off the gyro by more than "
                  f"{cfg['max_heading_error_deg']} deg and {leaked_off} off the field. Its rules should reject both: "
                  f"check VisionFilter in the robot code, and that [vision] max_heading_error_deg in the robot file "
                  f"matches the robot's setting.")
    elif any(bad_heading(e) for e in en):
        r.lines.append("- Every estimate off the gyro heading was rejected by the robot.")

    accepted_res = [e["residual_m"] for e in acc if e["residual_m"] is not None]
    if accepted_res:
        r.metric("vision_accepted_residual_p90_m", pct(accepted_res, 0.9))
        r.lines.append(f"- Accepted estimates vs the pose they corrected: typical {pct(accepted_res, .5):.2f} m, "
                       f"90th percentile {pct(accepted_res, .9):.2f} m, max {max(accepted_res):.2f} m")

    # Separate vision jumps from odometry jumps with the raw wheel odometry pose.
    odo = log.out(_name(cfg, "odometry_pose"))
    if odo and jumps:
        vision_j, odo_j = 0, 0
        for t, d in jumps:
            a, b = odo.at(t - 0.021), odo.at(t)
            step = math.hypot(b[0] - a[0], b[1] - a[1]) if a and b else 0.0
            if step > 0.5 * d:
                odo_j += 1
            else:
                vision_j += 1
        r.metric("pose_jumps_vision", vision_j)
        r.metric("pose_jumps_odometry", odo_j)
        r.lines.append(f"- Of the {len(jumps)} pose jumps, {vision_j} came from vision and {odo_j} from wheel odometry "
                       f"(the raw odometry pose jumped too: a drive motor reconnecting, wheel slip, or a pose reset)")
        if vision_j > 5:
            r.watch(f"{vision_j} pose jumps came from vision estimates the robot accepted. Run tools/vision_replay.py "
                    f"to see which rule would have stopped them and how much good data it would cost.")

    corr = log.out(_name(cfg, "vision_correction"))
    vals = [v for v in (corr.at(t) for t in ctx.enabled_grid()) if v is not None] if corr else []
    if vals:
        r.metric("vision_correction_p90_m", pct(vals, 0.9))
        r.metric("vision_correction_max_m", max(vals))
        r.lines.append(f"- How far vision has moved the pose from wheel odometry alone: typical {pct(vals, .5):.2f} m, "
                       f"max {max(vals):.2f} m (it grows as the wheels slip; a sudden step is a vision correction)")

    drift = log.out(_name(cfg, "gyro_drift"))
    if drift:
        worst = max(abs(v) for v in drift.values if v is not None)
        r.metric("gyro_drift_max_deg", worst)
        r.lines.append(f"- Gyro vs the heading the tags give, checked while disabled: worst {worst:.1f} deg")
        if worst > th.get("gyro_drift_warn_deg", 5):
            r.watch(f"While disabled the gyro was {worst:.1f} deg off the heading the AprilTags give. MegaTag2 trusts "
                    f"the gyro, so every position it gives was skewed by that. Re-zero heading before the match.")

    saves = log.out(_name(cfg, "rewind_count"))
    if saves:
        times = [t for t, _ in saves.changes()]
        r.metric("rewind_saves", len(times))
        r.lines.append(f"- Limelight Rewind video saved {len(times)} time(s), at " + ", ".join(f"{t:.0f} s" for t in times)
                       + ". Watch them in each camera's web UI (Rewind tab).")


def fmt_num(x, digits=2):
    return "-" if x is None else f"{x:.{digits}f}"


def fmt_pct(x):
    return "-" if x is None else f"{x:.0f}%"
