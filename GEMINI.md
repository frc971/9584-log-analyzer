# Team 9584 robot log analysis: instructions for the AI agent

You are helping FRC Team 9584 students figure out what their robot did, from AdvantageKit `.wpilog`
files. Most users are high-school students who are new to logs. Explain plainly, define terms the
first time you use them, and always say what to physically check on the robot.

## Ground rules

1. **Never guess a number.** Every number you state must come from running a script on the log.
   If you have not measured it, say so and measure it.
2. **Start with the report:** `python tools/match_report.py logs/<file>.wpilog --record`
   (use `python3` on Mac/Linux). It runs every check and saves the numbers to `history/metrics.csv`.
3. **Compare, don't stare.** The four swerve modules are told to do similar things, so the one that
   differs is the suspect. Also compare against earlier logs: `python tools/history.py <metric text>`.
4. **Read `history/findings.md` before diagnosing.** It records past problems, what fixed them, and
   what did not. Check whether this is a repeat.
5. **Separate evidence from guesses.** Say "the log shows X" for measured facts and "this suggests Y"
   for interpretation. Give the evidence that would confirm or rule out each guess.
6. **Hardware first, code second.** Most problems at events were wiring, batteries, magnets, and
   obstructions. Only propose code changes when the evidence points at code, and do not edit the
   robot code repo unless asked.
7. **When a problem is confirmed and fixed, append an entry to `history/findings.md`** (template at
   the top of that file). Ask the student what was physically found and changed.
8. Keep logs in `logs/` (not in git) and do not upload them anywhere else.

## Repo layout

| Path | What |
|---|---|
| `tools/match_report.py` | One-page report. `--record` saves metrics, `--only drivetrain,vision` runs some checks, `--json` for machine-readable output |
| `tools/history.py` | Compare metrics across logs from `history/metrics.csv` |
| `tools/vision_replay.py` | Test vision filter rules against a recorded log |
| `tools/wpilog.py` | Log reader (no dependencies). Use it for any custom digging, see below |
| `tools/checks/*.py` | The individual checks. Each has a docstring explaining the method |
| `robot/2026.toml` | The 2026 robot: signal names, CAN IDs, current limits, thresholds |
| `robot/2027.toml` | Robots built from `9584-skeleton-robot` (same file as that repo's `docs/analyzer-robot.toml`). Pass `--robot robot/2027.toml` |
| `history/metrics.csv` | One row of numbers per analyzed log |
| `history/findings.md` | Dated diagnoses, fixes, and outcomes |
| `tests/` | `python -m unittest discover tests` must pass after changing a check. `test_recorded_vision.py` builds synthetic logs (`wpilog_writer.py`) and always runs; `test_known_findings.py` needs the mttd logs in `logs/` |

The robot code for 2026 is the sibling repo `../9584-wcp-code-2026` (branch `competition`). Its
`docs/drivetrain-log-guide.md` explains every drivetrain signal for students. Next season's robot
starts from `../9584-skeleton-robot`, whose `docs/logging.md` lists every signal it writes and which
ones this repo depends on.

**Which robot file?** If the log has `/RealOutputs/Vision/RejectReasons` (check with
`log.names("RejectReasons")`), it came from skeleton-based code: use `robot/2027.toml`. Otherwise
use `robot/2026.toml` (the default).

## Custom digging

```python
import sys; sys.path.insert(0, "tools")
from wpilog import Log
log = Log("logs/akit_26-11-08_18-23-38_mttd_q68.wpilog")
log.names("Intake")                        # list signals
s = log.out("BatteryVoltage")              # /RealOutputs/BatteryVoltage
s.at(200.0); s.window(190, 210); s.changes()
log.series("/DriverStation/Enabled")       # non-RealOutputs names need the full path
```
Times are seconds since the robot program started (same as AdvantageScope). For enabled windows,
auto/teleop split and sampling helpers, build a `checks.common.Context(log, robot_config)`.

## The 2026 robot (details in robot/2026.toml)

- Swerve: CTRE Phoenix 6, Kraken X60 drive + steer, CANcoders, CANivore "Turret". Modules and CAN
  IDs: FrontLeft drive 1 / steer 2 / encoder 21; FrontRight 3 / 4 / 20; BackLeft 5 / 6 / 22;
  BackRight 7 / 8 / 23; Pigeon 26. Not Phoenix Pro licensed (steer uses RemoteCANcoder).
- Team swerve settings live in `SwerveConfigOverrides.java` (drive supply 35 A, slip/stator 70 A,
  steer 40 A stator / 20 A supply) and are verified while disabled (`Drive/Config/Verified`).
- Mechanisms on the roboRIO CAN bus: intake pivot + rollers, floor (indexer), feeder, three shooter
  flywheels, hood (servo), hanger (also extends the hopper).
- Driver controls: left trigger intake, left stick click outtake (0.75 s minimum burst), left bumper
  stow, right trigger aim-and-shoot, right bumper shoot with shot table, Start manual shoot, right
  stick click lock wheels, POV up/down climb.
- Teleop drive: field-centric; after 0.25 s with no rotation input it holds the current heading
  (`Drive/Input/State` = `DRIVING_WITH_LOCKED_HEADING`).
- Logs are written only to the roboRIO's USB stick. Pull them with AdvantageScope (File > Download
  Logs, 10.95.84.2) or `scp lvuser@10.95.84.2:/media/sda1/<file> logs/`.

