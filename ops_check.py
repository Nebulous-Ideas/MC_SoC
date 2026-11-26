#!/usr/bin/env python3
"""Pre-run operations check: is everything MC SOC needs in order? Read-only. Stdlib only.

  python3 ops_check.py                 # uses ops.json, else ops.example.json
  python3 ops_check.py --config FILE --json

The checks come from a config file, not from code, so another setup swaps in its own.
Check types: http (url, expect, optional bearer_env), tcp (host, port), disk (path,
max_used_pct), env (names), verify (root: runs verify --all on the repo). A check marked
"required": false only warns. Secrets are never printed: env checks report set/unset,
and bearer tokens are read from the named environment variable and never echoed.
Exit 0 when every required check passes.
"""
import argparse, json, os, shutil, socket, sys, urllib.request, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import verify as V

HERE = Path(__file__).resolve().parent

def c_http(c):
    req = urllib.request.Request(c["url"])
    if c.get("bearer_env"):
        tok = os.environ.get(c["bearer_env"], "")
        if not tok:
            return "skip", f"{c['bearer_env']} is not set"
        req.add_header("Authorization", "Bearer " + tok)
    try:
        r = urllib.request.urlopen(req, timeout=c.get("timeout", 5))
        code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return "fail", type(e).__name__
    lo, hi = c.get("expect", [200, 299])
    return ("ok" if lo <= code <= hi else "fail"), f"HTTP {code}"

def c_tcp(c):
    try:
        socket.create_connection((c["host"], c["port"]), timeout=c.get("timeout", 5)).close()
        return "ok", f"{c['host']}:{c['port']} open"
    except Exception as e:
        return "fail", f"{c['host']}:{c['port']} {type(e).__name__}"

def c_disk(c):
    u = shutil.disk_usage(c["path"])
    pct = round(100 * u.used / u.total)
    return ("ok" if pct <= c.get("max_used_pct", 90) else "fail"), f"{pct}% used, {u.free // 2**30} GiB free"

def c_env(c):
    missing = [n for n in c["names"] if not os.environ.get(n)]
    return ("ok" if not missing else "fail"), ("all set" if not missing else "unset: " + ", ".join(missing))

def c_verify(c):
    res = V.verify_all(c.get("root", str(HERE)))
    bad = [k for k, e in res.items() if e]
    return ("ok" if not bad else "fail"), f"{len(res)} item(s), {len(bad)} with errors"

TYPES = {"http": c_http, "tcp": c_tcp, "disk": c_disk, "env": c_env, "verify": c_verify}

def run(config):
    out = []
    for c in config["checks"]:
        try:
            status, detail = TYPES[c["type"]](c)
        except Exception as e:
            status, detail = "fail", f"check error: {type(e).__name__}"
        out.append({"name": c["name"], "required": c.get("required", True), "status": status, "detail": detail})
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = Path(a.config) if a.config else next((p for p in (HERE / "ops.json", HERE / "ops.example.json") if p.exists()), None)
    if not cfg:
        print("no ops.json or ops.example.json"); return 1
    results = run(json.loads(cfg.read_text()))
    failed = [r for r in results if r["status"] == "fail" and r["required"]]
    if a.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            mark = {"ok": "ok  ", "fail": "FAIL" if r["required"] else "warn", "skip": "skip"}[r["status"]]
            print(f"{mark} {r['name']}: {r['detail']}")
        print(f"\n{len(failed)} required check(s) failing")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
