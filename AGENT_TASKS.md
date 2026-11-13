# Agent tasks

The four standard jobs an AI agent does in this repo. This file is the ONE copy of them: Gemini's
`/report` (in `.gemini/commands/`) and Claude Code's `/report` (in `.claude/commands/`) both just
say "do the report task in AGENT_TASKS.md", and with Codex a student asks for it in words ("do the
report task on logs/<file>"). Change a task here, never in the command files.

Every task follows [GEMINI.md](GEMINI.md) (the ground rules, the playbook and the answer format),
whichever agent is running it. `<log>` below is the log file the student gave.

The scripts pick the robot file themselves (2027 for logs from skeleton-based robot code, 2026
otherwise) and the report's second line says which one they used; pass `--robot` only to override.
Use `python` instead of `python3` if `python3` is not found (Windows).

## report: full report on a log, explained

1. Run `python3 tools/match_report.py <log> --record`.
2. Read `history/findings.md` and check whether any problem is a repeat.
3. For each PROBLEM and WATCH item, compare with earlier logs using `python3 tools/history.py <metric>`.
4. Answer in the GEMINI.md answer format: summary, evidence (signal names + times), what to check on
   the robot in order, optional code suggestions. Keep it short and plain for a student.

## module: which swerve module (if any) is misbehaving, and why

1. Run `python3 tools/match_report.py <log> --only devices,drivetrain,power`.
2. Compare the four modules side by side (speed/target, drive and steer current, steering error,
   time on current limits, magnet health, connection drops). The one that differs is the suspect;
   if all four struggle, look at limits, battery, or the floor.
3. For unwanted rotation, check whether drift is one-directional (single module) or both ways.
4. Use `tools/wpilog.py` for any extra measurement you need. Tell the student exactly what to check
   on the robot and in AdvantageScope (signal names + times).

## vision: bad estimates, pose jumps, and testing filter rules

1. Run `python3 tools/match_report.py <log> --only timeline,vision,cameras,comms`.
2. Run `python3 tools/vision_replay.py <log> --max-heading-error 15`, then try stricter rules
   (e.g. `--max-correction 1.0`, `--min-tags 2`) and compare how many pose jumps each would prevent
   versus how much agreeing data it throws away. If the log records the robot's own decisions, the
   replay also shows where each rule disagrees with what the robot actually did: use that, not a
   guess, when recommending a change to the robot's VisionFilter.
3. Explain where the pose jumps came from (vision vs odometry), whether they hit auto or shooting,
   whether any camera stopped sending frames, and which filter rule you would recommend, with the
   numbers. If Limelight Rewind video was saved, say which match time to scrub to.

## compare: what got worse (or better) since earlier logs

1. Make sure the log is recorded: `python3 tools/match_report.py <log> --record --json`.
2. Use `python3 tools/history.py` with metric names (battery_path, magnet_not_green, steer_limit,
   comms_disables, not_responding, pose_jumps, roller_stalled, intake_short, heading_held) to find
   metrics that changed noticeably versus earlier logs.
3. Report trends: what got worse, what got better, and what that suggests. Show the numbers.
