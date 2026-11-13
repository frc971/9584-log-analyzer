"""Vision and camera checks on synthetic logs: the 2026 robot's format and the skeleton robot's.

Unlike test_known_findings.py these need no event logs, so they always run:
    python -m unittest discover tests
"""

import math
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from match_report import run  # noqa: E402
from wpilog_writer import Writer  # noqa: E402

ROBOT_2026 = os.path.join(REPO, "robot", "2026.toml")
ROBOT_2027 = os.path.join(REPO, "robot", "2027.toml")
RO = "/RealOutputs/"


def _match(w, enable_at=1.0, disable_at=11.0):
    """A teleop-only FMS match: disabled, enabled from enable_at to disable_at, disabled."""
    w.put("/DriverStation/Enabled", "boolean", 0.0, False)
    w.put("/DriverStation/Autonomous", "boolean", 0.0, False)
    w.put("/DriverStation/FMSAttached", "boolean", 0.0, True)
    w.put("/DriverStation/MatchNumber", "int64", 0.0, 7)
    w.put("/DriverStation/MatchType", "int64", 0.0, 2)
    w.put("/DriverStation/Enabled", "boolean", enable_at, True)
    w.put("/DriverStation/Enabled", "boolean", disable_at, False)


def _report(w, robot, only):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "synthetic.wpilog")
        w.save(path)
        _, results = run(path, robot, set(only))
    metrics = {f"{k}.{n}": v for k, res in results for n, v in res.metrics.items()}
    findings = [(k, s, t) for k, res in results for s, t in res.findings]
    return metrics, findings


def _has(findings, check, severity, text):
    return any(k == check and s == severity and text in t for k, s, t in findings)


def _steady_robot(w, t0=0.0, t1=12.0, x=3.0, y=4.0, heading_deg=30.0):
    """Robot sitting at one pose with the gyro agreeing, logged every loop like the robot does."""
    t = t0
    while t <= t1:
        w.put(RO + "Drive/Pose", "struct:Pose2d", t, (x, y, math.radians(heading_deg)))
        w.put(RO + "Vision/GyroYawDegrees", "double", t, heading_deg)
        t += 0.02


class Format2026(unittest.TestCase):
    """A 2026-style log: estimates only, no robot verdicts. Behaviour must not change."""

    def test_reconstructs_without_recorded_decisions(self):
        w = Writer()
        _match(w)
        _steady_robot(w)
        # One good estimate and the mttd bad solve (field center, facing 0 deg), each held for 10
        # loops: the 2026 robot republished an estimate every loop until a new one arrived.
        for i in range(10):
            t = 2.0 + 0.02 * i
            w.put(RO + "Vision/Poses", "struct:Pose2d[]", t, [(3.0, 4.0, math.radians(30))])
            w.put(RO + "Vision/TagCounts", "double[]", t, [2.0])
            w.put(RO + "Vision/AvgTagDists", "double[]", t, [2.0])
            w.put(RO + "Vision/StdDevsXY", "double[]", t, [0.1])
        for i in range(10):
            t = 4.0 + 0.02 * i
            w.put(RO + "Vision/Poses", "struct:Pose2d[]", t, [(8.27, 4.035, 0.0)])
        m, f = _report(w, ROBOT_2026, ["vision", "cameras"])
        self.assertEqual(m["vision.vision_estimates_enabled"], 2)
        self.assertEqual(m["vision.vision_bad_heading"], 10)
        self.assertEqual(m["vision.vision_field_center_loops"], 10)
        self.assertTrue(_has(f, "vision", "watch", "disagreed with the gyro heading"))
        self.assertNotIn("vision.vision_accepted", m)
        self.assertFalse([k for k in m if k.startswith("cameras.")], "no camera signals in a 2026 log")


