"""Ask a LOCAL AI model about one log: no internet, no account.

    python tools/local_ai.py logs/<file>.wpilog "Why did the robot feel slow?"
    python analyze.py ask q57 "Why did it brown out?"      (same thing, newest log if no selector)

It talks to any OpenAI-compatible server (oMLX, LM Studio, Ollama, llama.cpp). The model never runs
shell commands: it may only call the four tools below, which run this repo's own scripts read-only.

Why not just run Claude Code or Gemini CLI against the local model? They work, but they re-send tens
of thousands of tokens of their own instructions on every step: one report took 45 minutes on a
27B model. This loop sends a short prompt cut from GEMINI.md and caps the tool calls, so the same
report takes about a minute.

Settings (flags win over environment variables):
    --url    LOCAL_AI_URL      default http://localhost:8000/v1   (oMLX's default port)
    --model  LOCAL_AI_MODEL    default qwen3.8-27b
    key      LOCAL_AI_API_KEY  (or OMLX_API_KEY); leave unset if your server has no key
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "qwen3.8-27b"
MAX_TOOL_CALLS = 6
DEFAULT_QUESTION = "What went wrong in this match, and what should we check first?"

# GEMINI.md sections the model gets. The rest (repo layout, shell commands, custom digging) is for
# agents that run commands, and only costs time here.
_SECTIONS = ["The 2026 robot", "Diagnosis playbook", "Vision and localization",
             "Pitfalls when reading these logs", "Answer format"]

_HOW_TO_WORK = """\
You help FRC Team 9584 high-school students find out what their robot did, from one match log.
You have tools that run the team's analysis scripts. You cannot run anything else.

How to work:
1. Call run_report first. It prints a Summary (PROBLEM / WATCH lines) and then tables.
2. The Summary does not list everything. Go through the tables section by section and match each
   number against the "Diagnosis playbook" below. A playbook row that fits counts as a finding
   even if the Summary did not mention it.
3. Call read_findings to see whether this is a repeat of a past problem, and what fixed it.
4. If you suspect a problem, compare with other matches using history (call it with no patterns to
   list the metric names). Use vision_replay only for pose jumps.
5. Stop calling tools once you can answer. Then write the answer in the format at the end.

Rules:
- Never state a number you did not get from a tool.
- Say "the log shows X" for measurements and "this suggests Y" for interpretation.
- Hardware first: most problems were wiring, batteries, magnets, obstructions.
- When a device stops responding, its last values are held in the log: do not trust its currents
  or speeds while it is disconnected.
