#!/usr/bin/env python3
"""Crate exchange: numbers-only bundles contributed through the repository. Stdlib only.

  exchange.py check [DIR]     validate every bundle under DIR (default ./exchange); non-zero if any is invalid
  exchange.py summary [DIR]   counts only

Layout:  DIR/crates/<id>.json   DIR/cards/<card>--<crate id>-<side>.json   DIR/prescriptions/<id>.json

What may be contributed (design decision 16): a crate descriptor (a count, a hash, a purpose; never names),
a persona card with where its numbers came from, a trial prescription. Never audio, lyrics, transcripts or
per-track rows. There is NO free-text field in any bundle: every string is an enum, a hash or a short
identifier, and every number is finite. Identifiers can still be chosen badly (an artist's name is a valid
identifier), so a maintainer's review is the human gate; this checker is the machine gate.
Imported data is untrusted: it is labelled community, and cards stay advisory inputs to Decide.
"""
import hashlib, json, math, re, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python3 -I drops the script dir
import features as F
import persona as P
import verify as V

IDENT = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
CRATE_ID = re.compile(r"^crate-[0-9a-f]{12}$")
CLAIM_ID = re.compile(r"^claim-[0-9a-f]{12}$")
RX_ID = re.compile(r"^rx-[0-9a-f]{12}$")
HASH64 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[0-9][0-9a-z.]{0,15}$")
PURPOSES = ("pace-reference", "rhyme-reference", "tempo-reference", "delivery-reference", "mixed")
FORMED_BY = ("predicate", "operator", "clustering")
REL_KINDS_TWO = ("contrast", "nested", "overlapping")  # two sides
REL_KINDS_MANY = ("ordered", "cast")                   # three or more sides: a gradient, or a cast of distinct personas
MEMBERSHIP = ("verified", "assumed", "chosen")         # chosen: the operator picked the members by design (a cast), no claim of checking
SIDE_ID = re.compile(r"^s[1-8]$")
MAX_SIDES = 8
MIN_SIDE_TRACKS, MIN_SIDE_GROUPS = 2, 1     # a crate is a hypothesis and may be tiny; a persona card still needs 3 tracks from 2 groups
ALPHA = 0.05                                # shared across every feature and pair in a crate
ORIENTATION = "positive_means_first_side_higher"   # the one reading every effect in a bundle uses; stated in the bundle so nobody has to remember it
LEAN = 0.5                                  # |effect| at which an unproven feature is listed as leaning
MATCHED = ("loudness", "tempo", "duration", "dynamic-range")
VOCAB = {f"{a[0]}:{w}" for kind in P.KINDS for i in P.instruments(kind) for a in i["axes"] for w in (a[4], a[5])}   # trait atoms a predicate may use
MAX_ATOMS, MAX_DEPTH = 8, 3
CONFIDENCE = ("low", "medium", "high")
EVIDENCE = ("supported", "exploratory")
FORMS = ("spoken-rhyme", "sung-hook", "skit")
DIRS = {"crate": "crates", "card": "cards", "prescription": "prescriptions"}
CARD_LABELS = {kind: {label for label, _ in spec["cards"].values()} for kind, spec in P.KINDS.items()}
CARD_LABELS_ALL = set().union(*CARD_LABELS.values())


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def whole(v, lo=0):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo


def keys(d, required, optional=()):
    if not isinstance(d, dict):
        return ["must be an object"]
    errs = [f"missing key {k!r}" for k in required if k not in d]
    errs += [f"unknown key {k!r} (bundles have no free-text or extra fields)" for k in d if k not in set(required) | set(optional)]
    return errs


def _canon(e):
    """A predicate in a form that does not depend on the order of the arguments of all/any."""
    if "atom" in e:
        return ["atom", e["atom"]]
    args = [_canon(a) for a in e["args"]]
    return [e["op"], sorted(args, key=json.dumps) if e["op"] in ("all", "any") else args]


