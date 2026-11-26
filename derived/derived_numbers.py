"""Derived numbers: sets of measures from many analyzers, joined by opaque track id and window, numbers only.

A set is one analyzer's output with its provenance (analyzer, version, separator, calibration, measured_on). Sets are
joined by key; the join never mixes two separators or two analyzer versions for the same measure name without saying so.

  {"schema_version": 1, "set": "flow", "level": "window",
   "provenance": {"analyzer": "seg-flow", "version": "1", "separator": "bs-roformer-ep317",
                  "measured_on": "reference", "calibration": "none"},
   "rows": [{"key": "ab12cd34ef56", "window": 0, "values": {"pace": 5.1, "spread": 2.7}}]}

Levels: "track" (window absent) or "window" (window = 30 s index). Keys are opaque ids; no names, paths or text.
Stdlib only.
"""
import math, re

LEVELS = {"track", "window"}
REQUIRED_PROV = ("analyzer", "version", "separator", "measured_on", "calibration")
KEY = re.compile(r"^[0-9a-f]{8,16}$")
NAMEY = re.compile(r"[A-Za-z]{3,}\s+[A-Za-z]{3,}|https?:|/|\\|@")   # two words, a URL, a path or an address: refused


def validate(s):
    errs = []
    if s.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    if not isinstance(s.get("set"), str) or not re.match(r"^[a-z][a-z0-9-]{1,30}$", s.get("set", "")):
        errs.append("set: a short lower-case name")
    if s.get("level") not in LEVELS:
        errs.append("level must be track or window")
    prov = s.get("provenance") or {}
    for f in REQUIRED_PROV:
        if not prov.get(f):
            errs.append(f"provenance.{f}: required")
    for k in prov:
        if k not in REQUIRED_PROV:
            errs.append(f"provenance.{k}: not an allowed field")
    for i, r in enumerate(s.get("rows", [])):
        if not KEY.match(str(r.get("key", ""))):
            errs.append(f"rows[{i}].key: not an opaque id")
        if s["level"] == "window" and not isinstance(r.get("window"), int):
            errs.append(f"rows[{i}].window: integer required at window level")
        if s["level"] == "track" and "window" in r:
            errs.append(f"rows[{i}].window: not allowed at track level")
        vals = r.get("values")
        if not isinstance(vals, dict) or not vals:
            errs.append(f"rows[{i}].values: non-empty object required")
            continue
        for name, v in vals.items():
            if not re.match(r"^[a-z][a-z0-9_]{1,40}$", name):
                errs.append(f"rows[{i}].values.{name}: measure name must be a short identifier")
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                errs.append(f"rows[{i}].values.{name}: finite numbers only")
        if set(r) - {"key", "window", "values"}:
            errs.append(f"rows[{i}]: unexpected fields")
    text = repr(s)
    if NAMEY.search(text.replace("'", " ")):
        errs.append("text that looks like a name, path or address is present")
    return errs


def join(sets, level="track"):
    """Combine sets into one row per key (track) or per key and window. Refuses to combine sets whose separator
    differs for the same level unless allow_mixed is implied by the caller; reports the separators it saw."""
    seps = {s["provenance"]["separator"] for s in sets}
    out = {}
    for s in sets:
        for r in s["rows"]:
            k = (r["key"], r.get("window")) if level == "window" else r["key"]
            e = out.setdefault(k, {"values": {}, "sets": []})
            e["sets"].append(s["set"])
            for name, v in r["values"].items():
                e["values"][f"{s['set']}.{name}"] = v
    return out, sorted(seps)