## Diagnosis playbook (learned at mttd, Nov 2026)

| What the log shows | Likely cause | Check on the robot |
|---|---|---|
| One device `Connected` false for long stretches, others fine; maybe "failed config" at boot | That device's CAN connector/splice or power | Its CAN wires, power leads, breaker |
| One module's speed/target far below the others | Weak, binding, or dead drive motor | Spin the wheel by hand; check that motor |
| All drive motors on their supply limit most of the time, robot slow at full stick | Current limit too low | Raise the limit; watch battery minimum |
| Battery sags far more than current explains; resistance fit > 0.025 ohm and rising | Weak battery or loose/hot connection | Battery tester; main breaker, leads, lugs, connector |
| Battery near 6 V; BridgeBrownout/Undervoltage on all motors | Brownout | Battery choice, total current |
| CANcoder `MagnetHealth` orange/red, worse over sessions; wheel visibly off while `Steer/ErrorDegrees` is small | Magnet off-center/loose, encoder cap/mount loose | Tighten the mount, reseat/glue magnet, then recalibrate that module |
| Steer motors at their stator limit on carpet but ~2 A on blocks | Carpet scrub; limit too low | Raise steer stator limit (40 -> 60 A suggested); check rear tread |
| Unwanted rotation split both ways; rear modules lag most | Steering lag + contact, not one module | Steering limit, heading-hold tuning, driver correction |
| Unwanted rotation mostly ONE way | One module's offset, magnet, or weakness | Straighten wheels, read `MeasuredAngleDegrees` (should be ~0); recalibrate |
| Heading-hold turns the robot opposite its correction > 30% | Wheels not at target yet / being pushed | Steering current limit, heading PID |
| Comms drops every few seconds with low current and good battery | Bad ethernet cables (or laptop Wi-Fi when untethered) | Replace/reseat cables, tether in the pit |
| DS lost for ~20 s, robot code kept running, Limelight stayed connected | Radio link/power, often after impact | DS log viewer, radio power and cables |
| Limelight NT client disconnects while DS stays connected | Camera rebooting / its cable | Limelight power and ethernet |
| Auto disabled after a few seconds while `MatchTime` keeps counting | Disabled externally (A-stop, field, drive team) | Ask the drive team |
| Intake pivot stops short of target at the same angle every time, lift motor on its limit | Solid obstruction in the swing path | Lower the intake by hand, find what it hits |
| Roller stalled (< 2000 RPM) at its current limit | Fuel jammed at the roller (if the intake is high, fuel wedges under it) | Intake height; roller power |
| Many outtake presses while the rollers were stopped | Jams the roller can't feel (hopper entrance) | Watch video of where fuel sticks |
| Feeder sitting on its current limit while feeding | Feeder is the shooting bottleneck | Feeder limit/speed |
| ~10-13% of loops over 20 ms while disabled | Expected: the swerve config check reads one motor config every 10 loops | Nothing |

## Vision and localization

Signals: `Vision/Poses` (every MegaTag2 estimate received), `Vision/TagCounts`, `AvgTagDists`,
`StdDevsXY` (trust given to each), `Vision/GyroYawDegrees` (pose heading), fused pose `Drive/Pose`.
The robot rejects estimates whose heading is > 15 deg off the gyro (added 11-07).

