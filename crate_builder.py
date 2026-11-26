#!/usr/bin/env python3
"""Build a crate bundle from a feature table and an assignment of rows to sides. Stdlib only.

  crate_builder.py build TABLE.json --assign ASSIGN.json --purpose delivery-reference
                         [--kind contrast|nested|overlapping|ordered|cast] [--membership chosen|verified|assumed]
                         [--matched loudness,tempo] [--features f1,f2] [--confidence low|medium|high]
                         [--claim claim-<12 hex> | --predicate JSON] [--out exchange/crates]

TABLE.json is a feature table (features.py) with provenance. ASSIGN.json maps side names to lists of the table's
row ids:  {"s1": ["ab12cd34ef56", ...], "s2": [...]}  (2 to 8 sides, named s1, s2, ... in order).
Rows in no side are simply left out. The table and the assignment are LOCAL working files (hashes of known names can be
guessed): never commit them. Only the bundle is written to the exchange, and it holds no row id, group id or name.

Computed here, so a contributor does not hand-write numbers that have to agree (and the checker recomputes the summaries):
  profile per side         p10, median, p90 of each feature
  effect per pair          rank-biserial, -1 to 1, positive when the first side tends higher
  overlap per pair         overlap of the two empirical distributions, 0 to 1
  a group effect per feature and pair (the effect between per-artist medians) and an exact two-sided p of it with the sides' ARTIST GROUP counts
  (Mann-Whitney; tracks of one artist are not independent, design decision 17), separability, distinctness, carriers (group effect of at least
  0.2 and p within a 5% level shared across all features and pairs), leaning features (|effect| of at least 0.5 but not carriers), the evidence
  tier (supported if there is a carrier, otherwise exploratory), shared artist groups, a content hash per side, the crate id (over members and numbers)
A crate may be tiny: it is a hypothesis and an observation, not a proof. Only features measured for every track in the crate are profiled.
Sides formed on a measured feature will separate on it by construction: that is circular, not a finding.
"""
import argparse, hashlib, json, math, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python3 -I drops the script dir
import features as F
import exchange as X

BINS = 20


class BuildError(Exception):
    pass


def quantile(sorted_vals, p):
    """Linear interpolation between order statistics."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = p * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def profile(vals):
    v = sorted(vals)
    return {"p10": round(quantile(v, 0.1), 4), "median": round(statistics.median(v), 4), "p90": round(quantile(v, 0.9), 4)}


def rank_biserial(a, b):
    """(2U / (n1 n2)) - 1 with ties counted half: +1 when every value in a exceeds every value in b."""
    u = sum((x > y) + 0.5 * (x == y) for x in a for y in b)
    return 2.0 * u / (len(a) * len(b)) - 1.0


def overlap(a, b):
    """Overlap coefficient of two empirical distributions on a shared grid: 1 identical, 0 disjoint."""
    lo, hi = min(min(a), min(b)), max(max(a), max(b))
    if hi == lo:
        return 1.0
    w = (hi - lo) / BINS
    def hist(v):
        h = [0] * BINS
        for x in v:
            h[min(int((x - lo) / w), BINS - 1)] += 1
        return [c / len(v) for c in h]
    return sum(min(x, y) for x, y in zip(hist(a), hist(b)))


def by_group(members, f):
    """One value per artist group: the median of that group's tracks. Tracks of one artist are not independent, so the test runs on these."""
    g = {}
    for r in members:
        g.setdefault(r["group"], []).append(r["values"][f])
    return [statistics.median(v) for v in g.values()]