def claim_for_predicate(pred):
    """The claim id of a predicate-formed crate: derived from the predicate, so two crates built from the same rule share a claim."""
    return "claim-" + hashlib.sha256(json.dumps(_canon(pred), sort_keys=True).encode()).hexdigest()[:12]


def check_expr(e, depth=1, atoms=None):
    """A predicate: {"atom": "pace:slow"} | {"op": "not", "args": [e]} | {"op": "all"|"any", "args": [e, ...]}."""
    atoms = atoms if atoms is not None else []
    if depth > MAX_DEPTH:
        return ["predicate is nested deeper than %d" % MAX_DEPTH], atoms
    if not isinstance(e, dict):
        return ["predicate nodes must be objects"], atoms
    if set(e) == {"atom"}:
        atoms.append(e["atom"])
        return ([] if e["atom"] in VOCAB else [f"predicate atom {str(e['atom'])[:30]!r} is not in the trait vocabulary {sorted(VOCAB)}"]), atoms
    if set(e) == {"op", "args"} and e["op"] in ("not", "all", "any") and isinstance(e["args"], list):
        n = len(e["args"])
        if (e["op"] == "not" and n != 1) or (e["op"] != "not" and not 2 <= n <= MAX_ATOMS):
            return [f"predicate op {e['op']!r} has the wrong number of arguments"], atoms
        errs = []
        for a in e["args"]:
            sub, atoms = check_expr(a, depth + 1, atoms)
            errs += sub
        return errs, atoms
    return ["predicate nodes are an atom or an op with args"], atoms


def check_profile(pr, label):
    if not isinstance(pr, dict) or not pr:
        return [f"{label}.profile must be a non-empty object of features"]
    errs = []
    for f, r in pr.items():
        if not F.FEATURE_NAME.match(str(f)) or F.REFUSED_NAME.search(str(f)):
            errs.append(f"{label}.profile has a bad feature name")
        elif keys(r, ["p10", "median", "p90"]) or not all(num(r[k]) for k in ("p10", "median", "p90")) or not r["p10"] <= r["median"] <= r["p90"]:
            errs.append(f"{label}.profile.{f} must be numbers p10 <= median <= p90")
    return errs


_MW_CACHE = {}


def mw_counts(na, nb):
    """Number of arrangements giving each Mann-Whitney U = 0 .. na*nb under the null (no ties): the coefficients of the Gaussian binomial
    [na+nb choose na]_q, built by multiplying (1 - q^(nb+i)) / (1 - q^i) for i = 1 .. na with exact integer arithmetic."""
    key = (na, nb)
    if key not in _MW_CACHE:
        poly = [1]
        for i in range(1, na + 1):
            up = [0] * (len(poly) + nb + i)           # multiply by (1 - q^(nb+i))
            for k, c in enumerate(poly):
                up[k] += c
                up[k + nb + i] -= c
            out, acc = [0] * (len(up) - i), 0          # divide by (1 - q^i): out[k] = up[k] + out[k - i]
            for k in range(len(out)):
                out[k] = up[k] + (out[k - i] if k >= i else 0)
            poly = out
        _MW_CACHE[key] = poly[:na * nb + 1]
    return _MW_CACHE[key]


def mw_pvalue(effect, na, nb):
    """Two-sided p-value for a rank-biserial effect between samples of na and nb. Exact (permutation distribution of U, ties ignored) when
    na * nb is at most 2500; a normal approximation beyond that. U is fixed by the effect: U = (effect + 1) * na * nb / 2."""
    u = (effect + 1.0) * na * nb / 2.0
    mu = na * nb / 2.0
    if na * nb <= 2500:
        counts = mw_counts(na, nb)
        total = sum(counts)
        k = max(0, min(na * nb, round(u)))
        lower = sum(counts[:k + 1]) / total
        upper = sum(counts[k:]) / total
        return min(1.0, 2.0 * min(lower, upper))
    sd = math.sqrt(na * nb * (na + nb + 1) / 12.0)
    return min(1.0, 2.0 * (1.0 - statistics.NormalDist().cdf((abs(u - mu) - 0.5) / sd)))


