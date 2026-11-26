#!/usr/bin/env python3
"""Publish approved lesson records with a chosen publisher.

  python3 publish.py static-site --out public
  python3 publish.py static-site --release releases/2026-11-11.json --out public
  python3 publish.py --list

Every publisher goes through the same gate (gate.py): only approved, verify-clean records
are published, and any record with verify errors fails the run (nothing is published).
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import gate
from publishers import PUBLISHERS

HERE = Path(__file__).resolve().parent
RECORDS_COLLECTION = "b168dc15-7b02-4fb2-93da-065eb68a5fac"   # MC SOC lesson records (Outline)
WORKS_COLLECTION = "4502b817-b7d1-4602-9b06-7cb7cfe1bfd2"     # MC SOC derived works (Outline)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("publisher", nargs="?", choices=sorted(PUBLISHERS))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--records", default=str(HERE / "records"))
    ap.add_argument("--out", default="public")
    ap.add_argument("--release", help="render this release manifest instead of the live approved records")
    ap.add_argument("--works", choices=["none", "file", "outline"], default="none",
                    help="also publish approved derived works: from works/ (file) or the Outline works collection")
    a = ap.parse_args()
    if a.list or not a.publisher:
        print("\n".join(sorted(PUBLISHERS))); return 0
    if a.release:
        try:
            ok = gate.load_release(json.loads(Path(a.release).read_text()), a.records)
        except (ValueError, OSError, KeyError) as e:
            print("error:", e); return 1
    else:
        ok, errors, skipped = gate.publishable(a.records)
        for f, st in skipped.items():
            print(f"skip  {f}: signoff={st}")
        if errors:
            for f, errs in errors.items():
                print(f"ERROR {f}:", *errs, sep="\n  - ")
            print(f"{len(errors)} record(s) failed verify; nothing published"); return 1
    kw = {}
    if a.works != "none":
        import memory, review
        lessons = memory.FileMemory(a.records)
        if a.works == "file":
            store = memory.FileWorks(str(HERE / "works"), lessons)
        else:
            store = memory.OutlineWorks(WORKS_COLLECTION, memory.OutlineMemory(RECORDS_COLLECTION), )
        works, werrors = gate.publishable_works(store)
        if werrors:
            for wid, errs in werrors.items():
                print(f"ERROR work {wid}:", *errs, sep="\n  - ")
            print(f"{len(werrors)} work(s) failed checks; nothing published"); return 1
        kw["works"] = works
    written = PUBLISHERS[a.publisher].publish(ok, a.out, **kw)
    print(f"{a.publisher}: published {len(ok)} record(s) -> {', '.join(written)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
