import csv, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import features as F, persona, exchange
import analyzers
from analyzers import flow_voices_tsv, flow_tsv

HEADER = ["artist", "title", "voice", "voices_in_track", "voice_active_s", "heard_syl_per_active_s", "npitch_sd_st", "npitch_span_st"]


def voice_rows():
    """Four artists. Each has a fast flat track with a slow melodic second voice on it, and two middle tracks with one voice."""
    out, n = [], 0
    for a in ("Zed One", "Yam Two", "Xav Three", "Wolf Four"):
        n += 1
        out.append([a, f"Secret Title {n}", 1, 2, 120.0, 5.0 + n / 100, 1.0 + n / 100, 9.0])
        out.append([a, f"Secret Title {n}", 2, 2, 75.0, 2.0 + n / 100, 4.0 + n / 100, 20.0])
        out.append([a, f"Other Title {n}", 1, 1, 150.0, 3.5 + n / 100, 2.5 + n / 100, 12.0])
        out.append([a, f"Other Title {n}b", 1, 1, 150.0, 3.4 + n / 100, 2.4 + n / 100, 12.0])
    return out


def read(rows, header=HEADER):
    p = Path(tempfile.mkdtemp()) / "voices.tsv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t"); w.writerow(header); w.writerows(rows)
    return flow_voices_tsv.read(p)


class T(unittest.TestCase):
    def test_one_row_per_voice_with_distinct_ids_and_the_artist_as_group(self):
        t = read(voice_rows()); self.assertEqual(F.validate(t), [])
        self.assertEqual(len(t["rows"]), 16); self.assertEqual(len({r["id"] for r in t["rows"]}), 16); self.assertEqual(len({r["group"] for r in t["rows"]}), 4)
        self.assertEqual(t["provenance"]["unit"], "voice"); self.assertEqual(t["provenance"]["n_tracks"], 16)
        self.assertIn("flow-voices-tsv", analyzers.ANALYZERS)
        blob = json.dumps(t)
        for name in ("Zed", "Secret", "Other Title"):
            self.assertNotIn(name, blob)

    def test_a_voice_with_too_little_material_is_left_out_and_a_blank_spread_is_not_invented(self):
        rows = voice_rows(); rows[1][4] = 59.9; rows[4][6] = ""
        t = read(rows); self.assertEqual(F.validate(t), [])
        self.assertEqual(len(t["rows"]), 15)
        self.assertEqual(sum("npitch_sd_st" not in r["values"] for r in t["rows"]), 1)
        no_len = [r[:4] + r[5:] for r in voice_rows()]   # a file that does not say how much material a voice had is not trusted
        self.assertEqual(read(no_len, HEADER[:4] + HEADER[5:])["rows"], [])

    def test_a_table_says_what_its_rows_are_and_only_known_units_pass(self):
        t = read(voice_rows()); t["provenance"]["unit"] = "speaker"
        self.assertTrue(any("unit" in e for e in F.validate(t)))
        self.assertNotIn("unit", F.provenance("m", "reference", 3))   # tables of tracks are unchanged

    def test_cards_cut_on_voice_rows_split_a_track_with_two_voices_and_say_they_count_voices(self):
        cards = persona.build_table(read(voice_rows()), "voice", basis=True)
        self.assertEqual({c["card"]: c["n_tracks"] for c in cards}, {"rapid-deadpan": 4, "slow-melodic": 4})   # the same four tracks feed both cards
        for c in cards:
            self.assertEqual(c["rows_are"], "voices"); self.assertEqual(c["basis"]["analyzer"], "flow-voices-tsv")
            self.assertEqual(set(c["measured"]), {"heard_syl_per_active_s", "npitch_sd_st", "npitch_span_st"})   # pause share is a whole-track measure
            self.assertEqual(set(c["thresholds"]), {"heard_pace_fast_min", "heard_pace_slow_max", "spread_melodic_min", "spread_flat_max"})

    def test_cards_from_a_table_of_tracks_are_unchanged(self):
        p = Path(tempfile.mkdtemp()) / "flow.tsv"
        with open(p, "w", newline="") as fh:
            w = csv.writer(fh, delimiter="\t"); w.writerow(["artist", "title"] + HEADER[5:]); w.writerows([[r[0], f"{r[1]} {r[2]}"] + r[5:] for r in voice_rows()])
        for c in persona.build_table(flow_tsv.read(p), "voice", basis=True):
            self.assertNotIn("rows_are", c)

    def test_two_voices_of_one_artist_group_still_do_not_make_a_card(self):
        rows = [r for r in voice_rows() if r[0] == "Zed One"] * 1
        rows += [["Zed One", f"More {i}", 1, 2, 60.0, 5.1 + i / 100, 1.1, 9.0] for i in range(3)] + [["Zed One", f"More {i}", 2, 2, 60.0, 2.1 + i / 100, 4.1, 20.0] for i in range(3)]
        self.assertEqual(persona.build_table(read(rows), "voice"), [])

    def test_the_exchange_checker_refuses_a_voice_counted_card_until_bundles_say_what_they_count(self):
        sys.path.insert(0, str(ROOT / "tests")); from test_exchange import CARD
        self.assertEqual(exchange.check_card(dict(CARD)), [])
        self.assertTrue(exchange.check_card(dict(CARD, rows_are="voices")))


if __name__ == "__main__":
    unittest.main()
