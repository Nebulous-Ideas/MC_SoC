#!/usr/bin/env python3
"""Feature tables: the one shape every analyzer produces for the Measure stage. Stdlib only.

A table is a list of measured numbers, one row per track, with an opaque row id and an opaque group id
(the artist, hashed) so a card can require several distinct artists without ever carrying a name.

  {"schema_version": 1, "analyzer": "flow-tsv", "analyzer_version": "1",
   "features": [{"name": "syl_per_voiced_s", "unit": "syllables/s", "description": "..."}],
   "rows": [{"id": "ab12cd34ef56", "group": "9f8e7d6c", "values": {"syl_per_voiced_s": 4.77}}]}

Every table also carries a `provenance` block, so a known bias travels with the numbers (decision 15):

  "provenance": {"method": "flow-profile-tsv", "measured_on": "reference", "n_tracks": 42,
                 "calibration": {"status": "own-tracks", "n_tracks": 7,
                                 "rank_agreement": {"end_rhyme_share": 0.8}, "bias": {"end_rhyme_share": "low"}}}

  method        a short identifier (letters, digits, . _ + -), never a sentence
  measured_on   own | reference | mixed | unspecified
  n_tracks      equals the number of rows
  unit          optional: what one row is, track (the default when absent) | voice (one voice inside a track; a track may give several rows)
  calibration   status none | own-tracks; n_tracks it was checked on; per-feature rank agreement with the truth
                (-1 to 1) and bias (low | high | none | unknown), only for features the table declares
Only enums, identifiers and numbers: free text is refused, so provenance cannot carry a lyric or a name.

Guardrails (enforced by validate()):
  - numbers only: every value is a finite number, never a list, string or vector, so a voice embedding
    cannot be stored in a table (no speaker/voice embeddings, ever)
  - feature names that say embedding, vector, speaker, voiceprint or xvector are refused
  - no names: ids and groups are short hashes; a table never holds an artist or track title
Tables are local working files (tables/ is gitignored). Hashes of known names can be guessed, so tables
are not for publishing; cards built from them carry no ids at all.
"""
import argparse, hashlib, json, math, re, sys, unicodedata
from pathlib import Path

REFUSED_NAME = re.compile(r"embed|vector|speaker|voiceprint|xvector|ivector|d-?vector", re.I)
FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
METHOD = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")
MEASURED_ON = ("own", "reference", "mixed", "unspecified")
UNIT = ("track", "voice")
CAL_STATUS = ("none", "own-tracks")
BIAS = ("low", "high", "none", "unknown")


def norm(s):
    """Lower-case, letters and digits of any script, single spaces: 'The  Tune!' and 'the tune' match.
    Unicode-aware (NFKC, so full-width forms fold): names outside Latin letters used to normalise to nothing and
    every one of them got the same id. Pure-ASCII input normalises exactly as before, so existing ids do not change."""
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(s)).lower()).strip()


def opaque(*parts, n=12):
    """Short stable hash of normalised parts. Not reversible by reading, guessable by dictionary: local only."""
    h = hashlib.sha256("\x1f".join(norm(p) for p in parts).encode()).hexdigest()
    return h[:n]


INSTRUMENT_NAME = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
INSTRUMENT_VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,40}$")


def check_instruments(v, label="instruments"):
    """Optional record of which instrument versions made the numbers: short names to short version labels, never a path or a host."""
    if not isinstance(v, dict) or not 1 <= len(v) <= 8:
        return [f"{label} must be an object of 1 to 8 entries (instrument name -> version label)"]
    return [f"{label}.{k}: names are lower-case identifiers and versions are 1 to 40 of letters, digits and . _ + -"
            for k, x in v.items() if not (isinstance(k, str) and INSTRUMENT_NAME.match(k) and isinstance(x, str) and INSTRUMENT_VERSION.match(x))]


def provenance(method, measured_on, n_tracks, calibration=None, instruments=None, unit=None):
    """Build a provenance block. calibration defaults to "not calibrated". instruments (optional): {name: version label} of the models and tools used.
    unit (optional): what one row is, when it is not a track."""
    p = {"method": method, "measured_on": measured_on, "n_tracks": n_tracks,
         "calibration": calibration or {"status": "none", "n_tracks": 0}}
    if instruments is not None:
        p["instruments"] = instruments
    if unit is not None:
        p["unit"] = unit
    return p


