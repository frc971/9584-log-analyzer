# 9584 Log Analyzer

Tools for figuring out what the robot did from its logs: why it was slow, why it drifted, why the
intake jammed, why it lost connection. Works with or without AI.

- **Without AI:** run one script and get a one-page report.
- **With AI:** run an AI agent in this folder (Gemini CLI, Claude Code or Codex) and ask questions
  in plain English. It reads the repo's instructions ([GEMINI.md](GEMINI.md)), runs the scripts,
  compares with past matches, and explains.

## One-time setup

1. **Python 3.11 or newer.** Check with `python --version` (Mac/Linux: `python3 --version`).
   Install from [python.org](https://www.python.org/downloads/) if needed. No extra packages needed.
2. **Get this repo** (clone it, or download and unzip).

Steps 1 and 2 are all you need to run the scripts. The rest is only for the AI part.

3. **Pick ONE AI agent** and set it up. Ask a mentor which one the team is using right now and for
   its account or API key. All three work the same way in this repo (same instructions, same
   tasks), so use whichever the team has budget for. A key always goes in an environment variable
   or the agent's own sign-in, **never in a file in this repo**.

### Gemini CLI

1. **Node.js 20 or newer.** Gemini CLI runs on Node.js, and **Node is not installed on Macs or
   Windows laptops by default**. Check with `node --version`. If that says "command not found" (Mac)
   or "not recognized" (Windows), or shows a version below 20:
   - Mac or Windows: download the **LTS** installer from [nodejs.org](https://nodejs.org/) and run
     it. (Mac users who already use Homebrew can run `brew install node` instead.)
   - Close the terminal and open a new one, then check `node --version` again.

   Installing Node needs admin rights. On a school-managed laptop that may be blocked: ask the IT
   department, or use the scripts without AI.
2. **Install it.** `npm` comes with Node.js, so this works once step 1 does:
   ```
   npm install -g @google/gemini-cli
   ```
   Check with `gemini --version`.
   - **Windows:** if `gemini` fails with *"running scripts is disabled on this system"*, that is a
     PowerShell security setting, not a problem with Gemini. Run this once, then open a new
     terminal:
     ```
     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
     ```
   - **Mac:** if `npm install -g` fails with a permission error (EACCES), do not use `sudo`. Either
     install Node with Homebrew (`brew install node`) and try again, or follow npm's
     [fix for EACCES errors](https://docs.npmjs.com/resolving-eacces-permissions-errors-when-installing-packages-globally).
3. **The team's Gemini API key**, from a mentor, as an environment variable:
   - Windows (PowerShell, once): `setx GEMINI_API_KEY "the-key"` then open a new terminal
   - Mac/Linux: add `export GEMINI_API_KEY="the-key"` to `~/.zshrc` or `~/.bashrc`, then open a new
     terminal

### Claude Code

1. **Install it** (no Node.js needed):
   - Mac: `curl -fsSL https://claude.ai/install.sh | bash`
   - Windows (PowerShell): `irm https://claude.ai/install.ps1 | iex`

   Other ways to install are on [Claude Code's setup page](https://code.claude.com/docs/en/setup).
   Check with `claude --version` in a new terminal.
2. **Sign in.** The first time you run `claude` it asks how to sign in: use the team's account or
   API key, from a mentor.

### Codex

1. **Install it** by following [Codex's install page](https://learn.chatgpt.com/docs/codex/cli).
   On a Mac that is `curl -fsSL https://chatgpt.com/codex/install.sh | sh`; Windows and other
   ways are on that page. Check with `codex --version` in a new terminal.
2. **Sign in.** The first time you run `codex` it asks how to sign in: use the team's account or
   API key, from a mentor.

## Getting a log

Logs are written to the USB stick in the roboRIO. Either pull the stick and copy the `.wpilog`, or
in AdvantageScope use **File > Download Logs** (robot address `10.95.84.2`). Copy it into `logs/`.
Add the match to the name, e.g. `akit_26-11-08_18-23-38_mttd_q68.wpilog`.

## Use it without AI

```
python tools/match_report.py logs/akit_26-11-08_18-23-38_mttd_q68.wpilog --record
```
The **Summary** at the top lists every PROBLEM and WATCH item. `--record` saves the numbers to
`history/metrics.csv` so later matches can be compared:
```
python tools/history.py magnet battery_path      # these numbers across every recorded log
python tools/vision_replay.py logs/<file> --max-heading-error 15 --max-correction 1.0
```

## Use it with AI

Start your agent inside this folder:
```
cd 9584-log-analyzer
gemini        # or: claude    or: codex
```
**The first time,** the agent asks whether to trust this folder. Say yes. An agent only works with
the files and commands in a folder you trust, and this repo is the folder it needs. Trust this
folder only, not your whole home folder. (Gemini: if you instead see *"Gemini CLI is not running in
a trusted directory"*, you ran a one-off `gemini -p ...` command before trusting the folder: run
plain `gemini` here once and say yes.)

Then ask. In **Gemini** and **Claude Code** the four standard tasks are commands:
- `/report logs/akit_..._q68.wpilog` full report, explained
- `/module logs/akit_..._q68.wpilog` which swerve module is misbehaving
- `/vision logs/akit_..._q68.wpilog` pose jumps and vision filter tuning
- `/compare logs/akit_..._q68.wpilog` what got worse since earlier matches

In **Codex**, ask for them in words: "do the report task on logs/akit_..._q68.wpilog". With any of
them you can also just ask: "The driver said the robot spun on its own near the end of q68. Why?"

The agent asks before running commands. Approve the `python tools/...` ones. (Gemini: you can choose
"always allow" for the session. Claude Code: the three analysis scripts are already allowed in this
folder once you have trusted it; anything else still asks.) Tell it what you physically saw on the
robot; that helps a lot.

The tasks are written once, in [AGENT_TASKS.md](AGENT_TASKS.md), for all three agents. To change
what `/report` does, edit that file, not the files in `.gemini/` or `.claude/`.

**When a problem is found and fixed,** have it add an entry to `history/findings.md`, and commit
`history/`. That is how the next student (and next season) learns from this one.

## New season

Robot code built from [9584-skeleton-robot](https://github.com/frc971/9584-skeleton-robot) already
has a robot file: `robot/2027.toml` (a copy of that repo's `docs/analyzer-robot.toml`). Keep the two
in step, and update CAN IDs, limits and camera names when the robot changes. The scripts pick
`robot/2027.toml` by themselves for logs from that code (they recognize the vision signals it
writes) and say so on the report's second line; `--robot` overrides it. The drivetrain,
power, connection, vision and camera checks carry over; mechanism checks
(`tools/checks/mechanisms.py`) need updating for the new game.

Skeleton-based robots also log what their vision filter decided about every estimate, so the vision
report shows what the robot actually rejected and why, instead of guessing.

## Changing a check

Each check is a small file in `tools/checks/`. After changing one, run the tests:
```
python -m unittest discover tests
```
`test_known_findings.py` makes sure the checks still catch the problems found at the 2026 mttd event
(needs those logs in `logs/`; tests for missing logs are skipped). `test_recorded_vision.py` builds
small synthetic logs and always runs.
