#!/usr/bin/env python3
"""Sync lesson records between the local cache (records/) and a memory system.

  OUTLINE_URL=... OUTLINE_API_TOKEN=... python3 sync.py pull --collection <id>
  python3 sync.py push --collection <id>

The token is read from the environment only. Run verify.py after every pull.
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import memory

HERE = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("op", choices=["pull", "push"])
    ap.add_argument("--collection", required=True, help="Outline collection id")
    ap.add_argument("--cache", default=str(HERE / "records"))
    ap.add_argument("--force", action="store_true", help="pull: overwrite local edits")
    a = ap.parse_args()
    cache = memory.FileMemory(a.cache)
    try:
        remote = memory.OutlineMemory(a.collection)
        done = memory.pull(remote, cache, a.force) if a.op == "pull" else memory.push(cache, remote)
    except (RuntimeError, PermissionError, KeyError, ValueError) as e:
        print("error:", e); return 1
    print(f"{a.op}: {len(done)} record(s)", *done)
    return 0

if __name__ == "__main__":
    sys.exit(main())
