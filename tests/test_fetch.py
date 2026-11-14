"""analyze.py fetch, with ssh/scp replaced by a fake robot. Always runs (no robot needed):
    python -m unittest discover tests
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import analyze  # noqa: E402


class FakeRobot:
    """Answers ssh (the listing) and scp (the copy) like a robot reachable at `address`."""

    def __init__(self, files, address="10.95.84.2", scp_fails_once=False):
        self.files = files            # remote path -> bytes
        self.address = address
        self.scp_fails_once = scp_fails_once
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        target = next(a for a in cmd if "@" in a)
        host = target.split("@", 1)[1].split(":", 1)[0]
        if host != self.address:
            return subprocess.CompletedProcess(cmd, 255, "", "ssh: connect timed out")
        if cmd[0] == "ssh":
            lines = [f"1700000000 {len(data)} {path}" for path, data in self.files.items()]
            # /U/logs is the same folder as /media/sda1/logs: the robot lists files twice.
            lines += [f"1700000000 {len(d)} {p.replace('/media/sda1/logs', '/U/logs')}"
                      for p, d in self.files.items() if p.startswith("/media/sda1/logs")]
            return subprocess.CompletedProcess(cmd, 0, "\n".join(lines) + "\n", "")
        if self.scp_fails_once and "-O" not in cmd:
            return subprocess.CompletedProcess(cmd, 1)
        remote = target.split(":", 1)[1]
        with open(cmd[-1], "wb") as f:
            f.write(self.files[remote])
        return subprocess.CompletedProcess(cmd, 0)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = os.path.join(self.tmp.name, "logs")

    def tearDown(self):
        self.tmp.cleanup()

    def _fetch(self, robot, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = analyze.fetch(list(args), run=robot, folder=self.logs)
        return code, out.getvalue()

    def _local(self):
        return sorted(os.listdir(self.logs))

    def test_copies_the_newest_akit_log_by_name_time(self):
        robot = FakeRobot({
            "/media/sda1/akit_26-11-07_17-32-08.wpilog": b"old",
            "/media/sda1/akit_26-11-08_18-23-38_mttd_q68.wpilog": b"newest",
            "/media/sda1/FRC_20261109_010000.wpilog": b"datalogmanager",  # newer, but not AdvantageKit
        })
        code, out = self._fetch(robot)
        self.assertEqual(code, 0)
        self.assertEqual(self._local(), ["akit_26-11-08_18-23-38_mttd_q68.wpilog"])
        self.assertIn("10.95.84.2", out)

    def test_falls_through_addresses_to_usb(self):
        robot = FakeRobot({"/media/sda1/akit_26-11-08_18-23-38.wpilog": b"x"}, address="172.22.11.2")
        code, out = self._fetch(robot)
        self.assertEqual(code, 0)
        tried = [c[-2].split("@")[1] for c in robot.calls if c[0] == "ssh"]
        self.assertEqual(tried, ["10.95.84.2", "roboRIO-9584-FRC.local", "172.22.11.2"])

    def test_same_file_listed_twice_is_one_log(self):
        logs = analyze._remote_logs("1 5 /U/logs/a.wpilog\n1 5 /media/sda1/logs/a.wpilog\n")
        self.assertEqual(len(logs), 1)

    def test_as_adds_match_name_and_second_fetch_does_nothing(self):
        robot = FakeRobot({"/media/sda1/akit_26-11-08_18-23-38.wpilog": b"match"})
        self._fetch(robot, "--as", "q68")
        self.assertEqual(self._local(), ["akit_26-11-08_18-23-38_q68.wpilog"])
        scps = sum(c[0] == "scp" for c in robot.calls)
        _, out = self._fetch(robot)
        self.assertIn("Already copied", out)
        self.assertEqual(sum(c[0] == "scp" for c in robot.calls), scps)

    def test_a_grown_log_replaces_the_partial_copy(self):
        path = "/media/sda1/akit_26-11-08_18-23-38.wpilog"
        robot = FakeRobot({path: b"part"})
        self._fetch(robot, "--as", "practice")
        robot.files[path] = b"part plus the rest of drive practice"
        self._fetch(robot, "--as", "practice2")
        self.assertEqual(self._local(), ["akit_26-11-08_18-23-38_practice2.wpilog"])

    def test_no_partial_file_left_when_copy_fails(self):
        robot = FakeRobot({"/media/sda1/akit_26-11-08_18-23-38.wpilog": b"x"})
        robot.files = dict(robot.files)
        real = robot.__call__

        def failing(cmd, **kw):
            if cmd[0] == "scp":
                open(cmd[-1], "wb").close()   # scp leaves a partial file behind
                return subprocess.CompletedProcess(cmd, 1)
            return real(cmd, **kw)
        with self.assertRaises(SystemExit):
            self._fetch(failing)
        self.assertEqual(self._local(), [])

    def test_old_scp_protocol_fallback(self):
        robot = FakeRobot({"/media/sda1/akit_26-11-08_18-23-38.wpilog": b"x"}, scp_fails_once=True)
        code, _ = self._fetch(robot)
        self.assertEqual(code, 0)
        self.assertEqual(self._local(), ["akit_26-11-08_18-23-38.wpilog"])

    def test_unreachable_robot_says_so(self):
        robot = FakeRobot({}, address="nowhere")
        with self.assertRaises(SystemExit) as e:
            self._fetch(robot)
        self.assertIn("Could not reach the robot", str(e.exception))

    def test_systemcore_profile(self):
        robot = FakeRobot({"/U/logs/akit_27-01-10_10-00-00.wpilog": b"x"}, address="robot.local")
        code, out = self._fetch(robot, "--systemcore")
        self.assertEqual(code, 0)
        self.assertIn("type: systemcore", out)
        self.assertTrue(all(c[-2 if c[0] == "ssh" else -2].startswith("systemcore@")
                            for c in robot.calls))

    def test_team_number_sets_address(self):
        self.assertEqual(analyze.robot_addresses("roborio", 971)[0], "10.9.71.2")
        self.assertEqual(analyze.robot_addresses("roborio", 9584)[1], "roboRIO-9584-FRC.local")


if __name__ == "__main__":
    unittest.main()
