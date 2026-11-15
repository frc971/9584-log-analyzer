"""tools/local_ai.py without a model server: a fake server replays scripted replies.
    python -m unittest discover tests
"""

import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import analyze  # noqa: E402
import local_ai  # noqa: E402


def reply(content="", calls=()):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function",
                              "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]
    return {"choices": [{"message": msg}]}


class FakeServer:
    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, url, key, body):
        self.bodies.append(json.loads(json.dumps(body)))
        return self.replies.pop(0)


class Prompt(unittest.TestCase):
    def test_built_from_gemini_md(self):
        p = local_ai.build_prompt()
        self.assertIn("Diagnosis playbook", p)
        self.assertIn("Pitfalls when reading these logs", p)
        self.assertIn("All drive motors on their supply limit", p)
        self.assertNotIn("## Repo layout", p)      # shell/repo instructions are left out
        self.assertNotIn("Custom digging", p)
        self.assertIn("draft `history/findings.md` entry", p)

    def test_skeleton_section_only_for_2027(self):
        self.assertNotIn("Logs from skeleton-based robot code", local_ai.build_prompt())
        self.assertIn("Logs from skeleton-based robot code", local_ai.build_prompt(robot_2027=True))


class Tools(unittest.TestCase):
    def test_commands(self):
        cmd = local_ai.tool_command("run_report", {"only": "power"}, "logs/x.wpilog")
        self.assertEqual(cmd[1:], [os.path.join("tools", "match_report.py"), "logs/x.wpilog", "--only", "power"])
        cmd = local_ai.tool_command("history", {"patterns": ["magnet", "battery"], "logs": "q8"}, "logs/x.wpilog")
        self.assertEqual(cmd[2:], ["magnet", "battery", "--logs", "q8"])
        cmd = local_ai.tool_command("vision_replay", {"max_correction": 1.0, "reject_field_center": True}, "l")
        self.assertEqual(cmd[2:], ["l", "--max-correction", "1.0", "--reject-field-center"])
        self.assertIsNone(local_ai.tool_command("rm", {}, "l"))

    def test_never_records(self):
        # The model must not change history/metrics.csv behind the student's back.
        self.assertNotIn("--record", local_ai.tool_command("run_report", {}, "l"))

    def test_text_tool_calls(self):
        # qwen2.5 writes the call as text instead of using tool_calls.
        calls = local_ai.text_tool_calls('{"name": "run_report", "arguments": {}}')
        self.assertEqual(calls[0]["function"]["name"], "run_report")
        calls = local_ai.text_tool_calls('<tool_call>\n{"name": "history", "arguments": {"patterns": ["x"]}}\n</tool_call>')
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"patterns": ["x"]})
        self.assertEqual(local_ai.text_tool_calls("The robot was slow because {it was}."), [])


class Loop(unittest.TestCase):
    def setUp(self):
        self._run, local_ai.run_tool = local_ai.run_tool, lambda name, args, *a: f"output of {name}"

    def tearDown(self):
        local_ai.run_tool = self._run

    def test_tool_then_answer(self):
        server = FakeServer(reply(calls=[("run_report", {})]), reply("It was CAN 5."))
        answer, steps = local_ai.ask("logs/x.wpilog", "why?", "m", "u", None, send=server)
        self.assertEqual(answer, "It was CAN 5.")
        self.assertEqual([s["tools"] for s in steps], [["run_report"], []])
        tool_msg = server.bodies[1]["messages"][-1]
        self.assertEqual((tool_msg["role"], tool_msg["content"]), ("tool", "output of run_report"))
        self.assertFalse(server.bodies[0]["chat_template_kwargs"]["enable_thinking"])

    def test_cap_forces_an_answer(self):
        server = FakeServer(*[reply(calls=[("history", {})])] * 2, reply("done"))
        answer, _ = local_ai.ask("l", "q", "m", "u", None, max_tools=2, send=server)
        self.assertEqual(answer, "done")
        self.assertNotIn("tools", server.bodies[-1])  # the last call cannot ask for more tools

    def test_text_call_fallback_runs_the_tool(self):
        server = FakeServer(reply('{"name": "run_report", "arguments": {}}'), reply("answer"))
        answer, steps = local_ai.ask("l", "q", "m", "u", None, send=server)
        self.assertEqual((answer, steps[0]["tools"]), ("answer", ["run_report"]))

    def test_no_findings(self):
        server = FakeServer(reply("answer"))
        local_ai.ask("l", "q", "m", "u", None, findings=False, send=server)
        names = [t["function"]["name"] for t in server.bodies[0]["tools"]]
        self.assertNotIn("read_findings", names)
        self.assertNotIn("Call read_findings", server.bodies[0]["messages"][0]["content"])


class AnalyzeAsk(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._run, analyze._run = analyze._run, lambda script, *a: self.calls.append((script, a)) or 0
        self._find, analyze.find_log = analyze.find_log, lambda sel=None, folder=None: (f"logs/{sel}.wpilog", "")

    def tearDown(self):
        analyze._run, analyze.find_log = self._run, self._find

    def test_selector_and_question(self):
        analyze.main(["ask", "q57", "why", "brownout?", "--model", "gemma"])
        self.assertEqual(self.calls, [("local_ai.py", ("logs/q57.wpilog", "why brownout?", "--model", "gemma"))])

    def test_question_only_uses_newest(self):
        analyze.main(["ask", "Why slow?"])
        self.assertEqual(self.calls, [("local_ai.py", ("logs/None.wpilog", "Why slow?"))])


if __name__ == "__main__":
    unittest.main()
