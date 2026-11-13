from . import cameras, comms, devices, drivetrain, loop, mechanisms, power, timeline, vision

# Report order. Each entry is (key, function); the key is used by --only.
ALL = [
    ("timeline", timeline.check),
    ("power", power.check),
    ("comms", comms.check),
    ("devices", devices.check),
    ("drivetrain", drivetrain.check),
    ("intake", mechanisms.check_intake),
    ("shooting", mechanisms.check_shooting),
    ("vision", vision.check),
    ("cameras", cameras.check),
    ("loop", loop.check),
]
