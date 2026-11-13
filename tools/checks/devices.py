"""Swerve CAN devices: connection, faults, config verification, CANcoder magnet health, boot errors."""

from .common import Result, seconds_where

# Faults that mean "working hard", not "broken". Reported elsewhere as time-on-limit.
_LIMIT_FAULTS = {"StatorCurrentLimit", "SupplyCurrentLimit"}


def check(ctx):
    r = Result("Swerve devices")
    log, dt = ctx.log, ctx.robot["drivetrain"]
    prefix = dt["module_prefix"]
    end = log.end_time
    rows = []
    for m in dt["modules"]:
        ids = dt["can_ids"][m]
        row = [m]
        for part, label in (("Drive", "drive"), ("Steer", "steer"), ("Encoder", "encoder")):
            conn = log.series(f"{prefix}{m}/{part}/Connected")
            # Seconds not responding while enabled (a dead motor while disabled matters less).
            dead = sum(seconds_where(conn, lambda v: v is False, a, b) for a, b in ctx.enabled_windows)
            flips = sum(1 for _, v in conn.changes() if v is False)
            r.metric(f"{m}.{label}.not_responding_s", dead)
            faults = set()
            for _, text in log.series(f"{prefix}{m}/{part}/Faults").changes():
                faults.update(f.strip() for f in (text or "").split(",") if f.strip())
            faults -= _LIMIT_FAULTS
            faults.discard("NotResponding")
            row.append(f"{dead:.1f} s off ({flips} drops)" if flips else "ok")
            row.append(", ".join(sorted(faults)) or "-")
            if dead > 1:
                r.problem(f"{m} {label} (CAN {ids[label]}) was not responding for {dead:.0f} s while enabled. "
                          f"Check its CAN connector/splice, power leads and breaker. "
                          f"(q8 at mttd: CAN 5 dead most of the match, robot drove on 3 motors.)")
            elif flips > 2:
                r.watch(f"{m} {label} (CAN {ids[label]}) dropped off the bus {flips} times.")
            if "BridgeBrownout" in faults or "Undervoltage" in faults:
                r.metric(f"{m}.{label}.brownout_fault", 1)
        # Magnet health: anything but green means the CANcoder reading is less trustworthy.
        mh = log.series(f"{prefix}{m}/Encoder/MagnetHealth")
        bad_en = sum(seconds_where(mh, lambda v: v != "Magnet_Green", a, b) for a, b in ctx.enabled_windows)
        bad_all = seconds_where(mh, lambda v: v != "Magnet_Green", mh.times[0] if mh else 0, end)
        red = any(v == "Magnet_Red" for v in mh.values)
        r.metric(f"{m}.magnet_not_green_s", bad_all)
        r.metric(f"{m}.magnet_not_green_enabled_s", bad_en)
        row.append(f"{bad_all:.1f} s ({bad_en:.1f} s enabled)" if bad_all > 0.05 else "green")
        rows.append(row)
        if red:
            r.problem(f"{m} CANcoder magnet went RED: the angle reading is invalid. Inspect the magnet and mount now.")
        elif bad_all > ctx.th.get("magnet_warn_s", 5):
            r.problem(f"{m} CANcoder magnet was marginal (orange) for {bad_all:.0f} s. Usually a magnet that has "
                      f"shifted off-center or a loose encoder mount/cap. The wheel can point wrong while the log "
                      f"says it is on target. Fix the mount, then recalibrate that module.")

    r.table(["Module", "Drive", "Drive faults", "Steer", "Steer faults", "Encoder", "Encoder faults", "Magnet"],
            rows)

    # Config verification (SwerveConfigOverrides): did every motor run the team's settings?
    verified = log.out("Drive/Config/Verified")
    mismatches = log.out("Drive/Config/Mismatches")
    timeouts = {}
    real = set()
    for _, text in mismatches.changes():
        for part in (text or "").split(";"):
            part = part.strip()
            if not part:
                continue
            if "could not read config" in part:
                key = part.split(":")[0]
                timeouts[key] = timeouts.get(key, 0) + 1
            else:
                real.add(part)
    r.metric("config_read_timeouts", sum(timeouts.values()))
    if verified:
        r.lines.append(f"- Swerve config check: {'passed' if any(verified.values) else 'NEVER passed'}"
                       + (f"; read timeouts: {', '.join(f'{k} x{v}' for k, v in timeouts.items())}" if timeouts else ""))
    if real:
        r.problem("Swerve motors not running the team's settings: " + "; ".join(sorted(real))
                  + ". Redeploy / power cycle before driving.")
    if verified and not any(verified.values):
        r.problem("The swerve config check never passed this session.")
    if sum(timeouts.values()) >= 3:
        r.watch("Repeated config read timeouts: " + ", ".join(timeouts) + ". Harmless alone, but if one "
                "CAN ID keeps showing up, check that device's CAN wiring.")

    # Errors printed at boot (failed configs, exceptions).
    boot = [(t, ln) for t, ln in ctx.console_lines(0, 30)
            if "failed config" in ln.lower() or ln.startswith("Error at") or "Exception" in ln]
    for t, ln in boot[:5]:
        r.lines.append(f"- Boot error at {t:.1f} s: `{ln[:140]}`")
    if any("failed config" in ln.lower() for _, ln in boot):
        r.problem("A motor failed to configure at boot (see boot errors). Its settings may not be applied.")
    if not r.findings:
        r.ok("All swerve devices connected, no faults, magnets green, config verified.")
    return r
