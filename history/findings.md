# Findings log

What we saw, what we changed, and whether it worked. Newest first. The agent reads this before
diagnosing, so write entries a future student can understand without having been there.

Template:

```
## YYYY-MM-DD <event> <match/session>: <short title>
- Saw: <symptom + key numbers + signal names>
- Cause: <confirmed / suspected>
- Changed: <hardware or code change, commit if code>
- Result: <what the next log showed>
```

## 2026-11-08 mttd q68: rotation drift while playing defense
- Saw: unwanted rotation split ~50/50 CW/CCW; module furthest off target at drift onset was usually
  BackRight (40%), then BackLeft; 2/3 of translation time pinned/pushing; heading-hold 35% wrong way.
- Cause: contact + rear steering lag + weak heading-hold, not a single module.
- Changed: nothing (season over). Suggested: steer stator limit 40 -> 60 A; retune heading-hold.
- Result: open.

## 2026-11-08 mttd practice: 86 comms drops; Limelight reboots
- Saw: `CommsDisableCount` 86, ~6 s apart, battery ~11.6 V and ~20 A at each drop; Limelight NT
  client disconnected twice (~9 s) while the DS stayed connected.
- Cause: bad ethernet cables (confirmed by the team).
- Changed: cables replaced.
- Result: q68 had 1 brief drop.

## 2026-11-08 mttd q51 and blocks test: FrontLeft CANcoder magnet
- Saw: FrontLeft `Encoder/MagnetHealth` orange 0 s (morning) -> 16 s (blocks) -> 111 s (q51),
  mostly while disabled. On blocks FrontLeft tracked its target best of all modules (0.4 deg) yet
  the wheel was visibly off: the sensor, not the motor.
- Cause: loose encoder cap/mount.
- Changed: tightened the encoder cap screw; drivetrain felt solid again.
- Result: q68 still orange 17% of disabled time, 3% enabled. Magnet may still be off-center;
  hand-rotate check and recalibration recommended.

## 2026-11-08 mttd q51: intake jams, outtake taps too short
- Saw: 15 outtakes, typical 0.3 s; roller only reached ~1400 RPM backward; 10 of 15 while rollers
  were stopped (jam not at the roller).
- Changed: outtake minimum 0.75 s burst; rollers 98%, 50 A stator / 40 A supply (robot code a735091).
- Result: practice 11-08: outtakes >= 0.78 s reaching ~6000 RPM reverse; rollers free ~6000 RPM.

## 2026-11-07 mttd q38 / practice: intake blocked short of target
- Saw: q38 pivot stuck 29-64 deg for 28 s, then 94-99 deg (target 108) with the lift motor on its
  35 A limit; practice stopped at 81.5 deg every time; rollers stalled 74% of intake time.
  Pit test earlier reached 107.7 deg freely.
- Cause: physical obstruction (unidentified; not the extended hopper, since q51 deployed fully with
  the hopper extended).
- Changed: nothing deliberate. Result: q51 deployed to 107.7 deg every time.

## 2026-11-07 mttd q38: 17 s connection loss at end of match
- Saw: DS lost at 17 s left for ~20 s; robot code kept running; battery ~9 V; Limelight stayed
  connected to the roboRIO; robot was pushing (100-120 A) at the time.
- Cause: suspected radio after impact (power/ethernet). Later cables found bad (see 11-08 entry).

## 2026-11-07 mttd q19 / practice: battery sag to 6.05 V
- Saw: voltage collapsed late in teleop at constant current; resistance fit rose 0.014 -> 0.035 ohm
  across sessions; BridgeBrownout/Undervoltage on all swerve motors.
- Cause: weak battery and/or battery-path connection (not confirmed which).
- Result: q51/q68 with better batteries stayed above 7.4 V.

## 2026-11-07 mttd q8: slow robot, CAN warnings
- Saw: BackLeft drive (CAN 5) `TxFailed` config at boot and not responding most of the match
  (robot drove on 3 motors); other drive motors on their 20 A supply limit 77% of teleop; full stick
  gave 1.4 m/s typical; Limelight bad solve (field center, 0 deg) caused a 5 m pose jump in auto.
- Changed: CAN 5 connection repaired by the team before q19 (it stayed connected from then on); drive supply 20 -> 35 A; slip current 70 A; vision heading filter
  (15 deg); config check skips devices that are off the bus (it was stalling loops 50 ms).
- Result: q19 typical speed 2.2 m/s (from 1.4); all devices connected; but battery sag (see q19).
