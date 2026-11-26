"""The publish gate, shared by every publisher. Stdlib only.

A record is publishable only if it passes verify AND its sign-off is approved. A record
with verify errors is never skipped quietly: it is reported so the caller can fail.
"""
import json
from pathlib import Path
import verify as V

def publishable(records_dir):
    """Return (publishable_records, errors, skipped). errors: {file: [msgs]}, skipped: {file: status}."""
    schema = json.loads(V.SCHEMA.read_text())
    ok, errors, skipped = [], {}, {}
    for f in sorted(Path(records_dir).glob("*.json")):
        errs, _, rec = V.verify(f, schema)
        if errs:
            errors[f.name] = errs
        elif rec["signoff"]["status"] == "approved":
            ok.append(rec)
        else:
            skipped[f.name] = rec["signoff"]["status"]
    return ok, errors, skipped


def publishable_works(store):
    """Approved derived works that pass the works checks (store.verify: redaction passed, source lessons approved,
    sign-off rules). Returns (works, errors) where errors is {work id: [messages]}. Works still in draft are skipped."""
    ok, errors = [], {}
    for wid in store.list():
        w = store.get(wid)
        if w.get("signoff", {}).get("status") != "approved":
            continue
        errs = store.verify(wid)
        if errs:
            errors[wid] = errs
        else:
            ok.append(w)
    return ok, errors


# ---- releases: a named, fixed set of records -------------------------------------------
import hashlib
from datetime import datetime, timezone

def record_hash(rec):
    """sha256 of the record's canonical JSON (independent of file formatting)."""
    return hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def make_release(records_dir, name, now=None):
    """Snapshot every publishable record into a manifest. Refuses on verify errors or no records."""
    ok, errors, _ = publishable(records_dir)
    if errors:
        raise ValueError("records failed verify: " + ", ".join(sorted(errors)))
    if not ok:
        raise ValueError("no approved records to release")
    return {"schema_version": 1, "name": name,
            "created_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "records": [{"id": r["id"], "sha256": record_hash(r),
                         "approved_by": r["signoff"]["by"], "approved_at": r["signoff"]["at"]} for r in ok]}

def load_release(manifest, records_dir):
    """Return the records a release names, after checking each is unchanged, approved and verify-clean.

    Raises ValueError if any record changed since the release was made, went missing, or no longer
    passes the gate: a release is never rendered from content it did not describe."""
    ok, errors, _ = publishable(records_dir)
    if errors:
        raise ValueError("records failed verify: " + ", ".join(sorted(errors)))
    by_id = {r["id"]: r for r in ok}
    out = []
    for e in manifest["records"]:
        r = by_id.get(e["id"])
        if r is None:
            raise ValueError(f"{e['id']}: no longer approved or missing")
        if record_hash(r) != e["sha256"]:
            raise ValueError(f"{e['id']}: changed since release {manifest['name']}")
        out.append(r)
    return out
