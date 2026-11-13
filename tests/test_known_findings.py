"""Each check must still catch the problems we found by hand at the 2026 mttd event.

Run from the repo root:   python -m unittest discover tests
Tests whose log is not in logs/ are skipped (logs are not in git; get them from the team drive).
"""

import glob
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

from match_report import run  # noqa: E402

_cache = {}


def report(suffix):
    """Run every check on the log whose name ends with suffix (e.g. '_q8.wpilog')."""
    if suffix not in _cache:
        matches = glob.glob(os.path.join(REPO, "logs", "*" + suffix))
        if not matches:
            raise unittest.SkipTest(f"log *{suffix} not in logs/")
        ctx, results = run(matches[0])
        metrics = {f"{k}.{n}": v for k, res in results for n, v in res.metrics.items()}
        findings = [(k, s, t) for k, res in results for s, t in res.findings]
        _cache[suffix] = (metrics, findings)
    return _cache[suffix]


def has_finding(findings, check, severity, text):
    return any(k == check and s == severity and text in t for k, s, t in findings)


class Q8DeadDriveMotor(unittest.TestCase):
    """q8: back-left drive motor (CAN 5) failed config at boot and was off the bus most of the match."""

    def test_dead_motor(self):
        m, f = report("_mttd_q8.wpilog")
        self.assertGreater(m["devices.BackLeft.drive.not_responding_s"], 60)
        self.assertTrue(has_finding(f, "devices", "problem", "BackLeft drive (CAN 5)"))

    def test_boot_config_failure(self):
        _, f = report("_mttd_q8.wpilog")
        self.assertTrue(has_finding(f, "devices", "problem", "failed to configure at boot"))

    def test_weak_module_speed(self):
        _, f = report("_mttd_q8.wpilog")
        self.assertTrue(has_finding(f, "drivetrain", "problem", "BackLeft reaches much less"))

    def test_auto_cut_short(self):
        m, f = report("_mttd_q8.wpilog")
        self.assertLess(m["timeline.auto_enabled_s"], 5)
        self.assertTrue(has_finding(f, "timeline", "problem", "Auto was disabled"))

    def test_bad_vision_solve(self):
        m, _ = report("_mttd_q8.wpilog")
        self.assertGreaterEqual(m["vision.vision_field_center_loops"], 15)
        self.assertGreaterEqual(m["vision.pose_jumps"], 10)


class Q19Battery(unittest.TestCase):
    def test_near_brownout(self):
        m, f = report("_mttd_q19.wpilog")
        self.assertLess(m["power.battery_min_v"], 6.5)
        self.assertTrue(has_finding(f, "power", "problem", "Battery fell"))


class Q38RadioAndIntake(unittest.TestCase):
    def test_radio_loss(self):
        m, f = report("_mttd_q38.wpilog")
        self.assertGreaterEqual(m["comms.ds_long_losses"], 1)
        self.assertTrue(has_finding(f, "comms", "problem", "Lost the Driver Station"))

    def test_intake_obstructed_and_jammed(self):
        m, _ = report("_mttd_q38.wpilog")
        self.assertGreater(m["intake.intake_short_of_target_p50_deg"], 5)
        self.assertGreater(m["intake.roller_stalled_pct"], 50)


class P0BatteryPathAndIntakeStop(unittest.TestCase):
    def test_battery_path_resistance(self):
        m, f = report("00-18-10_mttd_p0.wpilog")
        self.assertGreater(m["power.battery_path_ohm"], 0.03)
        self.assertTrue(has_finding(f, "power", "problem", "resistance"))

    def test_intake_stops_at_82(self):
        m, _ = report("00-18-10_mttd_p0.wpilog")
        self.assertAlmostEqual(m["intake.intake_deployed_p50_deg"], 81.5, delta=2)


class Q51Magnet(unittest.TestCase):
    def test_front_left_magnet(self):
        m, f = report("_mttd_q51.wpilog")
        self.assertGreater(m["devices.FrontLeft.magnet_not_green_s"], 60)
        self.assertLess(m["devices.FrontRight.magnet_not_green_s"], 1)
        self.assertTrue(has_finding(f, "devices", "problem", "FrontLeft CANcoder magnet"))

    def test_short_outtake_taps(self):
        m, _ = report("_mttd_q51.wpilog")
        self.assertLess(m["intake.outtake_p50_s"], 0.5)


class PracticeCables(unittest.TestCase):
    """11-08 practice: bad ethernet cables (86 drops) and the Limelight rebooting; outtake burst deployed."""

    def test_comms_drops(self):
        m, f = report("_mttd_p60636.wpilog")
        self.assertGreater(m["comms.comms_disables"], 50)
        self.assertGreaterEqual(m["comms.nt_drops.limelight-shooter"], 2)

    def test_outtake_burst(self):
        m, _ = report("_mttd_p60636.wpilog")
        self.assertGreaterEqual(m["intake.outtake_p50_s"], 0.75)


class Q68Defense(unittest.TestCase):
    def test_shot_only_in_auto(self):
        m, _ = report("_mttd_q68.wpilog")
        self.assertGreaterEqual(m["shooting.feeds_auto"], 1)
        self.assertEqual(m["shooting.feeds_teleop"], 0)

    def test_no_single_module_drift(self):
        _, f = report("_mttd_q68.wpilog")
        self.assertFalse(has_finding(f, "drivetrain", "problem", "Drift is mostly one direction"))


if __name__ == "__main__":
    unittest.main()
