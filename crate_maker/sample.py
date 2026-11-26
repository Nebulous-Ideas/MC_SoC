"""Crate maker, step 1: sample a library by declared rules and write the sides for crate_builder.

  python3 -I crate_maker/sample.py LIBRARY.tsv RULES.json --out DIR

LIBRARY.tsv: columns artist, title, duration_s, tags (tags separated by ';'). Tags are the attributes that define the sides;
they must not be measures (a side formed on a measured feature separates on it by construction).
RULES.json: {"seed", "min_seconds", "max_seconds", "max_per_artist", "min_artists", "require_tags", "exclude_tags",
             "sides": {"s1": {"tags_all": [...], "tags_any": [...], "tags_none": [...]}, "s2": {...}}}

Writes, in DIR (local working files: never commit them):
  sample.json  the rules hash, counts per side, and the selected rows as opaque ids and group ids
  assign.json  {side: [row ids]} in the form crate_builder.py expects (row id = features.opaque(artist, title))
Prints counts only. Stdlib only. Reads no audio.
"""
import argparse, csv, hashlib, json, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # python3 -I drops the script dir; features.py lives one level up
import features as F  # noqa: E402

DEFAULTS = {"min_seconds": 120, "max_seconds": 360, "max_per_artist": 3, "min_artists": 2,
            "require_tags": [], "exclude_tags": []}


def load_library(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            rows.append({"artist": r["artist"].strip(), "title": r["title"].strip(),
                         "seconds": float(r["duration_s"]),
                         "tags": {t.strip() for t in (r.get("tags") or "").split(";") if t.strip()}})
    return rows


def rules_hash(rules):
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def eligible(row, rules):
    if not rules["min_seconds"] <= row["seconds"] <= rules["max_seconds"]:
        return False
    if any(t not in row["tags"] for t in rules["require_tags"]):
        return False
    return not any(t in row["tags"] for t in rules["exclude_tags"])


def side_of(row, sides):
    """The first side whose tags match. A track in no side is left out, so the sides never overlap."""
    for name, spec in sides.items():
        any_ok = not spec.get("tags_any") or any(t in row["tags"] for t in spec["tags_any"])
        if any_ok and all(t in row["tags"] for t in spec.get("tags_all", [])) and not any(t in row["tags"] for t in spec.get("tags_none", [])):
            return name
    return None


def sample(rows, rules):
    """Rules are applied in a fixed order: eligibility, then a seeded shuffle of a sorted pool, then the per-artist cap."""
    pool = sorted((r for r in rows if eligible(r, rules)), key=lambda r: (r["artist"], r["title"]))
    random.Random(rules["seed"]).shuffle(pool)
    per_artist, picked, seen = {}, [], set()
    for r in pool:
        rid = F.opaque(r["artist"], r["title"])
        if rid in seen:  # the same track listed twice (e.g. a case-only difference in the title): pick it once
            continue
        seen.add(rid)
        side = side_of(r, rules["sides"])
        if side is None:
            continue
        if per_artist.get(r["artist"], 0) >= rules["max_per_artist"]:
            continue
        per_artist[r["artist"]] = per_artist.get(r["artist"], 0) + 1
        picked.append((side, r))
    out = {name: {"tracks": 0, "artists": set()} for name in rules["sides"]}
    for side, r in picked:
        out[side]["tracks"] += 1
        out[side]["artists"].add(r["artist"])
    short = [s for s, c in out.items() if len(c["artists"]) < rules["min_artists"]]
    if short:
        raise ValueError(f"side(s) {', '.join(short)} have fewer than {rules['min_artists']} artists; widen the rules")
    return picked, {s: {"tracks": c["tracks"], "artists": len(c["artists"])} for s, c in out.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library"); ap.add_argument("rules"); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rules = dict(DEFAULTS, **json.loads(Path(a.rules).read_text()))
    if "sides" not in rules or len(rules["sides"]) < 2:
        print("error: rules need two or more sides"); return 1
    try:
        picked, counts = sample(load_library(a.library), rules)
    except ValueError as e:
        print("error:", e); return 1
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    assign = {s: [] for s in rules["sides"]}
    rows = []
    for side, r in picked:
        rid = F.opaque(r["artist"], r["title"])
        assign[side].append(rid)
        rows.append({"row": rid, "group": F.opaque(r["artist"], n=8), "side": side})
    (out / "sample.json").write_text(json.dumps({"rules_hash": rules_hash(rules), "counts": counts, "rows": rows}, indent=1))
    (out / "assign.json").write_text(json.dumps(assign, indent=1))
    print("rules", rules_hash(rules), "|", ", ".join(f"{s}: {c['tracks']} tracks, {c['artists']} artists" for s, c in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
