import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import persona

def row(a, p, f): return {"artist": a, "title": "t-" + a, "syl_per_voiced_s": p, "flat_pct": f, "pitch_span_st": 12}

class T(unittest.TestCase):
    def rows(self):
        r = [row("ZedOne", 5.0, 50), row("YamTwo", 5.1, 52), row("XavThree", 4.9, 48), row("WolfFour", 5.2, 51),
             row("ZedOne", 2.0, 20), row("YamTwo", 2.1, 22), row("XavThree", 1.9, 18), row("WolfFour", 1.8, 19),
             row("Mid", 3.5, 35), row("Mid", 3.6, 36), row("Mid", 3.4, 34)]
        return [{k: str(v) for k, v in x.items()} for x in r]
    def test_cards_and_no_names(self):
        cards = persona.build(self.rows())
        self.assertEqual({c["card"] for c in cards}, {"rapid-deadpan", "slow-melodic"})
        blob = json.dumps(cards)
        for n in ("ZedOne", "YamTwo", "XavThree", "Mid", "t-"):
            self.assertNotIn(n, blob)
    def test_single_artist_group_is_dropped(self):
        rows = [{k: str(v) for k, v in row("Solo", 5.0 + i / 10, 50).items()} for i in range(4)]
        rows += [{k: str(v) for k, v in row("Other", 2.0, 20).items()} for _ in range(4)]
        self.assertEqual(persona.build(rows), [])
    def new_rows(self, with_old=True):
        r = []
        for g, pace, spread in [(g, p, s) for p, s in ((5.0, 1.0), (2.0, 4.0)) for g in ("a", "b", "c", "d")] + [("m", 3.5, 2.5)] * 3:
            v = {"heard_syl_per_active_s": pace + len(r) / 100, "npitch_sd_st": spread + len(r) / 100, "npitch_span_st": 12.0, "pause_share_pct": 20.0}
            if with_old:   # the older pair points the other way on purpose: a card cut on it would come out with the opposite labels
                v.update(syl_per_voiced_s=7.0 - pace + len(r) / 100, flat_pct=60.0 - 10 * spread + len(r) / 100, pitch_span_st=9.0)
            r.append({"group": g, "values": v})
        return r
    def test_validated_measures_are_preferred_and_the_card_says_which_instrument(self):
        cards = persona.build_rows(self.new_rows(), "voice")
        self.assertEqual({c["card"] for c in cards}, {"rapid-deadpan", "slow-melodic"})   # fast with LOW spread is deadpan
        for c in cards:
            self.assertEqual(set(c["thresholds"]), {"heard_pace_fast_min", "heard_pace_slow_max", "spread_melodic_min", "spread_flat_max"})
            self.assertEqual(set(c["measured"]), {"heard_syl_per_active_s", "npitch_sd_st", "npitch_span_st", "pause_share_pct"})
        fast = next(c for c in cards if c["card"] == "rapid-deadpan")
        self.assertEqual(fast["traits"], ["pace:fast", "delivery:deadpan"])
        self.assertLess(fast["measured"]["npitch_sd_st"]["median"], fast["thresholds"]["spread_flat_max"])
    def test_an_older_table_is_still_cut_on_the_older_pair(self):
        rows = [{"group": r["group"], "values": {k: v for k, v in r["values"].items() if k in ("syl_per_voiced_s", "flat_pct", "pitch_span_st")}} for r in self.new_rows()]
        cards = persona.build_rows(rows, "voice")
        self.assertEqual({c["card"] for c in cards}, {"slow-deadpan", "rapid-melodic"})   # the fixture's older pair points the other way
        for c in cards:
            self.assertEqual(set(c["thresholds"]), {"pace_fast_min", "pace_slow_max", "flat_min", "melodic_max"})
            self.assertEqual(set(c["measured"]), {"syl_per_voiced_s", "flat_pct", "pitch_span_st"})
    def test_rows_without_the_validated_measures_are_left_out_not_filled_from_the_older_ones(self):
        rows = self.new_rows()
        for r in rows[:4]:   # the four fast rows lose the validated pair and keep the older one
            r["values"] = {k: v for k, v in r["values"].items() if k in ("syl_per_voiced_s", "flat_pct", "pitch_span_st")}
        cards = persona.build_rows(rows, "voice")
        self.assertEqual(sum(c["n_tracks"] for c in cards), sum(c["n_tracks"] for c in persona.build_rows(rows[4:], "voice")))
        for c in cards:
            self.assertNotIn("flat_pct", c["measured"]); self.assertNotIn("pace_fast_min", c["thresholds"])
    def test_legacy_tsv_rows_with_the_new_columns_use_them(self):
        rows = [dict({k: str(v) for k, v in r["values"].items()}, artist=r["group"], title="t") for r in self.new_rows()]
        self.assertTrue(all("heard_pace_fast_min" in c["thresholds"] for c in persona.build(rows)))
        self.assertTrue(persona.build(rows))
if __name__ == "__main__":
    unittest.main()


class OwnTracksExcludedTests(unittest.TestCase):
    """Our own tracks (artist OURS in flow_profile.tsv) never shape reference cards."""

    def test_persona_builder_counts_only_reference_rows(self):
        import tempfile, io, contextlib, persona
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        head = "artist\ttitle\tseconds\tvoiced_pct\tsyl_per_voiced_s\tsyl_per_s\tphrase_gap_s\tpitch_sd_st\tpitch_step_st\tpitch_span_st\tflat_pct\n"
        ref = "".join(f"Artist{i % 3}\tT{i}\t200\t70\t{3 + i / 10}\t3\t0.4\t{2 + i / 10}\t1.5\t12\t{30 + i}\n" for i in range(9))
        ours = "OURS\tOwn\t200\t70\t9\t3\t0.4\t9\t1.5\t12\t90\n" * 4
        (d / "flow.tsv").write_text(head + ref + ours)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            persona.main([str(d / "flow.tsv"), "--out", str(d / "cards")])
        self.assertIn("9 tracks measured", out.getvalue())
