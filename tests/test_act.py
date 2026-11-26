import json, math, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import act

CARD = {"schema_version": 1, "card": "test-voice", "kind": "voice", "n_tracks": 6, "traits": ["pace:fast", "delivery:melodic"],
        "measured": {"heard_syl_per_active_s": {"p10": 4.0, "median": 4.5, "p90": 5.0},
                     "npitch_sd_st": {"p10": 2.0, "median": 2.5, "p90": 3.0}},
        "form_hint": ["spoken-rhyme", "sung-hook"], "thresholds": {}}


def tree():
    d = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "records", d / "records"); shutil.copytree(ROOT / "personas", d / "personas")
    (d / "schema").mkdir()
    (d / "personas" / "test-voice.json").write_text(json.dumps(CARD))
    return d


class Targets(unittest.TestCase):
    def test_bands_come_from_the_card(self):
        t = act.target(CARD, "sung-hook")
        self.assertEqual(t["bands"]["npitch_sd_st"], {"low": 2.0, "mid": 2.5, "high": 3.0})
        self.assertEqual(t["card"], "test-voice"); self.assertEqual(t["form"], "sung-hook")

    def test_card_without_numbers_is_refused(self):
        with self.assertRaises(ValueError): act.target({**CARD, "measured": {}}, "skit")

    def test_beat_card_is_refused(self):
        with self.assertRaises(ValueError): act.target({**CARD, "kind": "beat"}, "skit")


class Compare(unittest.TestCase):
    def setUp(self): self.t = act.target(CARD, "sung-hook")

    def test_inside_below_above_and_distance(self):
        g = act.compare(self.t, {"heard_syl_per_active_s": 4.2, "npitch_sd_st": 3.5})
        a, b = g["measures"]["heard_syl_per_active_s"], g["measures"]["npitch_sd_st"]
        self.assertEqual((a["where"], a["gap"]), ("inside", 0.0))
        self.assertEqual((b["where"], b["gap"]), ("above", 0.5))
        self.assertEqual(g["inside"], 1); self.assertEqual(g["scored"], 2)
        below = act.compare(self.t, {"npitch_sd_st": 1.0})["measures"]["npitch_sd_st"]
        self.assertEqual((below["where"], below["gap"]), ("below", -1.0))

    def test_card_measures_the_engine_left_out_are_named(self):
        g = act.compare(self.t, {"npitch_sd_st": 2.5})
        self.assertEqual(g["missing"], sorted(k for k in self.t["bands"] if k != "npitch_sd_st"))
        self.assertEqual(g["scored"], 1)
        none = act.compare(self.t, {"heard_syl_per_active_s": 4.2, "npitch_sd_st": 2.5, "npitch_span_st": 12.0})
        self.assertEqual(none["missing"], [])

    def test_measure_not_on_the_card_is_ignored_not_scored(self):
        g = act.compare(self.t, {"npitch_sd_st": 2.5, "lufs": -15.0})
        self.assertNotIn("lufs", g["measures"]); self.assertEqual(g["unscored"], ["lufs"])

    def test_non_numbers_are_refused(self):
        for bad in ("fast", None, True, math.nan, math.inf, [4.2]):
            with self.assertRaises(ValueError, msg=repr(bad)): act.compare(self.t, {"npitch_sd_st": bad})

    def test_too_little_material_is_not_scored(self):
        g = act.compare(self.t, {"npitch_sd_st": 2.5}, seconds=30.0)
        self.assertFalse(g["scored"]); self.assertIn("under", g["reason"])


