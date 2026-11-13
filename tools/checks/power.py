"""Battery voltage, total current, brownouts, and the resistance between battery and robot."""

from .common import Result, pct, fmt


def _fit_resistance(log, times_ok):
    """Fit PDH voltage = V0 - R * current. A rising R across matches means a weak battery or a
    loose/hot connection (main breaker, battery leads, connector)."""
    cur = log.out("Power/TotalCurrent")
    volt = log.out("Power/Voltage")
    pts = []
    for t, i in zip(cur.times, cur.values):
        if i is None or i < 5 or not times_ok(t):
            continue
        v = volt.at(t)
        if v is not None:
            pts.append((i, v))
    if len(pts) < 50:
        return None, None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return None, None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return -slope, my - slope * mx


def check(ctx):
    r = Result("Power")
    log, th = ctx.log, ctx.th
    grid = ctx.enabled_grid()
    battery = log.out("BatteryVoltage")
    if not grid or not battery:
        r.lines.append("- No enabled time or no battery data.")
        return r
    volts = [battery.at(t) for t in grid]
    vmin = r.metric("battery_min_v", min(v for v in volts if v is not None))
    p10 = r.metric("battery_p10_v", pct(volts, 0.10))
    p50 = r.metric("battery_p50_v", pct(volts, 0.50))
    below7 = r.metric("battery_below_7v_s", sum(1 for v in volts if v is not None and v < 7.0) * ctx.STEP)
    total = log.out("Power/TotalCurrent")
    amps = [total.at(t) for t in grid if total]
    r.metric("pdh_current_p50_a", pct(amps, 0.5))
    r.metric("pdh_current_p90_a", pct(amps, 0.9))
    res, v0 = _fit_resistance(log, ctx.is_enabled)
    r.metric("battery_path_ohm", res)
    browned = any(log.series("/SystemStats/BrownedOut").values)
    r.metric("browned_out", int(browned))

    r.lines.append(f"- Battery while enabled: lowest {fmt(vmin, 2)} V, 10th percentile {fmt(p10, 2)} V, "
                   f"typical {fmt(p50, 2)} V; {fmt(below7)} s below 7 V")
    r.lines.append(f"- Total current: typical {fmt(pct(amps, 0.5), 0)} A, 90th percentile {fmt(pct(amps, 0.9), 0)} A")
    if res is not None:
        r.lines.append(f"- Battery-to-PDH resistance (fit of voltage vs current): {res:.3f} ohm "
                       f"(resting ~{v0:.2f} V). Healthy is about 0.012-0.020.")

    if browned:
        r.problem("The roboRIO browned out (all outputs cut).")
    if vmin < th.get("battery_warn_v", 7.0):
        r.problem(f"Battery fell to {vmin:.2f} V (brownout is ~{ctx.robot['power']['brownout_v']} V). "
                  f"Motors log BridgeBrownout/Undervoltage and lose power near this point.")
    if res is not None and res > th.get("battery_resistance_warn_ohm", 0.025):
        r.problem(f"Battery-path resistance {res:.3f} ohm is high. Test the battery's internal resistance; "
                  f"if it is fine, check the main breaker, battery leads, lugs and connector for looseness or heat.")
    if not r.findings:
        r.ok("Battery and current look healthy.")
    return r
