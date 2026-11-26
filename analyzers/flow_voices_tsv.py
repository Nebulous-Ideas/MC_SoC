"""reference-stats/flow_voices.tsv -> feature table with one row per VOICE in a track (pace and pitch movement, numbers only).

A track can hold more than one voice (a guest, a sung hook), and inside such a track who is speaking explains most of the movement in pace and pitch
spread (docs/roadmap.md, "Inside a track: fixed windows and voices"). The measuring tool, outside this repository, groups the stem's short windows by
voice and measures each voice over the pieces it holds; this reader only takes the numbers. No fingerprint, embedding or voice id is in the file or the table.

Columns used: artist, title, voice (a rank inside the track: 1 = the most heard; used only to make opaque ids, never stored) and the measures below.
A row is left out when the voice has under MIN_ACTIVE_S (60 s) of material or the file does not say how much it had. On 30 s of real stem the
pitch spread wobbles by about half the gap between the flat and melodic cuts, on 60 s by a fifth to a third (roadmap, "Planted changes on short
pieces"), and with 30 s rows two cards came out that each rested on a single voice with under 45 s; they are not built. The group is the track's artist, so a guest voice counts toward
that artist's group; the two-group rule of a card is therefore no weaker than on a table of tracks.

Not validated: the voice grouping has only been tested for comparing groups of tracks, not for which piece belongs to which voice, and it cannot tell a
second performer from one performer switching between rapping and singing. Both give a different delivery, which is what a card describes."""
import csv
import features as F

NAME, VERSION, METHOD, MIN_ACTIVE_S = "flow-voices-tsv", "1", "flow-profile-voices", 60.0
FEATURES = [
    ("voice_active_s", "s", "active time in the pieces of the track this voice holds"),
    ("heard_syl_per_active_s", "syllables/s", "syllables in the words a speech recogniser hears in this voice's pieces, per active second"),
    ("npitch_sd_st", "semitones", "median 2 s pitch standard deviation over this voice's pieces, neural pitch tracker"),
    ("npitch_span_st", "semitones", "5th-95th percentile of voiced pitch over this voice's pieces, neural pitch tracker"),
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
                    pass  # a missing or blank measure is left out, never invented
            if vals.get("voice_active_s", 0.0) < MIN_ACTIVE_S:
                continue
            rows.append({"id": F.opaque(r["artist"], r["title"], str(r["voice"])), "group": F.opaque(r["artist"], n=8), "values": vals})
    have = {k for r in rows for k in r["values"]}
    feats = [{"name": n, "unit": u, "description": d} for n, u, d in FEATURES if n in have]
    return F.make_table(NAME, VERSION, feats, rows, F.provenance(METHOD, "unspecified", len(rows), unit="voice"))