Known patterns:
- **Bad solve signature:** the Limelight sometimes returns exactly (8.27, 4.03) facing 0 deg, the
  field center. It repeats for many loops. Before the heading filter it caused 5 m pose jumps.
- **Pose jumps with no vision estimate behind them** are odometry jumps: a drive motor reconnecting
  (q8: CAN 5 coming back online), wheel slip, or a pose reset at auto/teleop start.
- **Single-tag estimates** are trusted at ~5-10 cm, which is too much; several q8 jumps were
  single-tag estimates 2-5 m from the pose with a correct heading.
- Wrong pose -> wrong distance to the hub -> wrong shooter RPM/hood from the shot table; in auto, a
  wrong path. Correlate pose jumps with shots and auto paths.

Use `tools/vision_replay.py` to test rules (heading error, max correction, min tags, max distance,
field-center) and see which jumps they would have prevented and how much good data they discard.

### Logs from skeleton-based robot code (2027 on)

`9584-skeleton-robot` records everything the list above used to ask for, and the vision check and
`vision_replay.py` use it automatically when it is in the log:

- `Vision/Accepted`, `Vision/RejectReasons` (one per estimate, lined up with `Vision/Poses`): what
  the robot's filter ACTUALLY did. Reasons: `NO_TAGS`, `OFF_FIELD`, `HEADING_MISMATCH`, `SPINNING`,
  `TOO_FAR`, `AMBIGUOUS`, `LARGE_CORRECTION`. Do not guess acceptance from today's rules when these
  are present.
- `Vision/ResidualMeters`, `ResidualDegrees`: how far each estimate was from the pose it would correct.
- `Drive/OdometryPose` (wheels + gyro only) and `Drive/VisionCorrectionMeters`: separates "odometry
  drifted" from "vision moved the pose". The report splits pose jumps into vision and odometry jumps.
- `Vision/Cameras/<name>/Connected`, `Fps`, `CpuTempC`: the **cameras** check. "Connected" means the
  camera's frame counter was still going up, not just that it was on the network.
- `Vision/GyroDriftDegrees`: gyro vs the heading MegaTag1 solves from tags, while disabled.
  MegaTag2 trusts the gyro, so a drifted gyro skews every position and no filter catches it.
- `Vision/Rewind/SaveCount`: Limelight 4 Rewind video saves (every FMS match end, and the driver's
  Start button). The report gives the times; the video is on each camera (web UI, Rewind tab), so a
  student can WATCH what the camera saw at a pose jump.

If the report says **"The robot's filter ACCEPTED ... off the gyro"**, that is a robot-code bug, not
tuning: the filter has a rule against exactly that.

**Reading those arrays yourself:** AdvantageKit only writes a value when it changes, so two loops
with the same `["ACCEPTED"]` are ONE entry. Never count entries in `Vision/RejectReasons`; for each
time `Vision/Poses` changed, read the other arrays with `.at(t)` (as `checks/vision.py` does), or
use the running totals `Vision/ReasonCounts/<REASON>`. The same applies to any steady value (a
camera at a constant 60 fps is written once): sample with `.at(t)` on `ctx.enabled_grid()`.

## Pitfalls when reading these logs

- When a device stops responding, its last values are held in the log. Check `Connected` before
  trusting currents or speeds.
- `Drive/TargetStates` are stale while the drive command idles (the Idle request does not update
  them). Filter on `Drive/Input/State` != `IDLING`.
- `Drive/MeasuredSpeeds` (including omega) is computed from module states, not the gyro. Use the gyro
  heading (`Vision/GyroYawDegrees`) for how the robot really rotated.
- AdvantageKit only writes a value when it changes; a signal with one sample was constant.
- Faults like `StatorCurrentLimit` mean "working at its limit", not broken.
- The intake pivot has no homing: its zero is wherever it sat at power-on, so angles shift a few
  degrees between boots (`intake_boot_angle_deg`). Power on with the intake stowed.

## Answer format

1. One-paragraph summary: what happened and the most likely cause.
2. Evidence: the numbers, with signal names and times so a student can find them in AdvantageScope.
3. What to check on the robot, in order.
4. Optional code changes, clearly marked as suggestions.
5. Offer to add a `history/findings.md` entry once the cause is confirmed.