"""


def build_prompt(guide_path=os.path.join(REPO, "GEMINI.md"), robot_2027=False):
    """The system prompt: how to work, plus the GEMINI.md sections a log-reading model needs.
    Read at run time, so editing GEMINI.md updates the local model too."""
    with open(guide_path, encoding="utf-8") as f:
        text = f.read()
    parts = [_HOW_TO_WORK]
    for title in _SECTIONS:
        m = re.search(rf"^## {re.escape(title)}.*?(?=^## |\Z)", text, re.S | re.M)
        if not m:
            continue
        section = m.group(0)
        if not robot_2027:  # the skeleton-robot subsection only applies to 2027 logs
            section = re.sub(r"^### Logs from skeleton-based robot code.*?(?=^## |^### |\Z)", "", section,
                             flags=re.S | re.M)
        parts.append(section.strip())
    prompt = "\n\n".join(parts)
    # This tool cannot write files: have the model hand the student the entry instead.
    return prompt.replace("Offer to add a `history/findings.md` entry once the cause is confirmed.",
                          "Once the cause is confirmed, give a draft `history/findings.md` entry for the "
                          "student to add.")


def _fn(name, desc, props):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": []}}}


TOOLS = [
    _fn("run_report", "Run every check on the log and return the one-page report (Summary + tables).",
        {"only": {"type": "string", "description": "optional comma list of parts: timeline,power,comms,"
                  "devices,drivetrain,intake,shooting,vision,cameras,loop"}}),
    _fn("history", "Compare metrics across all recorded matches. No patterns lists the metric names.",
        {"patterns": {"type": "array", "items": {"type": "string"},
                      "description": "text the metric names must contain, e.g. ['supply_limit']"},
         "logs": {"type": "string", "description": "optional comma list of log-name text, e.g. 'q8,q19'"}}),
    _fn("vision_replay", "Replay vision filter rules on the log: which pose jumps they would prevent.",
        {"max_heading_error": {"type": "number"}, "max_correction": {"type": "number"},
         "min_tags": {"type": "integer"}, "max_dist": {"type": "number"},
         "reject_field_center": {"type": "boolean"}}),
    _fn("read_findings", "Read history/findings.md: past problems, their causes, fixes and results.", {}),
]


def tool_command(name, args, log, robot=None):
    """The script a tool call runs, as an argument list, or None for an unknown tool."""
    py = [sys.executable]
    rob = ["--robot", robot] if robot else []
    if name == "run_report":
        only = str(args.get("only") or "").strip()
        return py + [os.path.join("tools", "match_report.py"), log, *rob] + (["--only", only] if only else [])
    if name == "history":
        pats = args.get("patterns") or []
        if isinstance(pats, str):
            pats = pats.split()
        logs = str(args.get("logs") or "").strip()
        return py + [os.path.join("tools", "history.py"), *[str(p) for p in pats]] + (["--logs", logs] if logs else [])
    if name == "vision_replay":
        cmd = py + [os.path.join("tools", "vision_replay.py"), log, *rob]
        for k in ("max_heading_error", "max_correction", "min_tags", "max_dist"):
            if args.get(k) is not None:
                cmd += ["--" + k.replace("_", "-"), str(args[k])]
        if args.get("reject_field_center"):
            cmd.append("--reject-field-center")
        return cmd
    return None


def run_tool(name, args, log, robot=None, findings=True):
    if name == "read_findings":
        if not findings:
            return "read_findings is turned off for this run."
        with open(os.path.join(REPO, "history", "findings.md"), encoding="utf-8") as f:
            return f.read()
    cmd = tool_command(name, args, log, robot)
    if cmd is None:
        return f"Unknown tool {name!r}. Tools: run_report, history, vision_replay, read_findings."
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)
    return ((p.stdout + p.stderr) or "(no output)")[:12000]


_TEXT_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>|^\s*(\{.*\})\s*$", re.S)


def text_tool_calls(content):
    """Some models (qwen2.5) write the tool call as plain text instead of using the API's tool_calls
    field. Recognise {"name": ..., "arguments": {...}} on its own or inside <tool_call> tags."""
    calls = []
    for m in _TEXT_CALL.finditer(content or ""):
        try:
            obj = json.loads(m.group(1) or m.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("name"), str):
            args = obj.get("arguments", obj.get("parameters", {}))
            calls.append({"id": f"text{len(calls)}", "type": "function",
                          "function": {"name": obj["name"],
                                       "arguments": args if isinstance(args, str) else json.dumps(args)}})
    return calls


def post(url, key, body, timeout=1200):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def ask(log, question, model, url, key, robot=None, findings=True, think=False, max_tools=MAX_TOOL_CALLS,
        say=lambda s: None, send=post):
    """Run the tool loop and return (answer, steps). say() gets one line per step."""
    system = build_prompt(robot_2027=bool(robot and "2027" in robot))
    if not findings:
        system = re.sub(r"^3\. Call read_findings.*\n", "", system, flags=re.M)
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": f"Log: {os.path.relpath(log, REPO)}\n\n{question}"}]
    tools = TOOLS if findings else [t for t in TOOLS if t["function"]["name"] != "read_findings"]
    used, steps = 0, []
    while True:
        final = used >= max_tools
        if final:
            msgs.append({"role": "user", "content": "Tool limit reached. Write your answer now."})
        body = {"model": model, "temperature": 0, "max_tokens": 3000, "messages": msgs,
                "chat_template_kwargs": {"enable_thinking": think}}
        if not final:
            body["tools"] = tools
        t0 = time.time()
        msg = send(url, key, body)["choices"][0]["message"]
        content = msg.get("content") or ""
        calls = msg.get("tool_calls") or ([] if final else text_tool_calls(content))
        steps.append({"secs": round(time.time() - t0, 1), "tools": [c["function"]["name"] for c in calls]})
        if not calls or final:
            return content.strip(), steps
        msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
        for c in calls:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            say(f"  -> {c['function']['name']} {json.dumps(args) if args else ''}".rstrip())
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""),
                         "content": run_tool(c["function"]["name"], args, log, robot, findings)})
            used += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, )
    ap.add_argument("log", help=".wpilog file")
    ap.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    ap.add_argument("--model", default=os.environ.get("LOCAL_AI_MODEL", DEFAULT_MODEL))
    ap.add_argument("--url", default=os.environ.get("LOCAL_AI_URL", DEFAULT_URL))
    ap.add_argument("--robot", help="robot description to pass to the scripts (default: picked from the log)")
    ap.add_argument("--no-findings", action="store_true", help="do not let the model read history/findings.md")
    ap.add_argument("--think", action="store_true", help="let a thinking model think (much slower)")
    ap.add_argument("--max-tools", type=int, default=MAX_TOOL_CALLS)
    a = ap.parse_args(argv)
    key = os.environ.get("LOCAL_AI_API_KEY") or os.environ.get("OMLX_API_KEY")
    log = os.path.abspath(a.log)
    print(f"Asking {a.model} at {a.url} (this takes about a minute)...", file=sys.stderr)
    t0 = time.time()
    try:
        answer, steps = ask(log, a.question, a.model, a.url, key, a.robot, not a.no_findings, a.think,
                            a.max_tools, say=lambda s: print(s, file=sys.stderr, flush=True))
    except urllib.error.HTTPError as e:
        hint = {401: "the server wants an API key: set LOCAL_AI_API_KEY",
                404: f"the server does not know model {a.model!r}: check --model against its model list"}
        print(f"Model server said HTTP {e.code}: {hint.get(e.code, e.read()[:300])}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Could not reach a model server at {a.url} ({e.reason}). Is it running?",
              file=sys.stderr)
        return 1
    print(f"({len(steps)} model calls, {sum(len(s['tools']) for s in steps)} tool calls, "
          f"{time.time() - t0:.0f} s)\n", file=sys.stderr)
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
