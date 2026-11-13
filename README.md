# 9584 Log Analyzer

Tools for figuring out what the robot did from its logs: why it was slow, why it drifted, why the
intake jammed, why it lost connection. Works with or without AI.

- **Without AI:** run one script and get a one-page report.
- **With AI:** run Gemini CLI in this folder and ask questions in plain English. It reads
  [GEMINI.md](GEMINI.md), runs the scripts, compares with past matches, and explains.

## One-time setup

1. **Python 3.11 or newer.** Check with `python --version` (Mac/Linux: `python3 --version`).
   Install from [python.org](https://www.python.org/downloads/) if needed. No extra packages needed.
2. **Get this repo** (clone it, or download and unzip).
3. **For the AI part, Gemini CLI** (needs [Node.js](https://nodejs.org/) 20+):
   ```
   npm install -g @google/gemini-cli
   ```
4. **The team's Gemini API key**, from a mentor. Set it as an environment variable, never in a file
   in this repo:
   - Windows (PowerShell, once): `setx GEMINI_API_KEY "the-key"` then open a new terminal
   - Mac/Linux: add `export GEMINI_API_KEY="the-key"` to `~/.zshrc` or `~/.bashrc`

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

```
cd 9584-log-analyzer
gemini
```
Then ask, for example:
- `/report logs/akit_..._q68.wpilog` full report, explained
- `/module logs/akit_..._q68.wpilog` which swerve module is misbehaving
- `/vision logs/akit_..._q68.wpilog` pose jumps and vision filter tuning
- `/compare logs/akit_..._q68.wpilog` what got worse since earlier matches
- or just: "The driver said the robot spun on its own near the end of q68. Why?"

Gemini asks before running commands. Approve the `python tools/...` ones (you can choose "always
allow" for the session). Tell it what you physically saw on the robot; that helps a lot.

**When a problem is found and fixed,** have it add an entry to `history/findings.md`, and commit
`history/`. That is how the next student (and next season) learns from this one.

## New season

Robot code built from [9584-skeleton-robot](https://github.com/frc971/9584-skeleton-robot) already
has a robot file: `robot/2027.toml` (a copy of that repo's `docs/analyzer-robot.toml`). Keep the two
in step, update CAN IDs, limits and camera names when the robot changes, and pass
`--robot robot/2027.toml` (or change `DEFAULT_ROBOT` in `tools/match_report.py`). The drivetrain,
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
