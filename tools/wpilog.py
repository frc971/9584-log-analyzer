"""Read WPILib .wpilog files (the format AdvantageKit writes) with no dependencies.

Usage:
    from wpilog import Log
    log = Log("logs/q68.wpilog")
    battery = log.series("/RealOutputs/BatteryVoltage")
    battery.at(200.0)            # value at t = 200 s (the last sample at or before it)
    battery.window(190, 210)     # [(t, value), ...] between two times
    log.names("Drive/Modules")   # every logged name containing that text

Times are seconds since the robot program started, the same timeline AdvantageScope shows.
Format reference: https://github.com/wpilibsuite/allwpilib/blob/main/wpiutil/doc/datalog.adoc
"""

import bisect
import struct

# Struct layouts for the WPILib types this team logs. Each is a list of doubles.
_STRUCT_DOUBLES = {
    "struct:Pose2d": 3,              # x, y, rotation (radians)
    "struct:Translation2d": 2,
    "struct:Rotation2d": 1,
    "struct:ChassisSpeeds": 3,       # vx, vy, omega (rad/s)
    "struct:SwerveModuleState": 2,   # speed (m/s), angle (radians)
    "struct:Pose3d": 7,              # x, y, z, quaternion w, x, y, z
    "struct:Rotation3d": 4,          # quaternion w, x, y, z
    "struct:Translation3d": 3,
}


def _decode(type_name, raw):
    if type_name == "double":
        return struct.unpack("<d", raw)[0] if len(raw) == 8 else None
    if type_name == "float":
        return struct.unpack("<f", raw)[0] if len(raw) == 4 else None
    if type_name == "int64":
        return struct.unpack("<q", raw)[0] if len(raw) == 8 else None
    if type_name == "boolean":
        return raw[0] != 0 if raw else None
    if type_name in ("string", "json"):
        return raw.decode(errors="replace")
    if type_name == "double[]":
        return list(struct.unpack_from("<%dd" % (len(raw) // 8), raw))
    if type_name == "float[]":
        return list(struct.unpack_from("<%df" % (len(raw) // 4), raw))
    if type_name == "int64[]":
        return list(struct.unpack_from("<%dq" % (len(raw) // 8), raw))
    if type_name == "boolean[]":
        return [b != 0 for b in raw]
    if type_name == "string[]":
        out, pos = [], 4
        for _ in range(struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else 0):
            n = struct.unpack_from("<I", raw, pos)[0]
            out.append(raw[pos + 4:pos + 4 + n].decode(errors="replace"))
            pos += 4 + n
        return out
    is_array = type_name.endswith("[]")
    base = type_name[:-2] if is_array else type_name
    if base in _STRUCT_DOUBLES:
        size = _STRUCT_DOUBLES[base]
        values = struct.unpack_from("<%dd" % (len(raw) // 8), raw)  # ignore a cut-off tail
        items = [tuple(values[i:i + size]) for i in range(0, len(values) - size + 1, size)]
        return items if is_array else (items[0] if items else None)
    return raw


class Series:
    """One logged signal: parallel lists of times (seconds) and decoded values."""

    def __init__(self, name, type_name, times, values):
        self.name = name
        self.type = type_name
        self.times = times
        self.values = values

    def __len__(self):
        return len(self.times)

    def __bool__(self):
        return bool(self.times)

    def at(self, t, default=None):
        """Value in effect at time t: the last sample at or before t."""
        i = bisect.bisect_right(self.times, t) - 1
        return self.values[i] if i >= 0 else default

    def window(self, t0, t1):
        """Samples with t0 <= t <= t1, as (t, value) pairs."""
        i = bisect.bisect_left(self.times, t0)
        j = bisect.bisect_right(self.times, t1)
        return list(zip(self.times[i:j], self.values[i:j]))

    def values_between(self, t0, t1):
        i = bisect.bisect_left(self.times, t0)
        j = bisect.bisect_right(self.times, t1)
        return self.values[i:j]

    def changes(self):
        """(t, value) for each sample whose value differs from the previous one."""
        out, last = [], object()
        for t, v in zip(self.times, self.values):
            if v != last:
                out.append((t, v))
                last = v
        return out


_EMPTY = Series("", "", [], [])


class Log:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            data = f.read()
        if data[:6] != b"WPILOG":
            raise ValueError(f"{path} is not a .wpilog file")
        header_len = struct.unpack_from("<I", data, 8)[0]
        pos = 12 + header_len
        entries = {}   # entry id -> (name, type)
        raw = {}       # name -> ([times], [payloads])
        n = len(data)
        while pos < n:
            head = data[pos]
            pos += 1
            id_len = (head & 0x3) + 1
            size_len = ((head >> 2) & 0x3) + 1
            ts_len = ((head >> 4) & 0x7) + 1
            if pos + id_len + size_len + ts_len > n:
                break  # file cut off mid-record (robot powered off while writing)
            entry = int.from_bytes(data[pos:pos + id_len], "little"); pos += id_len
            size = int.from_bytes(data[pos:pos + size_len], "little"); pos += size_len
            ts = int.from_bytes(data[pos:pos + ts_len], "little"); pos += ts_len
            payload = data[pos:pos + size]
            pos += size
            if entry == 0:
                # Control record. Type 0 starts a new entry: id, name, type, metadata.
                if payload and payload[0] == 0:
                    new_id = struct.unpack_from("<I", payload, 1)[0]
                    p = 5
                    name_len = struct.unpack_from("<I", payload, p)[0]; p += 4
                    name = payload[p:p + name_len].decode(errors="replace"); p += name_len
                    type_len = struct.unpack_from("<I", payload, p)[0]; p += 4
                    type_name = payload[p:p + type_len].decode(errors="replace")
                    entries[new_id] = (name, type_name)
                    raw.setdefault(name, ([], []))
                continue
            if entry in entries:
                times, payloads = raw[entries[entry][0]]
                times.append(ts / 1e6)
                payloads.append(payload)
        self._types = {name: type_name for name, type_name in entries.values()}
        self._raw = raw
        self._cache = {}
        self.end_time = max((t[-1] for t, _ in raw.values() if t), default=0.0)

    def names(self, contains=""):
        return sorted(n for n in self._types if contains in n)

    def has(self, name):
        return bool(self._raw.get(name, ([], []))[0])

    def series(self, name):
        """The decoded signal, or an empty Series if the log does not have it."""
        if name not in self._cache:
            if name not in self._raw:
                return _EMPTY
            type_name = self._types[name]
            times, payloads = self._raw[name]
            self._cache[name] = Series(name, type_name, times, [_decode(type_name, p) for p in payloads])
        return self._cache[name]

    def out(self, name):
        """Shortcut for robot-code outputs: log.out('BatteryVoltage') reads /RealOutputs/BatteryVoltage."""
        return self.series("/RealOutputs/" + name)