def make_table(analyzer, version, features, rows, prov=None):
    t = {"schema_version": 1, "analyzer": analyzer, "analyzer_version": str(version),
         "features": features, "rows": rows}
    if prov is not None:
        t["provenance"] = prov
    return t


def _check_provenance(p, names, n_rows):
    if not isinstance(p, dict):
        return ["provenance is required (an object; see features.provenance())"]
    errs = []
    extra = set(p) - {"method", "measured_on", "n_tracks", "calibration", "instruments", "unit"}
    if extra:
        errs.append(f"provenance: unknown keys {sorted(extra)}")
    if not isinstance(p.get("method"), str) or not METHOD.match(p.get("method") or ""):
        errs.append(f"provenance.method must match {METHOD.pattern} (an identifier, not a sentence)")
    if p.get("measured_on") not in MEASURED_ON:
        errs.append(f"provenance.measured_on must be one of {list(MEASURED_ON)}")
    if "instruments" in p:
        errs += check_instruments(p["instruments"], "provenance.instruments")
    if "unit" in p and p["unit"] not in UNIT:
        errs.append(f"provenance.unit must be one of {list(UNIT)}")
    n = p.get("n_tracks")
    if isinstance(n, bool) or not isinstance(n, int) or n != n_rows:
        errs.append(f"provenance.n_tracks must be the number of rows ({n_rows})")
    c = p.get("calibration")
    if not isinstance(c, dict):
        return errs + ["provenance.calibration is required (an object)"]
    extra = set(c) - {"status", "n_tracks", "rank_agreement", "bias"}
    if extra:
        errs.append(f"provenance.calibration: unknown keys {sorted(extra)}")
    if c.get("status") not in CAL_STATUS:
        errs.append(f"provenance.calibration.status must be one of {list(CAL_STATUS)}")
    cn = c.get("n_tracks")
    if isinstance(cn, bool) or not isinstance(cn, int) or cn < 0:
        errs.append("provenance.calibration.n_tracks must be a whole number, 0 or more")
    elif c.get("status") == "own-tracks" and cn < 1:
        errs.append("provenance.calibration: status own-tracks needs n_tracks of at least 1")
    elif c.get("status") == "none" and cn != 0:
        errs.append("provenance.calibration: status none needs n_tracks 0")
    for key, check in (("rank_agreement", lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and -1 <= v <= 1),
                       ("bias", lambda v: v in BIAS)):
        d = c.get(key, {})
        if not isinstance(d, dict):
            errs.append(f"provenance.calibration.{key} must be an object")
            continue
        if d and c.get("status") == "none":
            errs.append(f"provenance.calibration.{key}: needs status own-tracks")
        for f, v in d.items():
            if f not in names:
                errs.append(f"provenance.calibration.{key}.{f}: not a declared feature")
            elif not check(v):
                errs.append(f"provenance.calibration.{key}.{f}: " + ("must be a number from -1 to 1" if key == "rank_agreement" else f"must be one of {list(BIAS)}"))
    return errs


