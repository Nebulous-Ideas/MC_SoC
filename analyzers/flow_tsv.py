"""reference-stats/flow_profile.tsv -> feature table (vocal delivery: pace and pitch motion, numbers only).

Columns used: artist, title (only to make opaque ids, never stored) and the numeric measures below.

Version 2 adds the measures that passed a known-manipulation test on real vocal stems (see docs/roadmap.md, "Instrument validation against planted truth").
The first nine are unchanged and kept so older tables still read; three of them are weak (syl_per_voiced_s, pitch_sd_st and pitch_span_st under-report a
planted change, phrase_gap_s moves the wrong way), so prefer the validated ones where a table has them. A table written before version 2 simply lacks them and is still read as version 1, so it stays comparable with earlier results."""
import csv
import features as F

NAME, VERSION, METHOD = "flow-tsv", "2", "flow-profile-tsv"
OWN_ARTIST = "OURS"   # the artist column value for our own tracks in reference-stats/flow_profile.tsv
V2 = {"active_s", "heard_syl_per_active_s", "heard_cover_pct", "pause_share_pct", "pauses_per_min", "npitch_median_st", "npitch_sd_st", "npitch_step_st", "npitch_span_st"}
FEATURES = [
    ("seconds", "s", "track length"),
    ("voiced_pct", "%", "share of frames that are voiced"),
    ("syl_per_voiced_s", "syllables/s", "syllable nuclei per second of voiced time (articulation rate)"),
    ("syl_per_s", "syllables/s", "syllable nuclei per second of the whole track (density)"),
    ("phrase_gap_s", "s", "median silence between phrases"),
    ("pitch_sd_st", "semitones", "median 2 s pitch standard deviation (how much the voice moves)"),
    ("pitch_step_st", "semitones", "median pitch change between neighbouring syllables"),
    ("pitch_span_st", "semitones", "5th-95th percentile of voiced pitch"),
    ("flat_pct", "%", "share of voiced frames within 1 semitone of their window median (monotone delivery)"),
    ("active_s", "s", "time the vocal is within 35 dB of its own loud level"),
    ("heard_syl_per_active_s", "syllables/s", "syllables in the words a speech recogniser hears, per active second (blank when too few words are heard)"),
    ("heard_cover_pct", "%", "share of the active time covered by heard words"),
    ("pause_share_pct", "%", "share of the stem inside pauses of 0.25 s or longer"),
    ("pauses_per_min", "1/min", "pauses of 0.25 s or longer per minute"),
    ("npitch_median_st", "semitones", "median pitch (MIDI scale), neural pitch tracker"),
    ("npitch_sd_st", "semitones", "median 2 s pitch standard deviation, neural pitch tracker"),
    ("npitch_step_st", "semitones", "median pitch change between neighbouring syllables, neural pitch tracker"),
    ("npitch_span_st", "semitones", "5th-95th percentile of voiced pitch, neural pitch tracker"),
]


def read(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["artist"].strip() == OWN_ARTIST:
                continue  # our own tracks are scored against cards, never used to build a reference table (design, decision 14/17)
            vals = {}
            for name, _, _ in FEATURES:
                try:
                    vals[name] = float(r[name])
                except (KeyError, TypeError, ValueError):
                    pass  # a missing or blank measure is left out, never invented
            if vals:
                rows.append({"id": F.opaque(r["artist"], r["title"]), "group": F.opaque(r["artist"], n=8), "values": vals})
    have = {k for r in rows for k in r["values"]}   # declare only what the file holds: a table from before version 2 stays a version 1 table
    feats = [{"name": n, "unit": u, "description": d} for n, u, d in FEATURES if n in have]
    return F.make_table(NAME, VERSION if have & V2 else "1", feats, rows,
                        F.provenance(METHOD, "unspecified", len(rows)))   # a TSV reader cannot know what the measuring tool measured on
