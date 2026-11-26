#!/usr/bin/env python3
"""Build persona cards from measured feature tables. Stdlib only.

Method: measure, don't sample - every row in the table is used. Each kind of card has two axes, each split at
the table's own terciles (the middle third of an axis is left out of the named cards):
  voice  pace (heard syllables per active second) x delivery (pitch spread: low = spoken/deadpan, high = melodic)
  beat   tempo (bpm) x feel (swing: high = swung, low = straight)
A new kind is a new entry in KINDS; the builder never branches on a kind's name.

A kind may list OLDER instruments for the same axes. The voice axes moved (2026-11-13) to the measures that passed a known-manipulation
test on real vocal stems; a table that lacks them (written before flow-tsv version 2) is still cut on the older pair, syllable nuclei per
voiced second and flat_pct. The trait words and card labels are the same either way; the threshold names differ, so a card always says
which instrument its numbers came from, and thresholds from the two must never be compared.

Privacy/guardrail: a card holds only a label, counts, measured ranges and a form mapping.
No artist or track names (and no row ids) are written, a card needs >= MIN_GROUPS distinct artist groups,
and cards describe traits to write toward - never a person to imitate.

A table may hold one row per VOICE instead of per track (provenance.unit, analyzer flow-voices-tsv). The builder treats the rows the same;
the card then carries "rows_are": "voices" and its n_tracks counts voices, so a track with a rapped verse and a sung hook can feed two cards.

Usage:
  persona.py build TABLE.json --kind voice|beat [--out personas]   from a feature table (see features.py)
  persona.py TSV [--out personas]                                  legacy: a flow_profile.tsv straight to voice cards
"""
import argparse, csv, json, statistics, sys
OWN_ARTIST = "OURS"   # the artist value for our own tracks in flow_profile.tsv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import features as F

MIN_TRACKS, MIN_GROUPS = 3, 2

KINDS = {
    "voice": {
        # axis: (feature, high label, low label, high trait word, low trait word, threshold names (high, low))
        "axes": [("pace", "heard_syl_per_active_s", "fast", "slow", "fast", "slow", ("heard_pace_fast_min", "heard_pace_slow_max")),
                 ("delivery", "npitch_sd_st", "melodic", "flat", "melodic", "deadpan", ("spread_melodic_min", "spread_flat_max"))],
        "measured": ["heard_syl_per_active_s", "npitch_sd_st", "npitch_span_st", "pause_share_pct"],
        "older": [{"axes": [("pace", "syl_per_voiced_s", "fast", "slow", "fast", "slow", ("pace_fast_min", "pace_slow_max")),
                            ("delivery", "flat_pct", "flat", "melodic", "deadpan", "melodic", ("flat_min", "melodic_max"))],
                   "measured": ["syl_per_voiced_s", "flat_pct", "pitch_span_st"]}],
        "cards": {("fast", "flat"): ("rapid-deadpan", ["spoken-rhyme"]),
                  ("fast", "melodic"): ("rapid-melodic", ["spoken-rhyme", "sung-hook"]),
                  ("slow", "flat"): ("slow-deadpan", ["skit", "spoken-rhyme"]),
                  ("slow", "melodic"): ("slow-melodic", ["sung-hook"])},
    },
    "beat": {
        "axes": [("tempo", "bpm", "fast", "slow", "fast", "slow", ("tempo_fast_min", "tempo_slow_max")),
                 ("feel", "swing", "swung", "straight", "swung", "straight", ("swing_swung_min", "straight_max"))],
        "measured": ["bpm", "swing", "lufs", "lra"],
        "cards": {("fast", "swung"): ("fast-swung", None), ("fast", "straight"): ("fast-straight", None),
                  ("slow", "swung"): ("slow-swung", None), ("slow", "straight"): ("slow-straight", None)},
    },
}


def instruments(kind):
    """The axis sets of a kind, preferred first: [{"axes": [...], "measured": [...]}]."""
    spec = KINDS[kind]
    return [{"axes": spec["axes"], "measured": spec["measured"]}] + list(spec.get("older", []))


def rng(vals):
    v = sorted(vals)
    return {"p10": round(F.tercile(v, .1), 2), "median": round(statistics.median(v), 2), "p90": round(F.tercile(v, .9), 2)}


