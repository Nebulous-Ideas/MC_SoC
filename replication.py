#!/usr/bin/env python3
"""Replication summary over exchange crates: the statistics live here, not in any single crate. Stdlib only.

  replication.py summary [DIR]        group the valid two-sided crates that share a claim and report, per feature, whether the
                                      contrast replicates (JSON, numbers and ids only)

Why: a freeform crate of two or three tracks against three or four can never prove anything alone (even a perfect separation of
3 from 4 has an exact two-sided p of 2/35). Many small crates that lean the same way can. Design decision 17: combine the FINDINGS of
compatible crates, never their tracks or levels.

What is combined, and when:
  only crates that share a `claim` id (the same contrast, oriented the same way: s1 has the quality, s2 lacks it), are two-sided,
  and are COMPATIBLE: same measured_on, analyzer, analyzer version and calibration status. Crates without a claim, cast or ordered crates and
  invalid crates are left out (counted, not combined). Crates with identical sides (same content hashes) count once. Crates that share
  only some tracks cannot be detected from hashes alone: the summary assumes the crates are independent, and says so.
Per feature, over k independent crates:
  sign test         how many crates have s1 higher, how many lower (exact two-sided binomial, ties dropped)
  combined p        Stouffer's method on each crate's signed z from its exact p, weighted by the square root of its effective size (artist groups, not tracks)
  combined effect   size-weighted mean of the crate effects, and their weighted spread (heterogeneity)
  verdict           replicated | suggestive | inconsistent | insufficient | no-clear-pattern  (rules below)
"""
import json, math, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python3 -I drops the script dir
import exchange as X

MIN_CRATES = 3         # fewer independent crates than this: insufficient
AGREE = 0.8            # share of crates with a non-zero effect that must lean the same way
ND = statistics.NormalDist()


def sign_test_p(up, down):
    """Exact two-sided binomial test of up versus down with p0 = 0.5 (ties already dropped)."""
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def signed_z(effect, p):
    z = ND.inv_cdf(1 - max(min(p, 1.0), 1e-12) / 2)
    return z if effect > 0 else -z if effect < 0 else 0.0


def compat_key(u):
    return (u["measured_on"], u["analyzer"], u["analyzer_version"], u["calibration"])


def summarize_feature(obs, m):
    """obs: [(effect, p, n1, n2)] for one feature over independent crates. m: features tested in this group (Bonferroni)."""
    k = len(obs)
    nonzero = [o for o in obs if o[0] != 0]
    up, down = sum(o[0] > 0 for o in obs), sum(o[0] < 0 for o in obs)
    w = [math.sqrt(o[2] * o[3] / (o[2] + o[3])) for o in obs]           # sqrt of the effective sample size
    z = sum(wi * signed_z(o[0], o[1]) for wi, o in zip(w, obs)) / math.sqrt(sum(wi * wi for wi in w))
    combined_p = min(1.0, 2 * (1 - ND.cdf(abs(z))))
    wsum = sum(o[2] * o[3] / (o[2] + o[3]) for o in obs)
    eff = sum(o[0] * o[2] * o[3] / (o[2] + o[3]) for o in obs) / wsum
    spread = math.sqrt(sum((o[0] - eff) ** 2 * o[2] * o[3] / (o[2] + o[3]) for o in obs) / wsum)
    agree = max(up, down) / len(nonzero) if nonzero else 0.0
    sp = sign_test_p(up, down)
    alpha = X.ALPHA / m
    if k < MIN_CRATES:
        verdict = "insufficient"
    elif agree >= AGREE and sp <= alpha and combined_p <= alpha:
        verdict = "replicated"
    elif agree >= AGREE and combined_p <= X.ALPHA:
        verdict = "suggestive"
    elif nonzero and agree < 0.7:
        verdict = "inconsistent"
    else:
        verdict = "no-clear-pattern"
    return {"crates": k, "s1_higher": up, "s1_lower": down, "agreement": round(agree, 4), "sign_test_p": round(sp, 6),
            "combined_z": round(z, 4), "combined_p": round(combined_p, 6), "combined_effect": round(eff, 4),
            "heterogeneity": round(spread, 4), "verdict": verdict}


def summarize(root):
    problems, _ = X.check_dir(root)
    root = Path(root)
    excluded = {"invalid": 0, "no_claim": 0, "not_two_sided": 0, "duplicate": 0}
    groups = {}
    seen = set()
    cdir = root / "crates"
    for path in sorted(cdir.glob("*.json")) if cdir.is_dir() else []:
        if f"crates/{path.name}" in problems:
            excluded["invalid"] += 1
            continue
        c = json.loads(path.read_text())
        if len(c["sides"]) != 2:
            excluded["not_two_sided"] += 1
            continue
        if "claim" not in c:
            excluded["no_claim"] += 1
            continue
        ident = (c["claim"], compat_key(c["universe"]), c["sides"]["s1"]["content_hash"], c["sides"]["s2"]["content_hash"])
        if ident in seen:                              # the same members measured the same way: one crate, not two
            excluded["duplicate"] += 1
            continue
        seen.add(ident)
        groups.setdefault((c["claim"], compat_key(c["universe"])), []).append(c)
    out = []
    for (claim, key), crates in sorted(groups.items()):
        feats = sorted(set.intersection(*[set(c["sides"]["s1"]["profile"]) for c in crates]))
        res = {}
        for f in feats:
            obs = []
            for c in crates:
                v = c["relationship"]["pairs"][0]["features"][f]
                obs.append((v["group_effect"], v["p"], c["sides"]["s1"]["groups"], c["sides"]["s2"]["groups"]))
            res[f] = summarize_feature(obs, len(feats))
        out.append({"claim": claim, "universe": dict(zip(("measured_on", "analyzer", "analyzer_version", "calibration"), key)),
                    "crates": len(crates), "supported_crates": sum(c["relationship"]["evidence"] == "supported" for c in crates),
                    "tracks_s1": sum(c["sides"]["s1"]["count"] for c in crates), "tracks_s2": sum(c["sides"]["s2"]["count"] for c in crates),
                    "features": res})
    return {"groups": out, "left_out": excluded,
            "note": "crates are assumed independent: hashes detect identical sides only, not crates that share some tracks"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "summary":
        print(__doc__); return 2
    root = argv[1] if len(argv) > 1 else str(HERE / "exchange")
    print(json.dumps(summarize(root), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
