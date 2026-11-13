"""Test vision filter rules against a recorded log, without the robot.

For every vision estimate the robot received, this asks: would these rules have rejected it?
Then it checks the pose jumps in the log: was the estimate that caused each jump rejected?

    python tools/vision_replay.py logs/q68.wpilog
    python tools/vision_replay.py logs/q68.wpilog --max-heading-error 10 --max-correction 1.0 --min-tags 2

Rules (all optional, combine freely):
  --max-heading-error DEG   reject if the estimate's heading is off the gyro by more than this (robot uses 15)
  --max-correction M        reject if the estimate is more than M meters from where the robot thinks it is
  --min-tags N              reject estimates that see fewer than N tags
  --max-dist M              reject estimates whose average tag distance is more than M meters
  --reject-field-center     reject the known bad solve: exactly field center, facing 0 deg

"Correction" is measured against the fused pose just before the estimate arrived (what the estimate
would have corrected).

Logs from the 2026 robot do not record which estimates the robot accepted, so this can only say
what the rules WOULD do. Logs from the skeleton robot (9584-skeleton-robot) do record it
(Vision/Accepted, Vision/RejectReasons): then this also prints what the robot ACTUALLY did and
where the rules here disagree with it, which is the evidence for changing a threshold in the robot's
VisionFilter.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checks.common import Context, pct, wrap_deg  # noqa: E402
from checks.vision import estimates, has_recorded_decisions  # noqa: E402
from match_report import load_robot, pick_robot  # noqa: E402
from wpilog import Log  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--robot", help="robot description (default: picked from the log, as in match_report.py)")
    ap.add_argument("--max-heading-error", type=float)
    ap.add_argument("--max-correction", type=float)
    ap.add_argument("--min-tags", type=int)
    ap.add_argument("--max-dist", type=float)
    ap.add_argument("--reject-field-center", action="store_true")
    a = ap.parse_args()
    log = Log(a.log)
    robot = load_robot(a.robot or pick_robot(log))
    ctx = Context(log, robot)
    vcfg = robot["vision"]
    pose = ctx.log.out("Drive/Pose")
    est = [e for e in estimates(ctx) if e["loops"] > 0]
    if not est:
        print("No vision estimates while enabled.")
        return

    def reasons(e):
        out = []
        prior = pose.at(e["t"] - 0.021)
        e["correction"] = math.hypot(e["x"] - prior[0], e["y"] - prior[1]) if prior else None
        if a.max_heading_error is not None and e["gyro_deg"] is not None and \
                abs(wrap_deg(e["heading_deg"] - e["gyro_deg"])) > a.max_heading_error:
            out.append("heading")
        if a.max_correction is not None and e["correction"] is not None and e["correction"] > a.max_correction:
            out.append("correction")
        if a.min_tags is not None and (e["tags"] or 0) < a.min_tags:
            out.append("tags")
        if a.max_dist is not None and (e["dist"] or 0) > a.max_dist:
            out.append("distance")
        if a.reject_field_center and abs(e["x"] - vcfg["field_length_m"] / 2) < 0.05 \
                and abs(e["y"] - vcfg["field_width_m"] / 2) < 0.05 and abs(e["heading_deg"]) < 0.5:
            out.append("field-center")
        return out

    for e in est:
        e["why"] = reasons(e)
    rejected = [e for e in est if e["why"]]
    print(f"Estimates while enabled: {len(est)} (applied over {sum(e['loops'] for e in est)} robot loops)")
    print(f"Rejected by these rules: {len(rejected)} ({100 * len(rejected) / len(est):.0f}%)")
    for rule in ("heading", "correction", "tags", "distance", "field-center"):
        n = sum(1 for e in rejected if rule in e["why"])
        if n:
            print(f"  {rule}: {n}")
    corr = [e["correction"] for e in est if e["correction"] is not None]
    print(f"Correction size (estimate vs current pose): typical {pct(corr, .5):.2f} m, 90th percentile "
          f"{pct(corr, .9):.2f} m, max {max(corr):.2f} m")
    small = [e for e in rejected if e["correction"] is not None and e["correction"] < 0.3]
    print(f"Rejected estimates that agreed with the pose anyway (< 0.3 m): {len(small)}  "
          f"<- good data these rules would throw away")

    recorded = has_recorded_decisions(est)
    if recorded:
        robot_rej = [e for e in est if e["accepted"] is False]
        reasons = {}
        for e in robot_rej:
            reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
        print(f"\nWhat the robot actually did (recorded): rejected {len(robot_rej)} of {len(est)}"
              + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])) + ")"
                 if reasons else ""))
        only_rules = [e for e in est if e["why"] and e["accepted"]]
        only_robot = [e for e in est if not e["why"] and e["accepted"] is False]
        print(f"  Rejected by these rules but accepted by the robot: {len(only_rules)}")
        print(f"  Rejected by the robot but not by these rules:      {len(only_robot)}"
              + (" (" + ", ".join(sorted({e['reason'] for e in only_robot})) + ")" if only_robot else ""))

    # Pose jumps and the estimate that was being applied when each happened.
    jumps = []
    seq = pose.window(0, ctx.log.end_time)
    for (t0, p0), (t1, p1) in zip(seq, seq[1:]):
        if ctx.is_enabled(t1) and t1 - t0 <= 0.1 and not any(s <= t1 <= s + 0.5 for s, _ in ctx.enabled_windows):
            d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if d > ctx.th.get("pose_jump_m", 0.5):
                jumps.append((t1, d))
    times = [e["t"] for e in est]
    import bisect
    prevented = 0
    print(f"\nPose jumps > {ctx.th.get('pose_jump_m', 0.5)} m: {len(jumps)}")
    for t, d in jumps:
        i = bisect.bisect_right(times, t + 0.001) - 1
        e = est[i] if i >= 0 and t - est[i]["t"] < 0.5 else None
        if e is None:
            print(f"  {t:7.1f} s  {d:4.1f} m  no vision estimate: an odometry jump (a drive motor reconnecting, wheel slip, or a pose reset)")
            continue
        blocked = bool(e["why"])
        prevented += blocked
        robot = "" if not recorded else (
            "; robot accepted it" if e["accepted"] else f"; robot rejected it ({e['reason']})")
        print(f"  {t:7.1f} s  {d:4.1f} m  estimate: {e['tags']} tag(s) at {e['dist'] or 0:.1f} m, heading off gyro "
              f"{abs(wrap_deg(e['heading_deg'] - (e['gyro_deg'] or e['heading_deg']))):.0f} deg -> "
              + ("REJECTED (" + ", ".join(e["why"]) + ")" if blocked else "accepted") + robot)
    if jumps:
        print(f"These rules would have blocked the estimate behind {prevented} of {len(jumps)} jumps.")


if __name__ == "__main__":
    main()