def check_side(sd, label):
    errs = keys(sd, ["count", "groups", "content_hash", "profile"])
    if errs:
        return [f"{label}: {e}" for e in errs]
    if not whole(sd["count"], MIN_SIDE_TRACKS): errs.append(f"{label}.count must be a whole number of at least {MIN_SIDE_TRACKS}")
    if not whole(sd["groups"], MIN_SIDE_GROUPS): errs.append(f"{label}.groups must be a whole number of at least {MIN_SIDE_GROUPS}")
    elif whole(sd["count"]) and sd["groups"] > sd["count"]: errs.append(f"{label}.groups cannot exceed count")
    if not HASH64.match(str(sd["content_hash"])): errs.append(f"{label}.content_hash must be a sha256 hex digest")
    return errs + check_profile(sd["profile"], label)


def check_crate(b):
    errs = keys(b, ["schema_version", "kind", "id", "universe", "formed_by", "sides", "membership", "relationship", "confounds"], ["predicate", "unknown", "claim"])
    if errs:
        return errs
    if not CRATE_ID.match(str(b["id"])): errs.append("id must look like crate-<12 hex>")
    u = b["universe"]
    e = keys(u, ["purpose", "measured_on", "analyzer", "analyzer_version", "calibration"], ["instruments"])
    if e:
        errs += [f"universe: {x}" for x in e]
    else:
        if u["purpose"] not in PURPOSES: errs.append(f"universe.purpose must be one of {list(PURPOSES)}")
        if u["measured_on"] not in F.MEASURED_ON: errs.append(f"universe.measured_on must be one of {list(F.MEASURED_ON)}")
        if not re.match(r"^[a-z][a-z0-9-]{0,39}$", str(u["analyzer"])): errs.append("universe.analyzer must be a short identifier")
        if not VERSION.match(str(u["analyzer_version"])): errs.append("universe.analyzer_version must look like 1 or 1.2")
        if "instruments" in u: errs += F.check_instruments(u["instruments"], "universe.instruments")
        if u["calibration"] not in F.CAL_STATUS: errs.append(f"universe.calibration must be one of {list(F.CAL_STATUS)}")
    if b["formed_by"] not in FORMED_BY: errs.append(f"formed_by must be one of {list(FORMED_BY)}")
    if b["formed_by"] == "predicate" and "predicate" not in b: errs.append("formed_by predicate needs a predicate")
    if b["formed_by"] != "predicate" and "predicate" in b: errs.append("a predicate is only allowed when formed_by is predicate (unlabelled crates are normal)")
    if "predicate" in b:
        pe, atoms = check_expr(b["predicate"])
        errs += pe
        if len(atoms) > MAX_ATOMS: errs.append(f"predicate has more than {MAX_ATOMS} atoms")
    if "claim" in b:
        if not CLAIM_ID.match(str(b["claim"])): errs.append("claim must look like claim-<12 hex> (a hash of a phrase you keep private, or derived from the predicate)")
        elif not isinstance(b["sides"], dict) or len(b["sides"]) != 2: errs.append("only a two-sided crate can carry a claim (s1 has the quality, s2 lacks it)")
        elif "predicate" in b and not check_expr(b["predicate"])[0] and b["claim"] != claim_for_predicate(b["predicate"]):
            errs.append("for a predicate-formed crate the claim is derived from the predicate: " + claim_for_predicate(b["predicate"]))
    if "unknown" in b and not whole(b["unknown"]): errs.append("unknown must be a whole number, 0 or more (tracks on no side)")
    if b["membership"] not in MEMBERSHIP: errs.append(f"membership must be one of {list(MEMBERSHIP)}")
    sd = b["sides"]
    if not isinstance(sd, dict) or not 2 <= len(sd) <= MAX_SIDES or set(sd) != {f"s{i}" for i in range(1, len(sd) + 1)}:
        return errs + [f"sides must be an object with 2 to {MAX_SIDES} sides named s1, s2, ... in order"]
    for sid in sorted(sd):
        errs += check_side(sd[sid], f"sides.{sid}")
    if errs:
        return errs
    ids = sorted(sd)
    feats = set(sd[ids[0]]["profile"])
    if any(set(sd[i]["profile"]) != feats for i in ids): return ["all sides must profile the same features"]
    r = b["relationship"]
    e = keys(r, ["kind", "orientation", "pairs", "separability", "distinctness", "carriers", "leaning", "evidence", "confidence"])
    if e:
        return [f"relationship: {x}" for x in e]
    if r["orientation"] != ORIENTATION:
        return [f"relationship.orientation must be {ORIENTATION!r}: every effect is read as positive when the first side of the pair is higher"]
    kinds = REL_KINDS_TWO if len(ids) == 2 else REL_KINDS_MANY
    if r["kind"] not in kinds: errs.append(f"relationship.kind for {len(ids)} sides must be one of {list(kinds)}")
    if r["confidence"] not in CONFIDENCE: errs.append(f"relationship.confidence must be one of {list(CONFIDENCE)}")
    if r["evidence"] not in EVIDENCE: errs.append(f"relationship.evidence must be one of {list(EVIDENCE)}")
    if b["membership"] == "assumed" and r["confidence"] != "low":
        errs.append("assumed membership (absent from a side, not verified to lack the property) can only claim low confidence")
    want = {(x, y) for n, x in enumerate(ids) for y in ids[n + 1:]}
    pairs = r["pairs"]
    if not isinstance(pairs, list) or {(p.get("a"), p.get("b")) for p in pairs if isinstance(p, dict)} != want or len(pairs) != len(want):
        return errs + ["relationship.pairs must hold each pair of sides exactly once, as {a, b, features} with a before b in side order"]
    m = len(feats) * len(want)                       # comparisons sharing the 5% level
    best_any, pair_best, carriers, leaning = 0.0, [], set(), set()
    for pr in pairs:
        pe = keys(pr, ["a", "b", "features"])
        rf = pr["features"]
        if pe or not isinstance(rf, dict) or set(rf) != feats:
            errs.append(f"relationship.pairs {pr.get('a')}/{pr.get('b')} must cover exactly the profiled features"); continue
        pa, pb, best = sd[pr["a"]]["profile"], sd[pr["b"]]["profile"], 0.0
        ga, gb = sd[pr["a"]]["groups"], sd[pr["b"]]["groups"]
        for f, v in rf.items():
            if keys(v, ["effect", "group_effect", "overlap", "p"]) or not (num(v["effect"]) and -1 <= v["effect"] <= 1 and num(v["group_effect"]) and -1 <= v["group_effect"] <= 1
                                                                         and num(v["overlap"]) and 0 <= v["overlap"] <= 1 and num(v["p"]) and 0 <= v["p"] <= 1):
                errs.append(f"relationship.pairs {pr['a']}/{pr['b']}.{f} needs effect and group_effect in [-1, 1], overlap in [0, 1] and p in [0, 1]"); continue
            # p is the test at the level of artist groups (tracks of one artist are not independent): from the group effect and the group counts
            exact = mw_pvalue(v["group_effect"], ga, gb)
            if abs(v["p"] - exact) > max(1e-4, 0.02 * exact):
                errs.append(f"relationship.pairs {pr['a']}/{pr['b']}.{f}: p should be {exact:.4g} for group_effect {v['group_effect']} with {ga} and {gb} artist groups")
            best = max(best, (abs(v["effect"]) + 1) / 2)
            if abs(v["group_effect"]) >= 0.2 and exact <= ALPHA / m: carriers.add(f)
            elif abs(v["effect"]) >= LEAN: leaning.add(f)
            # effect > 0 means the first side tends higher; a strong effect cannot contradict the medians
            if v["effect"] > 0.5 and pa[f]["median"] < pb[f]["median"]: errs.append(f"relationship.pairs {pr['a']}/{pr['b']}.{f}: effect says {pr['a']} is higher but its median is lower")
            if v["effect"] < -0.5 and pa[f]["median"] > pb[f]["median"]: errs.append(f"relationship.pairs {pr['a']}/{pr['b']}.{f}: effect says {pr['a']} is lower but its median is higher")
        pair_best.append(best); best_any = max(best_any, best)
    if not errs:
        if not num(r["separability"]) or abs(r["separability"] - best_any) > 0.01:
            errs.append(f"relationship.separability must equal the best single-feature AUC over all pairs, (|effect| + 1) / 2 = {best_any:.2f}")
        if not num(r["distinctness"]) or abs(r["distinctness"] - min(pair_best)) > 0.01:
            errs.append(f"relationship.distinctness must equal the worst pair's best AUC (how hard the two closest sides are to tell apart) = {min(pair_best):.2f}")
        leaning -= carriers
        if r["carriers"] != sorted(carriers):
            errs.append(f"relationship.carriers must be exactly the features whose group_effect is at least 0.2 with an artist-level exact p of at most {ALPHA}/{m} in some pair: {sorted(carriers)}")
        if r["leaning"] != sorted(leaning):
            errs.append(f"relationship.leaning must be exactly the features with |effect| of at least {LEAN} in some pair that are not carriers: {sorted(leaning)}")
        if r["evidence"] != ("supported" if carriers else "exploratory"):
            errs.append("relationship.evidence is supported when there is at least one carrier, otherwise exploratory")
        if r["evidence"] == "exploratory" and r["confidence"] != "low":
            errs.append("an exploratory crate (nothing beyond chance on its own) can only claim low confidence; replication across crates is what adds evidence")
        if r["kind"] == "ordered" and not any(all(sd[ids[k]]["profile"][f]["median"] < sd[ids[k + 1]]["profile"][f]["median"] for k in range(len(ids) - 1))
                                              or all(sd[ids[k]]["profile"][f]["median"] > sd[ids[k + 1]]["profile"][f]["median"] for k in range(len(ids) - 1)) for f in feats):
            errs.append("an ordered crate needs at least one feature whose medians rise or fall strictly across s1, s2, ...")
    cf = b["confounds"]
    e = keys(cf, ["shared_groups", "matched_on"])
    if e:
        errs += [f"confounds: {x}" for x in e]
    else:
        total, biggest = sum(sd[i]["groups"] for i in ids), max(sd[i]["groups"] for i in ids)
        if not whole(cf["shared_groups"]) or cf["shared_groups"] > total - biggest:
            errs.append("confounds.shared_groups (artist groups on more than one side) must be a whole number no larger than the groups outside the largest side")
        if not (isinstance(cf["matched_on"], list) and set(cf["matched_on"]) <= set(MATCHED) and len(set(cf["matched_on"])) == len(cf["matched_on"])):
            errs.append(f"confounds.matched_on must be a list from {list(MATCHED)}")
    return errs


