"""reference-stats/results.tsv -> feature table (tempo, swing, loudness, spectral balance: numbers only).

Columns used: artist, title (only to make opaque ids, never stored) and the numeric measures below.
The per-step drum pattern columns (kick16 and friends) and balance_db (five band levels in one cell) are not
single numbers, so they are not read; splitting them needs the band definitions, which this adapter does not guess."""
import csv
import features as F

NAME, VERSION, METHOD = "rhythm-tsv", "1", "results-tsv"
FEATURES = [
    ("seconds", "s", "track length"),
    ("bpm", "beats/min", "estimated tempo"),
    ("conf", "ratio", "confidence of the tempo estimate"),
    ("swing", "ratio", "off-beat timing: about 0.5 is straight, higher is swung"),
    ("lufs", "LUFS", "integrated loudness"),
    ("lra", "LU", "loudness range"),
]


def read(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            vals = {}
            for name, _, _ in FEATURES:
                try:
                    vals[name] = float(r[name])
                except (KeyError, TypeError, ValueError):
                    pass
            if vals:
                rows.append({"id": F.opaque(r["artist"], r["title"]), "group": F.opaque(r["artist"], n=8), "values": vals})
    return F.make_table(NAME, VERSION, [{"name": n, "unit": u, "description": d} for n, u, d in FEATURES], rows,
                        F.provenance(METHOD, "unspecified", len(rows)))   # a TSV reader cannot know what the measuring tool measured on
