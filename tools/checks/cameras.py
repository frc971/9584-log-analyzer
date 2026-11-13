"""Camera health: did each camera keep sending frames, how fast, and how hot.

Reads Vision/Cameras/<name>/{Connected, Fps, CpuTempC} for each camera in [vision] cameras. The
skeleton robot (9584-skeleton-robot) logs these; the 2026 robot did not, so this check is silent on
2026 logs. "Connected" means the camera's heartbeat counter was still going up, i.e. it was really
processing frames, not just plugged in.

A camera that is not connected while enabled is reported. Frame rate and temperature are only
reported, not judged, unless the robot file sets camera_fps_warn / camera_temp_warn_c in
[thresholds]: there are no measured limits for them yet.
"""

from .common import Result, pct, seconds_where

PREFIX = "Vision/Cameras/"


def check(ctx):
    r = Result("Cameras")
    log, th = ctx.log, ctx.th
    cameras = ctx.robot.get("vision", {}).get("cameras", [])
    present = [c for c in cameras if log.out(PREFIX + c + "/Connected")]
    if not present:
        return r

    rows = []
    for cam in cameras:
        conn = log.out(PREFIX + cam + "/Connected")
        if not conn:
            rows.append([cam, "not logged", "-", "-", "-"])
            continue
        off = sum(seconds_where(conn, lambda v: v is False, a, b) for a, b in ctx.enabled_windows)
        ever_on = any(v for v in conn.values)
        # Sampled on the robot-loop grid: AdvantageKit writes a value only when it changes, so a
        # steady frame rate has almost no samples inside the enabled window.
        fps_series = log.out(PREFIX + cam + "/Fps")
        fps = [v for v in (fps_series.at(t) for t in ctx.enabled_grid())
               if v is not None and v == v]  # v == v drops NaN (sent while disconnected)
        temps = [v for v in log.out(PREFIX + cam + "/CpuTempC").values if v is not None and v == v]
        r.metric(f"{cam}.not_connected_enabled_s", off)
        r.metric(f"{cam}.fps_p10", pct(fps, 0.1))
        r.metric(f"{cam}.fps_p50", pct(fps, 0.5))
        r.metric(f"{cam}.cpu_temp_max_c", max(temps) if temps else None)
        rows.append([cam, f"{off:.1f} s" if ever_on else "never", pct(fps, 0.5), pct(fps, 0.1),
                     max(temps) if temps else None])

        enabled_s = sum(b - a for a, b in ctx.enabled_windows)
        if not ever_on:
            r.problem(f"{cam} never sent a frame this session. It is listed in the robot code but not running: "
                      f"check its power and ethernet, or remove it from the robot code if the robot does not have it.")
        elif off > th.get("camera_disconnect_s", 1.0) and enabled_s > 0:
            r.problem(f"{cam} stopped sending frames for {off:.1f} s while enabled. Check its power and ethernet; "
                      f"if the comms check also shows it dropping off the network, it is rebooting.")
        fps_warn = th.get("camera_fps_warn")
        if fps_warn is not None and fps and pct(fps, 0.1) < fps_warn:
            r.watch(f"{cam} ran below {fps_warn} fps for over 10% of enabled time (slowest 10%: {pct(fps, .1):.0f} fps).")
        temp_warn = th.get("camera_temp_warn_c")
        if temp_warn is not None and temps and max(temps) > temp_warn:
            r.watch(f"{cam} CPU reached {max(temps):.0f} C (warning set at {temp_warn} C).")

    r.table(["Camera", "not sending while enabled", "fps typical", "fps slowest 10%", "CPU max C"], rows)
    if not r.findings:
        r.ok("All cameras kept sending frames.")
    return r