class Run(unittest.TestCase):
    def test_fake_engine_end_to_end_is_generate_only(self):
        d = tree()
        eng = act.FakeEngine({"heard_syl_per_active_s": 4.6, "npitch_sd_st": 2.4}, seconds=90.0)
        rep = act.run(d, "incident-llm-deep-context-corruption", "spoken-rhyme", "test-voice", eng)
        self.assertEqual(rep["status"], "generated"); self.assertEqual(rep["comparison"]["inside"], 2)
        self.assertEqual(rep["engine"], "fake")
        text = json.dumps(rep)
        for hidden in ("signoff", "approved", "memory_ref", "maintainer"): self.assertNotIn(hidden, text)

    def test_unapproved_lesson_cannot_be_acted_on(self):
        with self.assertRaises(ValueError):
            act.run(tree(), "news-clawjacked-localhost-websocket", "spoken-rhyme", "test-voice", act.FakeEngine({"npitch_sd_st": 2.5}, 90.0))

    def test_form_and_card_must_be_in_the_brief(self):
        eng = act.FakeEngine({"npitch_sd_st": 2.5}, 90.0)
        with self.assertRaises(ValueError): act.run(tree(), "incident-llm-deep-context-corruption", "sung-hook", "test-voice", eng)  # form not offered for this lesson
        with self.assertRaises(ValueError): act.run(tree(), "incident-llm-deep-context-corruption", "spoken-rhyme", "no-such-card", eng)

    def test_engine_returning_text_is_refused(self):
        class Leaky(act.Engine):
            name = "leaky"
            def render(self, target): return {"values": {"npitch_sd_st": 2.5}, "seconds": 90.0, "transcript": "some words"}
        with self.assertRaises(ValueError): act.run(tree(), "incident-llm-deep-context-corruption", "spoken-rhyme", "test-voice", Leaky())

    def test_summary_counts_only(self):
        t = act.target(CARD, "sung-hook")
        reps = [{"comparison": act.compare(t, {"npitch_sd_st": v})} for v in (2.5, 3.5, 1.0, 2.2)]
        s = act.summarize(reps)["npitch_sd_st"]
        self.assertEqual((s["inside"], s["below"], s["above"], s["n"]), (2, 1, 1, 4))


CONTRAST = json.loads((ROOT / "contrasts" / "driving-calm.json").read_text())


def rep(values, seconds=90.0):
    t = act.target(CARD, "spoken-rhyme")
    return {"comparison": act.compare(t, values, seconds), "values": values, "seconds": seconds}


class Contrast(unittest.TestCase):
    def test_shipped_contrast_only_scores_what_replicated(self):
        a = act.contrast_measures(CONTRAST)
        self.assertEqual(a, {"heard_syl_per_active_s": "higher"})  # pitch spread was not shown, so it is not a test

    def test_driving_faster_than_calm_agrees(self):
        r = act.contrast(CONTRAST, rep({"heard_syl_per_active_s": 4.9, "npitch_sd_st": 2.0}), rep({"heard_syl_per_active_s": 4.4, "npitch_sd_st": 2.6}))
        m = r["measures"]["heard_syl_per_active_s"]
        self.assertEqual((m["diff"], m["agrees"]), (0.5, True)); self.assertAlmostEqual(m["vs_reference"], 0.5 / 0.315, places=2)
        self.assertEqual(r["not_scored"], {"npitch_sd_st": "not shown in the reference"})

    def test_wrong_direction_disagrees_and_equal_is_not_agreement(self):
        bad = act.contrast(CONTRAST, rep({"heard_syl_per_active_s": 4.2}), rep({"heard_syl_per_active_s": 4.6}))
        self.assertFalse(bad["measures"]["heard_syl_per_active_s"]["agrees"])
        same = act.contrast(CONTRAST, rep({"heard_syl_per_active_s": 4.5}), rep({"heard_syl_per_active_s": 4.5}))
        self.assertFalse(same["measures"]["heard_syl_per_active_s"]["agrees"])

    def test_a_short_render_is_not_compared(self):
        r = act.contrast(CONTRAST, rep({"heard_syl_per_active_s": 4.9}, 30.0), rep({"heard_syl_per_active_s": 4.4}))
        self.assertEqual(r["measures"], {}); self.assertIn("under", r["reason"])

    def test_one_pair_is_not_a_test(self):
        r = act.contrast(CONTRAST, rep({"heard_syl_per_active_s": 4.9}), rep({"heard_syl_per_active_s": 4.4}))
        self.assertEqual(r["pairs"], 1); self.assertIn("one pair", r["note"])

    def test_summary_counts_pairs(self):
        pairs = [act.contrast(CONTRAST, rep({"heard_syl_per_active_s": a}), rep({"heard_syl_per_active_s": b})) for a, b in ((4.9, 4.4), (4.8, 4.5), (4.3, 4.6))]
        s = act.contrast_summary(pairs)["heard_syl_per_active_s"]
        self.assertEqual((s["pairs"], s["agree"]), (3, 2))


if __name__ == "__main__":
    unittest.main()
