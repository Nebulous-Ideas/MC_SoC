#!/usr/bin/env python3
"""Make and check releases: a named, fixed set of approved records.

  python3 release.py make 2026-11-11            # writes releases/2026-11-11.json
  python3 release.py check releases/2026-11-11.json

A release is a manifest (record ids, content hashes, who approved and when). It does not
contain the records; commit it and tag the commit so the records at that tag are the release.
Publishers render a release with:  python3 publish.py static-site --release FILE
"""
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import gate

HERE = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("op", choices=["make", "check"])
    ap.add_argument("target", help="release name (make) or manifest file (check)")
    ap.add_argument("--records", default=str(HERE / "records"))
    ap.add_argument("--out", default=str(HERE / "releases"))
    a = ap.parse_args()
    try:
        if a.op == "make":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", a.target):
                raise ValueError("release name: letters, digits, . _ - only")
            path = Path(a.out) / f"{a.target}.json"
            if path.exists():
                raise ValueError(f"{path} already exists; releases are not overwritten")
            m = gate.make_release(a.records, a.target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(m, indent=2) + "\n")
            print(f"wrote {path}: {len(m['records'])} record(s)")
        else:
            m = json.loads(Path(a.target).read_text())
            gate.load_release(m, a.records)
            print(f"ok: release {m['name']} matches {len(m['records'])} record(s)")
    except (ValueError, OSError, KeyError) as e:
        print("error:", e); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
