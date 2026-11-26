#!/usr/bin/env python3
"""MC SOC verify stage. Stdlib only.

Checks every lesson record in a directory (default: records/):
  1. schema      record validates against schema/lesson-record.schema.json
  2. redaction   scan every string VALUE for secrets (not field names)
  3. evidence    each claim has a checkable ref in a known form
  4. signoff     approved needs a named human, a time and a channel;
                 approval is refused while redaction fails; a declared
                 redaction 'passed' that the scan contradicts is an error

Exit 0 when no record has an error. With --require-approved, exit 1 unless
every record is also redaction-clean and signed off (the publish gate).
Unattended runs are generate-only: this script never writes a sign-off.
"""
import argparse, json, math, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema" / "lesson-record.schema.json"
NON_HUMAN = {"unattended", "cli", "bot", "claude", "ci", "auto"}

# ---------- minimal JSON-Schema subset (no jsonschema package installed) ----------
DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

def check_schema(v, s, path, errs):
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} not in {s['enum']}")
    t = s.get("type")
    py = {"object": dict, "array": list, "string": str}.get(t)
    if py and not isinstance(v, py):
        errs.append(f"{path}: expected {t}")
        return
    if t == "string":
        if len(v) < s.get("minLength", 0):
            errs.append(f"{path}: too short")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: does not match {s['pattern']}")
        if s.get("format") == "date-time" and not DT.match(v):
            errs.append(f"{path}: not an RFC3339 date-time")
    elif t == "array":
        if len(v) < s.get("minItems", 0):
            errs.append(f"{path}: needs at least {s['minItems']} item(s)")
        for i, x in enumerate(v):
            check_schema(x, s.get("items", {}), f"{path}[{i}]", errs)
    elif t == "object":
        props = s.get("properties", {})
        for r in s.get("required", []):
            if r not in v:
                errs.append(f"{path}.{r}: required")
        for k, x in v.items():
            if k in props:
                check_schema(x, props[k], f"{path}.{k}", errs)
            elif s.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: unexpected field")

# ---------- redaction by value ----------
PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{10,}")),
    ("GitHub token", re.compile(r"\b(ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("API-style key", re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{20,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("bearer/basic header value", re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{12,}")),
    ("assigned secret", re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|apikey|auth)\b\s*[:=]\s*[^\s,;\"']{4,}")),
    ("private IPv4", re.compile(r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")),
    ("email address", re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b")),
]
URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s\"'<>]+")
SECRET_PARAM = re.compile(r"(?i)(^|[?&;])(token|access_token|key|api_key|apikey|password|passwd|secret|sig|signature|auth)=([^&#\s]+)")
USERINFO = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s@]+:[^/\s@]+@")

def entropy(s):
    return -sum((s.count(c) / len(s)) * math.log2(s.count(c) / len(s)) for c in set(s))

def scan_value(text):
    """Return list of finding labels for one string value."""
    found = []
    for url in URL.findall(text):
        if USERINFO.match(url):
            found.append("credentials in URL")
        if SECRET_PARAM.search(url):
            found.append("secret in URL query")
    stripped = URL.sub(" ", text)  # URLs handled above; slugs there are not secrets
    for label, rx in PATTERNS:
        if rx.search(text) and label not in found:
            found.append(label)
    for tok in re.findall(r"[A-Za-z0-9+/_=\-]{28,}", stripped):
        if (any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)
                and entropy(tok) >= 4.0):
            found.append("high-entropy token")
            break
    return found

def walk_strings(v, path=""):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from walk_strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk_strings(x, f"{path}[{i}]")

# ---------- evidence refs ----------
REF_OK = re.compile(r"^(https?://[^\s]+|claude-config:[^\s]+|outline:[0-9a-f\-]{36}(#[\w\-]+)?|file:[^\s]+)$")

def check_evidence(rec, errs):
    for i, e in enumerate(rec.get("evidence", [])):
        if not REF_OK.match(e.get("ref", "")):
            errs.append(f"evidence[{i}].ref: not a checkable reference ({e.get('ref')!r})")
    if not REF_OK.match(rec.get("source", {}).get("ref", "")):
        errs.append("source.ref: not a checkable reference")

# ---------- sign-off ----------
def check_signoff(rec, errs, redaction_clean):
    so = rec.get("signoff", {})
    if so.get("status") == "approved":
        for f in ("by", "at", "channel"):
            if not so.get(f):
                errs.append(f"signoff.{f}: required when approved")
        if str(so.get("by", "")).strip().lower() in NON_HUMAN:
            errs.append("signoff.by: approval must come from a named person, not an unattended run")
        if not redaction_clean or rec.get("redaction", {}).get("status") != "passed":
            errs.append("signoff: approved while redaction has not passed")

def verify(path, schema):
    try:
        rec = json.loads(path.read_text())
    except Exception as ex:
        return ["unreadable JSON: %s" % ex], [], None
    return verify_record(rec, schema, path.stem)