def validate(t, require_provenance=True):
    """Return a list of problems (empty = valid). Provenance is required unless a caller opts out (old tables)."""
    errs = []
    if not isinstance(t, dict):
        return ["table must be an object"]
    if t.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    for k in ("analyzer", "analyzer_version"):
        if not isinstance(t.get(k), str) or not t.get(k):
            errs.append(f"{k} is required (non-empty string)")
    feats = t.get("features")
    names = []
    if not isinstance(feats, list) or not feats:
        errs.append("features must be a non-empty list")
    else:
        for i, f in enumerate(feats):
            n = f.get("name") if isinstance(f, dict) else None
            if not isinstance(n, str) or not FEATURE_NAME.match(n):
                errs.append(f"features[{i}].name must match {FEATURE_NAME.pattern}")
                continue
            if REFUSED_NAME.search(n):
                errs.append(f"features[{i}].name {n!r}: embeddings and speaker vectors are never stored")
            if n in names:
                errs.append(f"features[{i}].name {n!r} is repeated")
            names.append(n)
            for k in ("unit", "description"):
                if not isinstance(f.get(k), str):
                    errs.append(f"features[{i}].{k} is required (string)")
    rows = t.get("rows")
    if not isinstance(rows, list) or not rows:
        errs.append("rows must be a non-empty list")
        return errs
    seen, used = set(), set()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            errs.append(f"rows[{i}] must be an object")
            continue
        for k in ("id", "group"):
            if not isinstance(r.get(k), str) or not re.fullmatch(r"[0-9a-f]{6,64}", r.get(k) or ""):
                errs.append(f"rows[{i}].{k} must be a hex hash, not a name")
        if r.get("id") in seen:
            errs.append(f"rows[{i}].id {r.get('id')!r} is repeated")
        seen.add(r.get("id"))
        vals = r.get("values")
        if not isinstance(vals, dict) or not vals:
            errs.append(f"rows[{i}].values must be a non-empty object")
            continue
        for k, v in vals.items():
            used.add(k)
            if k not in names:
                errs.append(f"rows[{i}].values.{k}: not a declared feature")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                errs.append(f"rows[{i}].values.{k}: must be a finite number (no lists, strings or vectors)")
    for n in names:
        if n not in used:  # a table must not advertise a column that no row has
            errs.append(f"feature {n!r} is declared but no row has a value for it")
    if require_provenance or "provenance" in t:
        errs += _check_provenance(t.get("provenance"), names, len(rows))
    return errs


def column(t, name):
    """All values of one feature, in row order, skipping rows that lack it."""
    return [r["values"][name] for r in t["rows"] if name in r["values"]]


def tercile(vals, p):
    v = sorted(vals)
    return v[int(p * (len(v) - 1))]


def coverage(tables):
    """Counts only: rows and groups per table, and how many rows/groups two tables share."""
    out = {"tables": [], "shared_rows": {}, "shared_groups": {}}
    for t in tables:
        out["tables"].append({"analyzer": t["analyzer"], "rows": len(t["rows"]),
                              "groups": len({r["group"] for r in t["rows"]}),
                              "features": [f["name"] for f in t["features"]]})
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            a, b = tables[i], tables[j]
            key = f"{a['analyzer']} + {b['analyzer']}"
            out["shared_rows"][key] = len({r["id"] for r in a["rows"]} & {r["id"] for r in b["rows"]})
            out["shared_groups"][key] = len({r["group"] for r in a["rows"]} & {r["group"] for r in b["rows"]})
    return out


def load(path):
    t = json.loads(Path(path).read_text())
    errs = validate(t)
    if errs:
        raise ValueError(f"{path}: invalid feature table: " + "; ".join(errs[:5]))
    return t


def main(argv=None):
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
    import analyzers
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="read an analyzer's output file into a feature table")
    b.add_argument("analyzer", choices=sorted(analyzers.ANALYZERS))
    b.add_argument("source")
    b.add_argument("--out", required=True)
    c = sub.add_parser("coverage", help="rows, groups and overlaps of tables (counts only)")
    c.add_argument("tables", nargs="+")
    v = sub.add_parser("validate", help="check a table against the contract")
    v.add_argument("table")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            t = analyzers.ANALYZERS[a.analyzer].read(a.source)
            errs = validate(t)
            if errs:
                print("invalid table:", "; ".join(errs[:5]), file=sys.stderr)
                return 1
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(json.dumps(t, indent=1) + "\n")
            print(f"{a.analyzer}: {len(t['rows'])} rows, {len({r['group'] for r in t['rows']})} groups, "
                  f"{len(t['features'])} features -> {a.out}")
        elif a.cmd == "coverage":
            print(json.dumps(coverage([load(p) for p in a.tables]), indent=1))
        else:
            errs = validate(json.loads(Path(a.table).read_text()))
            print("ok" if not errs else "invalid: " + "; ".join(errs))
            return 0 if not errs else 1
    except (OSError, ValueError, KeyError) as e:
        print("error:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
