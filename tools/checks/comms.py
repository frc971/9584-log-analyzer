"""Driver Station connection drops, and devices dropping off the robot network (Limelight, dashboard)."""

from .common import Result, pct


def check(ctx):
    r = Result("Connection")
    log = ctx.log
    drops = log.series("/SystemStats/CommsDisableCount")
    count = 0
    drop_times = []
    if drops:
        count = (drops.values[-1] or 0) - (drops.values[0] or 0)
        drop_times = [t for t, _ in drops.changes()[1:]]
    r.metric("comms_disables", count)

    # Long losses: DS detached while the match was running.
    attached = log.series("/DriverStation/DSAttached")
    long_losses = []
    last_off = None
    for t, v in attached.changes():
        if not v:
            last_off = t
        elif last_off is not None:
            if any(a <= last_off <= b for a, b in ctx.enabled_windows) or ctx.is_enabled(last_off - 0.5):
                long_losses.append((last_off, t - last_off))
            last_off = None
    r.metric("ds_long_losses", len(long_losses))

    # Robot-network clients (Limelight, dashboards) disconnecting from the roboRIO.
    nt_drops = {}
    for name in log.names("/SystemStats/NTClients/"):
        if not name.endswith("/Connected"):
            continue
        client = name.split("/")[3].split("@")[0]
        offs = sum(1 for _, v in log.series(name).changes() if v is False)
        nt_drops[client] = nt_drops.get(client, 0) + offs
    for client, n in nt_drops.items():
        r.metric(f"nt_drops.{client}", n)

    r.lines.append(f"- Comms disables (robot lost the Driver Station): {count}")
    if len(drop_times) > 3:
        gaps = [b - a for a, b in zip(drop_times, drop_times[1:])]
        r.lines.append(f"- Typical time between drops: {pct(gaps, 0.5):.1f} s")
    for t, dur in long_losses:
        r.lines.append(f"- Driver Station detached at {t:.1f} s for {dur:.1f} s")
    if nt_drops:
        r.lines.append("- Network clients disconnecting from the roboRIO: " +
                       ", ".join(f"{c} {n}x" for c, n in sorted(nt_drops.items())))

    if long_losses:
        r.problem("Lost the Driver Station for seconds during the match. If the robot code kept running and the "
                  "battery was fine, suspect the radio: its power, the radio-to-roboRIO ethernet, or impact. "
                  "The DS log viewer shows whether the radio or only the roboRIO disappeared.")
    if count > 5:
        r.problem(f"{count} comms drops. At mttd, 86 regular drops (~6 s apart) were bad ethernet cables.")
    elif count > 0:
        r.watch(f"{count} brief comms drop(s).")
    for cam in ctx.robot.get("vision", {}).get("cameras", []):
        if nt_drops.get(cam, 0) > 1:  # one disconnect at shutdown is normal
            r.watch(f"{cam} dropped off the robot network {nt_drops[cam]} times: check the camera's power "
                    f"and ethernet, it may be rebooting.")
    if not r.findings:
        r.ok("No connection problems.")
    return r