def check_card(b):
    errs = keys(b, ["schema_version", "kind", "card", "voice_or_beat", "crate", "side", "n_tracks", "traits", "measured", "thresholds", "basis"], ["form_hint"])
    if errs:
        return errs
    kind = b["voice_or_beat"]
    if kind not in P.KINDS:
        return [f"voice_or_beat must be one of {sorted(P.KINDS)}"]
    spec = P.KINDS[kind]
    if b["card"] not in CARD_LABELS[kind]: errs.append(f"card must be one of {sorted(CARD_LABELS[kind])}")
    if not CRATE_ID.match(str(b["crate"])): errs.append("crate must look like crate-<12 hex>")
    if not SIDE_ID.match(str(b["side"])): errs.append("side must be s1 ... s8 (the card is the profile of one side of its crate; thresholds are relative to that crate)")
    if not whole(b["n_tracks"], P.MIN_TRACKS): errs.append(f"n_tracks must be a whole number of at least {P.MIN_TRACKS}")
    allowed_traits = {f"{a[0]}:{w}" for a in spec["axes"] for w in (a[4], a[5])}
    if not (isinstance(b["traits"], list) and len(b["traits"]) == len(spec["axes"]) and set(b["traits"]) <= allowed_traits):
        errs.append(f"traits must be one value per axis from {sorted(allowed_traits)}")
    t = b["thresholds"]   # the threshold names say which instrument the card was cut with; its ranges must come from the same one
    sets = [({n for a in i["axes"] for n in a[6]}, i["measured"]) for i in P.instruments(kind)]
    names, allowed = next(((n, ms) for n, ms in sets if isinstance(t, dict) and set(t) == n), sets[0])
    m = b["measured"]
    if not isinstance(m, dict) or not m or not set(m) <= set(allowed):
        errs.append(f"measured must be an object over {allowed}")
    else:
        for f, r in m.items():
            if keys(r, ["p10", "median", "p90"]) or not all(num(r[k]) for k in ("p10", "median", "p90")) or not r["p10"] <= r["median"] <= r["p90"]:
                errs.append(f"measured.{f} must be numbers p10 <= median <= p90")
    if not isinstance(t, dict) or set(t) != names or not all(num(v) for v in t.values()):
        errs.append("thresholds must be numbers for exactly " + " or ".join(str(sorted(n)) for n, _ in sets))
    if "form_hint" in b and not (isinstance(b["form_hint"], list) and b["form_hint"] and set(b["form_hint"]) <= set(FORMS)):
        errs.append(f"form_hint must be a non-empty list from {list(FORMS)}")
    bs = b["basis"]
    e = keys(bs, ["analyzer", "analyzer_version", "method", "measured_on", "calibration"])
    if e:
        errs += [f"basis: {x}" for x in e]
    else:
        if not re.match(r"^[a-z][a-z0-9-]{0,39}$", str(bs["analyzer"])): errs.append("basis.analyzer must be a short identifier")
        if not VERSION.match(str(bs["analyzer_version"])): errs.append("basis.analyzer_version must look like 1 or 1.2")
        if not F.METHOD.match(str(bs["method"])): errs.append("basis.method must be an identifier")
        if bs["measured_on"] not in F.MEASURED_ON: errs.append(f"basis.measured_on must be one of {list(F.MEASURED_ON)}")
        if bs["calibration"] not in F.CAL_STATUS: errs.append(f"basis.calibration must be one of {list(F.CAL_STATUS)}")
    return errs


