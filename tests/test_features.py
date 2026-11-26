import copy, csv, json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import features as F, persona
from analyzers import flow_tsv, rhythm_tsv

ARTISTS = ["Zed One", "Yam Two", "Xav Three", "Wolf Four"]


def write_tsv(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


def flow_rows():
    out, n = [], 0
    for a in ARTISTS:
        for pace, flat in ((5.0, 50), (2.0, 20), (3.5, 35)):  # fast+flat, slow+melodic, middle
            n += 1
            out.append([a, f"Secret Title {n}", 200, 70, pace + n / 100, 3.0, 0.4, 2.0, 1.5, 12.0, flat + n / 100])
    return out


FLOW_HEADER = ["artist", "title", "seconds", "voiced_pct", "syl_per_voiced_s", "syl_per_s", "phrase_gap_s",
               "pitch_sd_st", "pitch_step_st", "pitch_span_st", "flat_pct"]
RHYTHM_HEADER = ["role", "artist", "title", "seconds", "bpm", "conf", "swing", "kick16", "snare16", "hat16",
                 "lufs", "lra", "balance_db", "peaky"]


def rhythm_rows():
    out, n = [], 0
    for a in ARTISTS:
        for bpm, swing in ((120, 0.60), (70, 0.46), (95, 0.50)):
            n += 1
            out.append(["core", a, f"Hidden Tune {n}", 180, bpm + n / 10, 0.9, swing + n / 1000, "7365343443933565",
                        "0000100000001000", "4343434343434343", -9.0, 6.0, "-7 0 -3 -11 -25", 12.0])
    return out


class T(unittest.TestCase):
    def tables(self):
        d = Path(tempfile.mkdtemp())
        write_tsv(d / "flow.tsv", FLOW_HEADER, flow_rows())
        write_tsv(d / "rhythm.tsv", RHYTHM_HEADER, rhythm_rows())
        return d, flow_tsv.read(d / "flow.tsv"), rhythm_tsv.read(d / "rhythm.tsv")

    def test_our_own_tracks_never_enter_a_reference_table(self):
        d = Path(tempfile.mkdtemp())
        ours = ["OURS", "Our Own Title", 200, 70, 4.0, 3.0, 0.4, 2.0, 1.5, 12.0, 30.0]
        write_tsv(d / "flow.tsv", FLOW_HEADER, flow_rows()[:3] + [ours])
        t = flow_tsv.read(d / "flow.tsv")
        self.assertEqual(len(t["rows"]), 3)
        self.assertEqual(t["provenance"]["n_tracks"], 3)
        self.assertNotIn(F.opaque("OURS", "Our Own Title"), [r["id"] for r in t["rows"]])

    def test_flow_reader_takes_the_validated_measures_and_leaves_blanks_out(self):
        d = Path(tempfile.mkdtemp()); new = ["active_s", "heard_syl_per_active_s", "heard_cover_pct", "pause_share_pct", "npitch_sd_st"]
        rows = [r + [55.0, 4.2, 90, 6.5, 2.1] for r in flow_rows()[:2]] + [flow_rows()[2] + [40.0, "", 12, 30.0, ""]]   # last: too few words heard, no pitch tracker
        write_tsv(d / "flow.tsv", FLOW_HEADER + new, rows)
        t = flow_tsv.read(d / "flow.tsv"); self.assertEqual(F.validate(t), [])
        self.assertEqual(t["analyzer_version"], "2")
        self.assertEqual(t["rows"][0]["values"]["heard_syl_per_active_s"], 4.2); self.assertEqual(t["rows"][0]["values"]["npitch_sd_st"], 2.1)
        self.assertNotIn("heard_syl_per_active_s", t["rows"][2]["values"]); self.assertNotIn("npitch_sd_st", t["rows"][2]["values"])
        self.assertEqual(t["rows"][2]["values"]["pause_share_pct"], 30.0); self.assertNotIn("pauses_per_min", t["rows"][0]["values"])   # column absent from the file
        self.assertNotIn("pauses_per_min", [f["name"] for f in t["features"]])
        old = self.tables()[1]; self.assertEqual(old["analyzer_version"], "1")   # a table from before version 2 is still a version 1 table
        self.assertNotIn("active_s", [f["name"] for f in old["features"]]); self.assertNotIn("Secret", json.dumps(t))

    def test_ids_keep_non_latin_names_apart_and_ascii_ids_stable(self):
        # ASCII ids must not change: pinned values from before the fix
        self.assertEqual(F.opaque("Zed One", "A Title"), "9d51a1de7bbf")
        self.assertEqual(F.opaque("Zed One", n=8), "0132ce08")
        # names outside Latin letters used to normalise to nothing and collide
        self.assertNotEqual(F.opaque("\u0e04\u0e37\u0e19"), F.opaque("\u0e1a\u0e49\u0e32\u0e19"))
        self.assertNotEqual(F.opaque("\u30c9\u30e9\u30b4\u30f3"), F.opaque("\u732b"))
        self.assertNotEqual(F.opaque("\u0e04\u0e37\u0e19"), F.opaque(""))
        # case, width and punctuation variants still match
        self.assertEqual(F.opaque("Caf\u00e9  Tacvba!"), F.opaque("caf\u00e9 tacvba"))
        self.assertEqual(F.opaque("\uff21\uff22\uff23"), F.opaque("abc"))

    def test_ids_are_stable_and_name_free(self):
        self.assertEqual(F.opaque("Zed One", "A Title"), F.opaque("  zed one ", "a  TITLE!"))
        self.assertNotEqual(F.opaque("Zed One", "A"), F.opaque("Zed One", "B"))
        _, flow, rhythm = self.tables()
        blob = json.dumps(flow) + json.dumps(rhythm)
        for n in ARTISTS + ["Secret", "Hidden", "Zed", "Title"]:
            self.assertNotIn(n, blob)

    def test_adapters_make_valid_tables(self):
        _, flow, rhythm = self.tables()
        self.assertEqual(F.validate(flow), [])
        self.assertEqual(F.validate(rhythm), [])
        self.assertEqual(len(flow["rows"]), 12)
        self.assertEqual(len({r["group"] for r in flow["rows"]}), 4)

    def test_adapter_skips_non_numeric_cells_and_declares_only_what_it_has(self):
        _, _, rhythm = self.tables()
        names = {f["name"] for f in rhythm["features"]}
        self.assertNotIn("balance_db", names)  # five numbers in one cell: not read
        self.assertNotIn("kick16", names)
        for r in rhythm["rows"]:
            for v in r["values"].values():
                self.assertIsInstance(v, float)

    def test_validate_refuses_vectors_embeddings_and_names(self):
        _, flow, _ = self.tables()
        t = copy.deepcopy(flow); t["rows"][0]["values"]["pitch_sd_st"] = [1.0, 2.0]
        self.assertTrue(any("finite number" in e for e in F.validate(t)))
        t = copy.deepcopy(flow); t["rows"][0]["values"]["pitch_sd_st"] = "high"
        self.assertTrue(any("finite number" in e for e in F.validate(t)))
        t = copy.deepcopy(flow); t["rows"][0]["values"]["pitch_sd_st"] = float("nan")
        self.assertTrue(any("finite number" in e for e in F.validate(t)))
        for bad in ("speaker_embedding", "voice_vector", "xvector_1", "voiceprint"):
            t = copy.deepcopy(flow); t["features"][0]["name"] = bad
            self.assertTrue(any("never stored" in e for e in F.validate(t)), bad)
        t = copy.deepcopy(flow); t["rows"][0]["id"] = "Zed One"
        self.assertTrue(any("hex hash" in e for e in F.validate(t)))
        t = copy.deepcopy(flow); t["rows"][1]["id"] = t["rows"][0]["id"]
        self.assertTrue(any("repeated" in e for e in F.validate(t)))

    def test_declared_but_empty_feature_is_an_error(self):
        _, flow, _ = self.tables()
        t = copy.deepcopy(flow)
        t["features"].append({"name": "ghost", "unit": "x", "description": "never measured"})
        self.assertTrue(any("ghost" in e and "no row" in e for e in F.validate(t)))

    def test_coverage_counts_only(self):
        _, flow, rhythm = self.tables()
        c = F.coverage([flow, rhythm])
        self.assertEqual([t["rows"] for t in c["tables"]], [12, 12])
        self.assertEqual(c["shared_rows"]["flow-tsv + rhythm-tsv"], 0)  # different titles
        self.assertEqual(c["shared_groups"]["flow-tsv + rhythm-tsv"], 4)  # same four artists
        self.assertNotIn("Zed", json.dumps(c))

    def test_voice_cards_same_from_table_and_from_legacy_rows(self):
        d, flow, _ = self.tables()
        legacy = persona.build([{k: str(v) for k, v in zip(FLOW_HEADER, r)} for r in flow_rows()])
        viatable = persona.build_table(flow, "voice")
        self.assertEqual(legacy, viatable)
        self.assertEqual({c["card"] for c in viatable}, {"rapid-deadpan", "slow-melodic"})
        self.assertTrue(all(c["kind"] == "voice" for c in viatable))

    def test_beat_cards_have_ranges_and_no_names_or_ids(self):
        _, flow, rhythm = self.tables()
        cards = persona.build_table(rhythm, "beat")
        self.assertEqual({c["card"] for c in cards}, {"fast-swung", "slow-straight"})
        for c in cards:
            self.assertEqual(c["kind"], "beat")
            self.assertNotIn("form_hint", c)
            self.assertGreaterEqual(c["n_tracks"], 3)
            self.assertEqual(set(c["measured"]), {"bpm", "swing", "lufs", "lra"})
        blob = json.dumps(cards)
        for n in ARTISTS + ["Hidden", "Zed"] + [r["id"] for r in rhythm["rows"]] + [r["group"] for r in rhythm["rows"]]:
            self.assertNotIn(n, blob)

    def test_card_needs_two_groups(self):
        rows = [{"group": "g1", "values": {"bpm": 120.0 + i, "swing": 0.60}} for i in range(4)]
        rows += [{"group": "g1", "values": {"bpm": 70.0 + i, "swing": 0.46}} for i in range(4)]
        self.assertEqual(persona.build_rows(rows, "beat"), [])

    def test_cli_end_to_end_in_isolated_mode(self):
        d = Path(tempfile.mkdtemp())
        write_tsv(d / "rhythm.tsv", RHYTHM_HEADER, rhythm_rows())
        r = subprocess.run([sys.executable, "-I", str(ROOT / "features.py"), "build", "rhythm-tsv",
                            str(d / "rhythm.tsv"), "--out", str(d / "t" / "rhythm.json")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, "-I", str(ROOT / "persona.py"), "build", str(d / "t" / "rhythm.json"),
                            "--kind", "beat", "--out", str(d / "cards")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in (d / "cards").iterdir()), ["fast-swung.json", "slow-straight.json"])
        r = subprocess.run([sys.executable, "-I", str(ROOT / "features.py"), "coverage", str(d / "t" / "rhythm.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Hidden", r.stdout)

class InstrumentsTests(unittest.TestCase):
    def tbl(self, instruments):
        rows = [{"id": "ab12cd34ef56", "group": "00000001", "values": {"pace": 1.0}}]
        return F.make_table("flow-tsv", "1", [{"name": "pace", "unit": "ratio", "description": "x"}], rows,
                            F.provenance("flow-profile-tsv", "reference", 1, instruments=instruments))

    def test_instrument_versions_are_optional_and_checked_by_shape(self):
        self.assertEqual(F.validate(self.tbl(None)), [])
        self.assertEqual(F.validate(self.tbl({"speech-model": "distil-small.en", "tagger-weights": "dd3b4043a87d"})), [])
        for bad in ({"Speech Model": "x"}, {"speech-model": ""}, {"speech-model": "a b"}, {"speech-model": "x" * 41}, ["x"],
                    {f"i{n}": "1" for n in range(9)}):
            self.assertTrue(F.validate(self.tbl(bad)), bad)



if __name__ == "__main__":
    unittest.main()