def build_rows(rows, kind):
    """rows: [{"group": hashable, "values": {feature: number}}]. Returns cards for one kind."""
    cards_of = KINDS[kind]["cards"]
    for spec in instruments(kind):   # the first instrument the table was measured with; rows lacking it are left out, never filled from another
        (_, f_a, hi_a, lo_a, *_), (_, f_b, hi_b, lo_b, *_) = spec["axes"]
        usable = [r for r in rows if f_a in r["values"] and f_b in r["values"]]
        if usable:
            break
    else:
        return []
    cut = {}
    for name, feat, *_rest in spec["axes"]:
        vals = [r["values"][feat] for r in usable]
        cut[name] = (F.tercile(vals, .33), F.tercile(vals, .67))
    groups = {}
    for r in usable:
        a = hi_a if r["values"][f_a] >= cut[spec["axes"][0][0]][1] else lo_a if r["values"][f_a] < cut[spec["axes"][0][0]][0] else None
        b = hi_b if r["values"][f_b] >= cut[spec["axes"][1][0]][1] else lo_b if r["values"][f_b] < cut[spec["axes"][1][0]][0] else None
        if a and b:
            groups.setdefault((a, b), []).append(r)
    cards = []
    for key, rs in sorted(groups.items()):
        if len(rs) < MIN_TRACKS or len({r["group"] for r in rs}) < MIN_GROUPS:
            continue
        label, forms = cards_of[key]
        traits, thresholds = [], {}
        for (name, feat, hi, lo, hi_t, lo_t, (hi_n, lo_n)), picked in zip(spec["axes"], key):
            traits.append(f"{name}:{hi_t if picked == hi else lo_t}")
            lo_cut, hi_cut = cut[name]
            thresholds[hi_n], thresholds[lo_n] = round(hi_cut, 2), round(lo_cut, 2)
        card = {"schema_version": 1, "card": label, "kind": kind, "n_tracks": len(rs), "traits": traits,
                "measured": {m: rng([r["values"][m] for r in rs if m in r["values"]])
                             for m in spec["measured"] if any(m in r["values"] for r in rs)}}
        if forms:
            card["form_hint"] = forms
        card["thresholds"] = thresholds
        cards.append(card)
    return cards


def build_table(table, kind, basis=False):
    """Cards from a feature table. basis=True adds where the numbers came from (analyzer, method, calibration), no ids."""
    cards = build_rows([{"group": r["group"], "values": r["values"]} for r in table["rows"]], kind)
    unit = (table.get("provenance") or {}).get("unit", "track")
    if unit != "track":   # n_tracks then counts rows of that unit: a track with two voices can feed two cards
        for c in cards:
            c["rows_are"] = unit + "s"
    if basis and table.get("provenance"):
        pv = table["provenance"]
        info = {"analyzer": table["analyzer"], "analyzer_version": table["analyzer_version"], "method": pv["method"],
                "measured_on": pv["measured_on"], "calibration": pv["calibration"]["status"]}
        for c in cards:
            c["basis"] = info
    return cards


def build(rows):
    """Legacy entry: csv rows from flow_profile.tsv (strings, with an 'artist' column) -> voice cards.
    The artist is only used in memory to count distinct groups; it is never written."""
    internal = []
    for r in rows:
        vals = {}
        for k in {f for i in instruments("voice") for f in [a[1] for a in i["axes"]] + i["measured"]}:
            try:
                vals[k] = float(r[k])
            except (KeyError, TypeError, ValueError):
                pass
        internal.append({"group": r["artist"], "values": vals})
    return build_rows(internal, "voice")


def write(cards, out):
    out = Path(out)
    out.mkdir(exist_ok=True)
    for c in cards:
        (out / f"{c['card']}.json").write_text(json.dumps(c, indent=2) + "\n")
        print(f"{c['card']}: {c['n_tracks']} {c.get('rows_are', 'tracks')}" + (f" -> {', '.join(c['form_hint'])}" if c.get("form_hint") else ""))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default_out = str(Path(__file__).resolve().parent / "personas")
    if argv and argv[0] == "build":
        ap.add_argument("cmd"); ap.add_argument("table"); ap.add_argument("--kind", choices=sorted(KINDS), required=True)
        ap.add_argument("--out", default=default_out)
        a = ap.parse_args(argv)
        try:
            table = F.load(a.table)
        except (OSError, ValueError) as e:
            print("error:", e, file=sys.stderr)
            return 1
        cards = build_table(table, a.kind, basis=True)
        write(cards, a.out)
        print(f"{len(table['rows'])} rows measured, {len(cards)} {a.kind} card(s)")
        return 0
    ap.add_argument("tsv"); ap.add_argument("--out", default=default_out)
    a = ap.parse_args(argv)
    rows = [r for r in csv.DictReader(open(a.tsv), delimiter="\t") if r["artist"].strip() != OWN_ARTIST]  # our own tracks never shape reference cards
    cards = build(rows)
    write(cards, a.out)
    print(f"{len(rows)} tracks measured, {len(cards)} card(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
