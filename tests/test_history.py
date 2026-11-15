"""tools/history.py's table: column names and empty cells. Always runs.
    python -m unittest discover tests
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import history  # noqa: E402


class Labels(unittest.TestCase):
    def test_named_match(self):
        self.assertEqual(history._label("akit_26-11-08_18-23-38_mttd_q68.wpilog"), "mttd_q68")
        self.assertEqual(history._label("akit_26-11-07_03-46-30_mttd_p8.wpilog"), "mttd_p8")

    def test_event_only_logs_stay_unique(self):
        # Several unnamed logs at one event used to all be called "mttd".
        a = history._label("akit_26-11-07_19-56-18_mttd.wpilog")
        b = history._label("akit_26-11-07_20-53-15_mttd.wpilog")
        self.assertEqual(a, "11-07_19:56_mttd")
        self.assertNotEqual(a, b)

    def test_no_spaces(self):
        for name in ("akit_26-11-01_22-53-11.wpilog", "akit_b58e9cd3e12cb379.wpilog",
                     "akit_26-11-08_00-54-49_mttd_p0_blocks.wpilog"):
            self.assertNotIn(" ", history._label(name))


class Table(unittest.TestCase):
    def test_missing_value_is_a_dash(self):
        # A blank cell shifts every later column for anyone reading by eye (or a model splitting on spaces).
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "metrics.csv")
            with open(path, "w") as f:
                f.write("log,power.battery_path_ohm\n"
                        "akit_26-11-07_19-20-49_mttd_q19.wpilog,0.0216\n"
                        "akit_26-11-07_19-56-18_mttd.wpilog,\n"
                        "akit_26-11-08_16-36-42_mttd_q57.wpilog,0.0244\n")
            old, history.METRICS_CSV = history.METRICS_CSV, path
            old_argv, sys.argv = sys.argv, ["history.py", "battery_path"]
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    history.main()
            finally:
                history.METRICS_CSV, sys.argv = old, old_argv
        header, row = out.getvalue().splitlines()
        self.assertEqual(header.split()[1:], ["mttd_q19", "11-07_19:56_mttd", "mttd_q57"])
        self.assertEqual(row.split()[1:], ["0.0216", "-", "0.0244"])


if __name__ == "__main__":
    unittest.main()
