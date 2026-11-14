"""analyze.py's log choice. Always runs (no event logs needed):
    python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import analyze  # noqa: E402


class LogChoice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, name, mtime=1_000_000_000):
        path = os.path.join(self.dir, name)
        open(path, "wb").close()
        os.utime(path, (mtime, mtime))
        return path

    def _names(self):
        return [os.path.basename(p) for p in analyze.list_logs(self.dir)]

    def test_newest_by_name_when_file_dates_are_identical(self):
        # Copying logs onto a laptop gives them all the same date: the name has to decide.
        self._make("akit_26-11-07_17-32-08_mttd_q8.wpilog")
        self._make("akit_26-11-07_23-20-50_mttd_q38.wpilog")
        self._make("akit_26-11-07_15-48-33_mttd.wpilog")
        self.assertEqual(self._names()[0], "akit_26-11-07_23-20-50_mttd_q38.wpilog")

    def test_name_beats_a_misleading_file_date(self):
        self._make("akit_26-11-08_18-23-38_mttd_q68.wpilog", mtime=1_000)
        self._make("akit_26-11-07_23-20-50_mttd_q38.wpilog", mtime=2_000_000_000)
        self.assertEqual(self._names()[0], "akit_26-11-08_18-23-38_mttd_q68.wpilog")

    def test_added_match_name_does_not_change_the_order(self):
        # "q8" sorts after "q38" as text; only the timestamp may decide.
        self._make("akit_26-11-07_17-32-08_mttd_q8.wpilog")
        self._make("akit_26-11-07_23-20-50_mttd_q38_renamed.wpilog")
        self.assertEqual(self._names()[0], "akit_26-11-07_23-20-50_mttd_q38_renamed.wpilog")

    def test_name_without_timestamp_falls_back_to_file_date(self):
        self._make("akit_26-11-07_17-32-08.wpilog")                       # 2026-11-07
        self._make("bench_test.wpilog", mtime=2_000_000_000)              # 2033, by file date
        self.assertEqual(self._names()[0], "bench_test.wpilog")

    def test_only_wpilog_files(self):
        self._make("akit_26-11-07_17-32-08.wpilog")
        self._make("README.md", mtime=2_000_000_000)
        self.assertEqual(self._names(), ["akit_26-11-07_17-32-08.wpilog"])

    def test_selector(self):
        self._make("akit_26-11-07_17-32-08_mttd_q8.wpilog")
        self._make("akit_26-11-07_23-20-50_mttd_q38.wpilog")
        path, note = analyze.find_log("Q38", self.dir)
        self.assertTrue(path.endswith("q38.wpilog"))
        path, note = analyze.find_log("mttd", self.dir)
        self.assertTrue(path.endswith("q38.wpilog"))
        self.assertIn("newest of 2", note)
        with self.assertRaises(SystemExit):
            analyze.find_log("q99", self.dir)

    def test_empty_folder_says_what_to_do(self):
        with self.assertRaises(SystemExit) as e:
            analyze.find_log(None, self.dir)
        self.assertIn("Getting a log", str(e.exception))


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._run, analyze._run = analyze._run, lambda script, *a: self.calls.append((script, a)) or 0
        self._find, analyze.find_log = analyze.find_log, lambda sel=None, folder=None: ("logs/x.wpilog", "")

    def tearDown(self):
        analyze._run, analyze.find_log = self._run, self._find

    def test_default_is_full_report_and_records(self):
        analyze.main([])
        self.assertEqual(self.calls, [("match_report.py", ("logs/x.wpilog", "--record"))])

    def test_no_record(self):
        analyze.main(["--no-record"])
        self.assertEqual(self.calls, [("match_report.py", ("logs/x.wpilog",))])

    def test_a_part_never_records(self):
        # A partial run would replace the log's saved row with fewer numbers.
        analyze.main(["drive", "q38"])
        self.assertEqual(self.calls, [("match_report.py", ("logs/x.wpilog", "--only", "drivetrain"))])

    def test_passthrough(self):
        analyze.main(["q38", "--robot", "robot/2026.toml"])
        self.assertEqual(self.calls[0][1], ("logs/x.wpilog", "--robot", "robot/2026.toml", "--record"))

    def test_trend(self):
        analyze.main(["trend", "magnet", "--logs", "q51"])
        self.assertEqual(self.calls, [("history.py", ("magnet", "--logs", "q51"))])


if __name__ == "__main__":
    unittest.main()