def check_prescription(b):
    errs = keys(b, ["schema_version", "kind", "id", "engine", "parameter", "value", "tested_low", "tested_high", "confidence", "n_raters", "n_trials"],
                ["unit", "flat_low", "flat_high"])
    if errs:
        return errs
    if not RX_ID.match(str(b["id"])): errs.append("id must look like rx-<12 hex>")
    for k in ("engine", "parameter") + (("unit",) if "unit" in b else ()):
        if not IDENT.match(str(b[k])): errs.append(f"{k} must be a short identifier (a-z, 0-9, _)")
    for k in ("value", "tested_low", "tested_high") + tuple(k for k in ("flat_low", "flat_high") if k in b):
        if not num(b[k]): errs.append(f"{k} must be a finite number")
    if all(num(b.get(k)) for k in ("value", "tested_low", "tested_high")) and not b["tested_low"] <= b["value"] <= b["tested_high"]:
        errs.append("value must lie within tested_low..tested_high")
    if ("flat_low" in b) != ("flat_high" in b): errs.append("flat_low and flat_high go together")
    if b["confidence"] not in CONFIDENCE: errs.append(f"confidence must be one of {list(CONFIDENCE)}")
    if not whole(b["n_raters"], 1): errs.append("n_raters must be a whole number of at least 1")
    if not whole(b["n_trials"], 1): errs.append("n_trials must be a whole number of at least 1")
    return errs