def build(table, assign, purpose, kind=None, membership="chosen", matched=(), confidence=None, only_features=None, claim=None, predicate=None):
    errs = F.validate(table)
    if errs:
        raise BuildError("the table is not a valid feature table with provenance: " + "; ".join(errs[:3]))
    ids = [f"s{i}" for i in range(1, len(assign) + 1)]
    if not 2 <= len(assign) <= X.MAX_SIDES or set(assign) != set(ids):
        raise BuildError(f"the assignment needs 2 to {X.MAX_SIDES} sides named s1, s2, ... in order")
    rows = {r["id"]: r for r in table["rows"]}
    seen = {}
    for sid in ids:
        if not isinstance(assign[sid], list) or len(set(assign[sid])) != len(assign[sid]):
            raise BuildError(f"{sid} must be a list of distinct row ids")
        for rid in assign[sid]:
            if rid not in rows:
                raise BuildError(f"{sid} names a row that is not in the table")
            if rid in seen:
                raise BuildError(f"a row is assigned to both {seen[rid]} and {sid}")
            seen[rid] = sid
    members = {sid: [rows[r] for r in assign[sid]] for sid in ids}
    for sid in ids:
        groups = {r["group"] for r in members[sid]}
        if len(members[sid]) < X.MIN_SIDE_TRACKS or len(groups) < X.MIN_SIDE_GROUPS:
            raise BuildError(f"{sid} has {len(members[sid])} tracks from {len(groups)} artist groups; a side needs at least "
                             f"{X.MIN_SIDE_TRACKS} tracks from {X.MIN_SIDE_GROUPS} group")
    names = [f["name"] for f in table["features"]]
    if only_features is not None:
        unknown = [f for f in only_features if f not in names]
        if unknown or not only_features:
            raise BuildError("--features must name features the table declares" + (f" (not declared: {', '.join(unknown)})" if unknown else ""))
        names = [f for f in names if f in only_features]
    vals = {sid: {f: [r["values"][f] for r in members[sid] if f in r["values"]] for f in names} for sid in ids}
    # a feature is profiled only if EVERY track in the crate has it, so the counts are the side sizes and the exact p-values reproduce
    feats = [f for f in names if all(len(vals[sid][f]) == len(members[sid]) for sid in ids)]
    if not feats:
        raise BuildError("no feature is measured for every track in the crate")
    sides = {}
    for sid in ids:
        digest = hashlib.sha256("\n".join(sorted(assign[sid])).encode()).hexdigest()
        sides[sid] = {"count": len(members[sid]), "groups": len({r["group"] for r in members[sid]}), "content_hash": digest,
                      "profile": {f: profile(vals[sid][f]) for f in feats}}
    pairs, pair_best, carriers, leaning = [], [], set(), set()
    m = len(feats) * len(ids) * (len(ids) - 1) // 2          # comparisons sharing the 5% level
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            fe, best = {}, 0.0
            for f in feats:
                e = round(rank_biserial(vals[a][f], vals[b][f]), 4)
                ga, gb = by_group(members[a], f), by_group(members[b], f)
                ge = round(rank_biserial(ga, gb), 4)
                exact = X.mw_pvalue(ge, len(ga), len(gb))
                fe[f] = {"effect": e, "group_effect": ge, "overlap": round(overlap(vals[a][f], vals[b][f]), 4), "p": round(exact, 6)}
                best = max(best, (abs(e) + 1) / 2)
                if abs(ge) >= 0.2 and exact <= X.ALPHA / m: carriers.add(f)
                elif abs(e) >= X.LEAN: leaning.add(f)
            pairs.append({"a": a, "b": b, "features": fe}); pair_best.append(best)
    leaning -= carriers
    kind = kind or ("contrast" if len(ids) == 2 else "cast")
    smallest = min(s["count"] for s in sides.values())
    evidence = "supported" if carriers else "exploratory"
    confidence = confidence or ("low" if membership == "assumed" or evidence == "exploratory" or smallest < 8 else "medium" if smallest < 20 else "high")
    count_by_group = {}
    for sid in ids:
        for g in {r["group"] for r in members[sid]}:
            count_by_group[g] = count_by_group.get(g, 0) + 1
    prov = table["provenance"]
    universe = {"purpose": purpose, "measured_on": prov["measured_on"], "analyzer": table["analyzer"],
                "analyzer_version": table["analyzer_version"], "calibration": prov["calibration"]["status"]}
    if "instruments" in prov:
        universe["instruments"] = dict(prov["instruments"])
    crate = {"schema_version": 1, "kind": "crate", "id": "", "universe": universe, "formed_by": "operator", "sides": sides, "membership": membership,
             "relationship": {"kind": kind, "orientation": X.ORIENTATION, "confidence": confidence, "separability": round(max(pair_best), 4), "distinctness": round(min(pair_best), 4),
                              "carriers": sorted(carriers), "leaning": sorted(leaning), "evidence": evidence, "pairs": pairs},
             "confounds": {"shared_groups": sum(1 for c in count_by_group.values() if c > 1), "matched_on": sorted(set(matched))}}
    if predicate is not None:                       # sides formed by a rule over the trait vocabulary: the claim follows from the rule
        derived = X.claim_for_predicate(predicate)
        if claim not in (None, derived):
            raise BuildError("for a predicate-formed crate the claim is derived from the predicate: " + derived)
        crate["formed_by"], crate["predicate"], claim = "predicate", predicate, derived
    if claim is not None:
        crate["claim"] = claim
    crate["id"] = "crate-" + hashlib.sha256(json.dumps([universe, sides], sort_keys=True).encode()).hexdigest()[:12]   # members and numbers: a re-measured crate is a new crate
    problems = X.check_crate(crate)
    if problems:
        raise BuildError("the crate fails the exchange checker:\n  - " + "\n  - ".join(problems))
    return crate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("table"); b.add_argument("--assign", required=True)
    b.add_argument("--purpose", required=True, choices=list(X.PURPOSES))
    b.add_argument("--kind", choices=list(X.REL_KINDS_TWO + X.REL_KINDS_MANY))
    b.add_argument("--membership", choices=list(X.MEMBERSHIP), default="chosen")
    b.add_argument("--matched", default="", help="measures you matched between the sides before assigning (loudness, tempo, duration, dynamic-range)")
    b.add_argument("--features", default="", help="comma-separated features to profile; leave out size and nuisance measures (a length difference is not a finding)")
    b.add_argument("--confidence", choices=list(X.CONFIDENCE))
    b.add_argument("--claim", help="claim-<12 hex>: crates that share it test the same contrast (s1 has the quality, s2 lacks it), so they can replicate each other")
    b.add_argument("--predicate", help='JSON rule over the trait vocabulary that formed the sides, e.g. {"atom": "feel:swung"}; derives the claim')
    b.add_argument("--out", default=str(HERE / "exchange" / "crates"))
    a = ap.parse_args(argv)
    try:
        table = json.loads(Path(a.table).read_text())
        assign = json.loads(Path(a.assign).read_text())
        matched = [m for m in a.matched.split(",") if m]
        crate = build(table, assign, a.purpose, a.kind, a.membership, matched, a.confidence, [f for f in a.features.split(",") if f] or None,
                       a.claim, json.loads(a.predicate) if a.predicate else None)
    except (OSError, ValueError, BuildError) as e:
        print("error:", e, file=sys.stderr)
        return 1
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{crate['id']}.json"
    path.write_text(json.dumps(crate, indent=1) + "\n")
    r = crate["relationship"]
    print(f"{crate['id']}: {len(crate['sides'])} sides, {r['kind']}, separability {r['separability']}, distinctness {r['distinctness']}, "
          f"carriers {', '.join(r['carriers'])} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