def verify_record(rec, schema, stem):
    errs, notes = [], []
    check_schema(rec, schema, "$", errs)
    if errs:
        return errs, notes, rec
    hits = []
    for p, text in walk_strings(rec):
        for label in scan_value(text):
            hits.append(f"redaction: {label} in {p}")
    errs += hits
    if hits and rec["redaction"]["status"] == "passed":
        errs.append("redaction.status is 'passed' but the value scan found secrets")
    if not hits and rec["redaction"]["status"] == "failed":
        notes.append("redaction.status is 'failed' but the scan is clean; re-run and update the record")
    check_evidence(rec, errs)
    check_signoff(rec, errs, not hits)
    if rec["id"] != stem:
        errs.append(f"id {rec['id']!r} does not match file name {stem!r}")
    return errs, notes, rec

# ---------- derived works and feedback ----------
def load_dir(d):
    out = {}
    for f in sorted(Path(d).glob("*.json")) if Path(d).is_dir() else []:
        try:
            out[f.stem] = json.loads(f.read_text())
        except Exception:
            out[f.stem] = None
    return out

def scan_all(rec):
    return [f"redaction: {label} in {p}" for p, text in walk_strings(rec) for label in scan_value(text)]

def verify_derived(rec, schema, stem, lessons):
    errs = []
    check_schema(rec, schema, "$", errs)
    if errs:
        return errs
    hits = scan_all(rec)
    errs += hits
    if hits and rec["redaction"]["status"] == "passed":
        errs.append("redaction.status is 'passed' but the value scan found secrets")
    for lid in rec["lesson_ids"]:
        l = lessons.get(lid)
        if not l:
            errs.append(f"lesson_ids: {lid!r} does not exist")
        elif l.get("signoff", {}).get("status") != "approved":
            errs.append(f"lesson_ids: {lid!r} is not approved")
    for i, link in enumerate(rec.get("source_links", [])):
        if not REF_OK.match(link):
            errs.append(f"source_links[{i}]: not a checkable reference")
    if rec["status"] in ("approved", "published"):
        so = rec["signoff"]
        if so.get("status") != "approved":
            errs.append(f"status {rec['status']!r} needs an approved sign-off")
        check_signoff(rec, errs, not hits)
    if rec["id"] != stem:
        errs.append(f"id {rec['id']!r} does not match file name {stem!r}")
    return errs

def verify_feedback(rec, schema, stem, targets):
    errs = []
    check_schema(rec, schema, "$", errs)
    if errs:
        return errs
    errs += scan_all(rec)
    if rec["target"] not in targets:
        errs.append(f"target {rec['target']!r} does not exist")
    if str(rec["by"]).strip().lower() in NON_HUMAN:
        errs.append("by: feedback must name a person")
    if rec["id"] != stem:
        errs.append(f"id {rec['id']!r} does not match file name {stem!r}")
    return errs

def verify_all(root):
    """Verify lessons (records/), derived works (works/) and feedback (feedback/). Returns {path: [errors]}."""
    root = Path(root)
    ls = json.loads(SCHEMA.read_text())
    ds = json.loads((SCHEMA.parent / "derived-work.schema.json").read_text())
    fs = json.loads((SCHEMA.parent / "feedback.schema.json").read_text())
    lessons, works, fb = load_dir(root / "records"), load_dir(root / "works"), load_dir(root / "feedback")
    res = {}
    for k, r in lessons.items():
        res[f"records/{k}.json"] = verify_record(r, ls, k)[0] if r else ["unreadable JSON"]
    for k, r in works.items():
        res[f"works/{k}.json"] = verify_derived(r, ds, k, lessons) if r else ["unreadable JSON"]
    targets = set(lessons) | set(works)
    for k, r in fb.items():
        res[f"feedback/{k}.json"] = verify_feedback(r, fs, k, targets) if r else ["unreadable JSON"]
    return res

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?", default=str(HERE / "records"))
    ap.add_argument("--all", action="store_true", help="also verify works/ (derived works) and feedback/ next to records/")
    ap.add_argument("--require-approved", action="store_true", help="publish gate: fail unless every record is clean and signed off")
    a = ap.parse_args()
    if a.all:
        res = verify_all(Path(a.dir).parent if Path(a.dir).name == "records" else a.dir)
        for path, errs in sorted(res.items()):
            print(f"{'ERROR' if errs else 'ok':5} {path}")
            for m in errs: print("      -", m)
        bad = sum(bool(e) for e in res.values())
        print(f"\n{len(res)} item(s), {bad} with errors")
        return 1 if bad else 0
    schema = json.loads(SCHEMA.read_text())
    files = sorted(Path(a.dir).glob("*.json"))
    if not files:
        print("no records found in", a.dir); return 1
    bad = gated = 0
    for f in files:
        errs, notes, rec = verify(f, schema)
        state = "ERROR" if errs else "ok"
        so = rec.get("signoff", {}).get("status") if rec else "?"
        print(f"{state:5} {f.name}  signoff={so}")
        for m in errs: print("      -", m)
        for m in notes: print("      ·", m)
        bad += bool(errs)
        if not errs and so != "approved":
            gated += 1
    print(f"\n{len(files)} record(s), {bad} with errors, {gated} awaiting sign-off")
    if bad:
        return 1
    if a.require_approved and gated:
        print("publish gate: BLOCKED (sign-off pending)"); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
