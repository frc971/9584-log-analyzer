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
    devices = []
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
            onsets, prev = [], None
            for t, v in conn.changes():
                if v is False and prev is True:
                    onsets.append(t)
                prev = v
            devices.append({"module": m, "label": label, "can": ids[label], "dead": dead, "flips": flips,
                            "onsets": onsets})
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

    _connection_findings(r, devices, dt["modules"])

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


# Two disconnects within this many seconds count as the same moment (a few robot loops).
_SAME_MOMENT_S = 0.25


def _together(a, b):
    """True if a and b lost connection at the same moments and stayed off for about as long.

    Most of the drops of the one with fewer drops must have a drop of the other within _SAME_MOMENT_S
    (devices on one break can log one drop more or less). The similar-time-off rule keeps out a device that
    only blipped at the same instant and came straight back (BackLeft in mttd p8)."""
    def matched(x, y):
        return sum(any(abs(t - u) <= _SAME_MOMENT_S for u in y) for t in x)
    if not a["onsets"] or not b["onsets"]:
        return False
    short, long_ = sorted((a["onsets"], b["onsets"]), key=len)
    if matched(short, long_) < 0.8 * len(short) or matched(long_, short) < 0.5 * len(long_):
        return False
    return abs(a["dead"] - b["dead"]) <= max(2.0, 0.3 * max(a["dead"], b["dead"]))


def _connection_findings(r, devices, modules):
    """One finding per group of devices that dropped together, one per device otherwise.

    Devices that lose connection at the same instant share something: a CAN splice or connector, the
    CANivore and its USB cable, or their power feed. Reporting each one separately sends a student to
    check nine connectors that are fine (mttd p8: FrontLeft, FrontRight and BackRight, 9 devices,
    off together for 129 s while BackLeft stayed up)."""
    dead = [d for d in devices if d["dead"] > 1]
    # Join a device to every group it matches any member of (and merge those groups).
    groups = []
    for d in dead:
        hits = [g for g in groups if any(_together(x, d) for x in g)]
        merged = [d] + [x for g in hits for x in g]
        groups = [g for g in groups if g not in hits] + [merged]
    groups.sort(key=lambda g: min(devices.index(x) for x in g))
    for g in groups:
        g.sort(key=devices.index)
    for g in groups:
        if len(g) >= 3:
            mods = [m for m in modules if any(d["module"] == m for d in g)]
            up = [m for m in modules if m not in mods]
            cans = ", ".join(str(d["can"]) for d in g)
            first = min(t for d in g for t in d["onsets"])
            worst = max(d["dead"] for d in g)
            r.metric("group_drop_devices", max(r.metrics.get("group_drop_devices", 0), len(g)))
            if not up:
                where = ("Every swerve device dropped at once: suspect the CANivore, its USB cable to the "
                         "roboRIO, or its power.")
            else:
                where = (f"{', '.join(up)} stayed connected, so look for a connection the others share and "
                         f"{'it does' if len(up) == 1 else 'they do'} not: a CAN splice or connector between "
                         f"modules, or the power feed to those modules.")
            r.problem(f"{len(g)} devices on {', '.join(mods)} (CAN {cans}) lost connection at the same moments "
                      f"(first at {first:.1f} s) and were off up to {worst:.0f} s while enabled. Devices that drop "
                      f"together share wiring: do not check them one by one. {where} (mttd: FrontLeft, "
                      f"FrontRight and BackRight dropped together in five sessions up to Nov 7 afternoon, "
                      f"129 s in p8.)")
        else:
            for d in g:
                r.problem(f"{d['module']} {d['label']} (CAN {d['can']}) was not responding for {d['dead']:.0f} s "
                          f"while enabled. Check its CAN connector/splice, power leads and breaker. "
                          f"(q8 at mttd: CAN 5 dead most of the match, robot drove on 3 motors.)")
    for d in devices:
        if d["dead"] <= 1 and d["flips"] > 2:
            r.watch(f"{d['module']} {d['label']} (CAN {d['can']}) dropped off the bus {d['flips']} times.")