CHECKS = {"crate": check_crate, "card": check_card, "prescription": check_prescription}


def check_dir(root):
    """Return ({relative path: [problems]}, {kind: count}). Empty problems everywhere means the exchange is clean."""
    root = Path(root)
    problems, counts, crates, cards = {}, {k: 0 for k in DIRS}, {}, []
    for kind, sub in DIRS.items():
        for path in sorted((root / sub).glob("*")) if (root / sub).is_dir() else []:
            rel, errs = f"{sub}/{path.name}", []
            try:
                b = json.loads(path.read_text())
            except (OSError, ValueError) as e:
                problems[rel] = [f"not readable JSON: {type(e).__name__}"]; continue
            if not path.name.endswith(".json"):
                errs.append("bundle files must end in .json")
            if not isinstance(b, dict) or b.get("schema_version") != 1:
                errs.append("schema_version must be 1")
            elif b.get("kind") != kind:
                errs.append(f"kind must be {kind!r} in {sub}/")
            else:
                errs += CHECKS[kind](b)
                for p, text in V.walk_strings(b):   # defence in depth: the same by-value scan as lessons
                    for f in V.scan_value(text):
                        errs.append(f"{p}: {f}")
                stem = path.name[:-5]
                want = {"crate": b.get("id"), "prescription": b.get("id"),
                        "card": f"{b.get('card')}--{b.get('crate')}-{b.get('side')}"}[kind]
                if stem != want:
                    errs.append(f"file name must be {want}.json")
                if kind == "crate" and not errs: crates[b["id"]] = b
                if kind == "card": cards.append((rel, b))
            counts[kind] += 1
            if errs: problems[rel] = errs
    for rel, b in cards:   # cross-checks: the crate a card names must exist and agree with it
        if rel in problems and any(e.startswith("crate must") for e in problems[rel]):
            continue
        c = crates.get(b.get("crate"))
        errs = []
        if c is None:
            errs.append(f"crate {b.get('crate')} is not in crates/ (or is itself invalid)")
        else:
            side = c["sides"].get(b.get("side")) if isinstance(b.get("side"), str) else None
            if side is None: errs.append(f"the crate has no side {str(b.get('side'))[:6]!r}")
            if side is not None and isinstance(b.get("n_tracks"), int) and b["n_tracks"] > side["count"]: errs.append("n_tracks exceeds the crate side's count")
            u = c["universe"]
            if isinstance(b.get("basis"), dict):
                for k, ck in (("measured_on", "measured_on"), ("analyzer", "analyzer"), ("analyzer_version", "analyzer_version")):
                    if b["basis"].get(k) != u[ck]: errs.append(f"basis.{k} differs from the crate's universe (cards from different measurements are not on one scale)")
        if errs: problems.setdefault(rel, []).extend(errs)
    return problems, counts


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "check"
    root = argv[1] if len(argv) > 1 else str(HERE / "exchange")
    if cmd not in ("check", "summary"):
        print(__doc__); return 2
    problems, counts = check_dir(root)
    if cmd == "summary":
        print(json.dumps({"bundles": counts, "invalid": len(problems)}, indent=1)); return 0
    for rel, errs in sorted(problems.items()):
        print(f"INVALID {rel}")
        for e in errs: print("  -", e)
    n = sum(counts.values())
    print(f"{n} bundle(s): " + ", ".join(f"{v} {k}" for k, v in counts.items()) + f"; {len(problems)} invalid")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