class FormatSkeleton(unittest.TestCase):
    """A skeleton-robot log: per-estimate verdicts, odometry pose, camera health."""

    def _log(self, accept_bad=False):
        w = Writer()
        _match(w)
        _steady_robot(w)
        # Four new estimates, one per 0.5 s. Each array is written in the same loop as
        # Vision/Poses, but ONLY when its value changes, as AdvantageKit does: Vision/Accepted is
        # [True] for the first two and is not written again for the second.
        rows = [
            (2.0, (3.02, 4.0, 30), 2, True, "ACCEPTED", 0.02),
            (2.5, (3.01, 4.0, 30), 2, True, "ACCEPTED", 0.01),
            (3.0, (8.27, 4.03, 0), 2, accept_bad, "ACCEPTED" if accept_bad else "HEADING_MISMATCH", 5.3),
            (3.5, (6.0, 4.0, 30), 1, False, "LARGE_CORRECTION", 3.0),
        ]
        last = {}

        def put_changed(name, type_name, t, value):
            if last.get(name) != value:
                w.put(RO + name, type_name, t, value)
                last[name] = value

        for t, (x, y, h), tags, acc, why, res in rows:
            put_changed("Vision/Poses", "struct:Pose2d[]", t, [(x, y, math.radians(h))])
            put_changed("Vision/TagCounts", "double[]", t, [float(tags)])
            put_changed("Vision/AvgTagDists", "double[]", t, [2.0])
            put_changed("Vision/StdDevsXY", "double[]", t, [0.1])
            put_changed("Vision/Accepted", "boolean[]", t, [acc])
            put_changed("Vision/RejectReasons", "string[]", t, [why])
            put_changed("Vision/ResidualMeters", "double[]", t, [res])
            put_changed("Vision/EstimateCameras", "string[]", t, ["limelight-front"])
        # Cameras: front sends frames at a steady 60 fps (so Fps is written ONCE); back never does.
        w.put(RO + "Vision/Cameras/limelight-front/Connected", "boolean", 0.0, True)
        w.put(RO + "Vision/Cameras/limelight-front/Fps", "double", 0.0, 60.0)
        w.put(RO + "Vision/Cameras/limelight-front/CpuTempC", "double", 0.0, 45.0)
        w.put(RO + "Vision/Cameras/limelight-back/Connected", "boolean", 0.0, False)
        w.put(RO + "Vision/Cameras/limelight-left/Connected", "boolean", 0.0, True)
        w.put(RO + "Vision/Cameras/limelight-left/Connected", "boolean", 5.0, False)
        w.put(RO + "Vision/Cameras/limelight-left/Connected", "boolean", 8.0, True)
        w.put(RO + "Vision/Rewind/SaveCount", "int64", 11.1, 1)
        w.put(RO + "Vision/GyroDriftDegrees", "double", 0.5, 7.0)
        return w

    def test_uses_recorded_verdicts_despite_write_on_change(self):
        m, f = _report(self._log(), ROBOT_2027, ["vision"])
        self.assertEqual(m["vision.vision_accepted"], 2)
        self.assertEqual(m["vision.vision_rejected"], 2)
        self.assertEqual(m["vision.vision_reject.HEADING_MISMATCH"], 1)
        self.assertEqual(m["vision.vision_reject.LARGE_CORRECTION"], 1)
        self.assertEqual(m["vision.vision_bad_heading_accepted"], 0)
        self.assertFalse(_has(f, "vision", "watch", "disagreed with the gyro heading"),
                         "with recorded verdicts the 2026 guess must not be shown")
        self.assertEqual(m["vision.rewind_saves"], 1)

    def test_filter_leak_is_a_problem(self):
        m, f = _report(self._log(accept_bad=True), ROBOT_2027, ["vision"])
        self.assertEqual(m["vision.vision_bad_heading_accepted"], 1)
        self.assertTrue(_has(f, "vision", "problem", "filter ACCEPTED"))

    def test_gyro_drift_watch(self):
        m, f = _report(self._log(), ROBOT_2027, ["vision"])
        self.assertEqual(m["vision.gyro_drift_max_deg"], 7.0)
        self.assertTrue(_has(f, "vision", "watch", "Re-zero heading"))

    def test_camera_health(self):
        m, f = _report(self._log(), ROBOT_2027, ["cameras"])
        self.assertEqual(m["cameras.limelight-front.fps_p50"], 60.0, "steady fps written once must still be read")
        self.assertAlmostEqual(m["cameras.limelight-left.not_connected_enabled_s"], 3.0, places=1)
        self.assertTrue(_has(f, "cameras", "problem", "limelight-back never sent a frame"))
        self.assertTrue(_has(f, "cameras", "problem", "limelight-left stopped sending frames for 3.0 s"))


class JumpAttribution(unittest.TestCase):
    """A fused-pose jump is vision if raw odometry did not jump with it, odometry if it did."""

    def test_vision_and_odometry_jumps(self):
        w = Writer()
        _match(w)
        t = 0.0
        while t <= 12.0:
            x = 3.0 + (1.0 if t >= 4.0 else 0.0) + (1.0 if t >= 6.0 else 0.0)  # jumps at 4 s and 6 s
            odo_x = 3.0 + (1.0 if t >= 6.0 else 0.0)                         # odometry jumps only at 6 s
            w.put(RO + "Drive/Pose", "struct:Pose2d", t, (x, 4.0, 0.0))
            w.put(RO + "Drive/OdometryPose", "struct:Pose2d", t, (odo_x, 4.0, 0.0))
            w.put(RO + "Vision/GyroYawDegrees", "double", t, 0.0)
            t += 0.02
        w.put(RO + "Vision/Poses", "struct:Pose2d[]", 2.0, [(3.0, 4.0, 0.0)])
        w.put(RO + "Vision/Accepted", "boolean[]", 2.0, [True])
        w.put(RO + "Vision/RejectReasons", "string[]", 2.0, ["ACCEPTED"])
        m, _ = _report(w, ROBOT_2027, ["vision"])
        self.assertEqual(m["vision.pose_jumps"], 2)
        self.assertEqual(m["vision.pose_jumps_vision"], 1)
        self.assertEqual(m["vision.pose_jumps_odometry"], 1)


if __name__ == "__main__":
    unittest.main()
