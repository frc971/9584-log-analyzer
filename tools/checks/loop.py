"""Robot loop timing: overruns slow every control loop and delay driver input."""

from .common import Result, pct


def check(ctx):
    r = Result("Loop timing")
    log, th = ctx.log, ctx.th
    cyc = log.out("LoggedRobot/FullCycleMS")
    if not cyc:
        return r
    limit = th.get("loop_overrun_ms", 20)
    for label, windows in (("enabled", ctx.enabled_windows), ("disabled", None)):
        if windows is None:
            vals = [v for t, v in zip(cyc.times, cyc.values) if v is not None and not ctx.is_enabled(t)]
        else:
            vals = [v for a, b in windows for v in cyc.values_between(a, b) if v is not None]
        if not vals:
            continue
        over = 100 * sum(1 for v in vals if v > limit) / len(vals)
        r.metric(f"loop_{label}_overrun_pct", over)
        r.metric(f"loop_{label}_p99_ms", pct(vals, 0.99))
        r.lines.append(f"- {label.capitalize()}: typical {pct(vals, .5):.1f} ms, 99th percentile {pct(vals, .99):.1f} ms, "
                       f"{over:.1f}% of loops over {limit} ms")
        # While disabled, the swerve config check reads one motor's config every 10 loops and each
        # read blocks for a few ms, so ~10-13% disabled overruns is expected with today's robot code.
        bad = 20 if label == "disabled" else 10
        if label == "disabled" and over <= bad:
            r.lines.append("  (about 10-13% is expected while disabled: the swerve config check runs every 10th loop)")
        if over > bad:
            r.problem(f"{over:.0f}% of {label} loops overran {limit} ms. Find the slow part in the console "
                      f"'Tracer' lines; at mttd it was a config read blocking on a dead CAN device.")
        elif label == "enabled" and over > 3:
            r.watch(f"{over:.1f}% of enabled loops overran.")
    return r
