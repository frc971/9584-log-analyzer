"""Write small synthetic .wpilog files for tests, so checks can be tested without event logs.

Only what tests need: doubles, booleans, strings, int64, their arrays, and struct:Pose2d(/[]).
Format reference: https://github.com/wpilibsuite/allwpilib/blob/main/wpiutil/doc/datalog.adoc

Like AdvantageKit, call put() only when a value changes if you want a realistic log: AdvantageKit
never writes an unchanged value, and that is exactly the behavior several checks must cope with.
"""

import struct

_HEAD = 3 | (3 << 2) | (7 << 4)   # 4-byte entry id, 4-byte size, 8-byte timestamp


def _encode(type_name, value):
    if type_name == "double":
        return struct.pack("<d", value)
    if type_name == "int64":
        return struct.pack("<q", value)
    if type_name == "boolean":
        return bytes([1 if value else 0])
    if type_name == "string":
        return value.encode()
    if type_name == "double[]":
        return struct.pack("<%dd" % len(value), *value)
    if type_name == "boolean[]":
        return bytes(1 if v else 0 for v in value)
    if type_name == "string[]":
        out = struct.pack("<I", len(value))
        for s in value:
            b = s.encode()
            out += struct.pack("<I", len(b)) + b
        return out
    if type_name == "struct:Pose2d":
        return struct.pack("<3d", *value)
    if type_name == "struct:Pose2d[]":
        return b"".join(struct.pack("<3d", *p) for p in value)
    raise ValueError(type_name)


class Writer:
    def __init__(self):
        self._ids = {}
        self._records = []

    def _record(self, entry, t, payload):
        self._records.append(bytes([_HEAD]) + struct.pack("<IIQ", entry, len(payload), int(t * 1e6)) + payload)

    def put(self, name, type_name, t, value):
        """Write `value` for signal `name` at time t (seconds). Starts the entry on first use."""
        if name not in self._ids:
            entry = len(self._ids) + 1
            self._ids[name] = entry
            n, ty = name.encode(), type_name.encode()
            start = (b"\x00" + struct.pack("<I", entry) + struct.pack("<I", len(n)) + n
                     + struct.pack("<I", len(ty)) + ty + struct.pack("<I", 0))
            self._record(0, t, start)
        self._record(self._ids[name], t, _encode(type_name, value))

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"WPILOG" + struct.pack("<H", 0x0100) + struct.pack("<I", 0))
            for r in self._records:
                f.write(r)
