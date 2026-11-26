import copy, json, random, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import crate_builder as C, exchange as X, features as F

FEATS = [{"name": "pace", "unit": "syl/s", "description": "d"}, {"name": "flat", "unit": "%", "description": "d"}]


def table(sides, seed=7, per_side=10, noise=0.3, distinct=False):
    """sides: list of (pace centre, flat centre). Returns (feature table, assignment). Artist groups repeat across sides on purpose."""
    rnd = random.Random(seed)
    rows, assign = [], {}
    for n, (pc, fc) in enumerate(sides, 1):
        ids = []
        for i in range(per_side):
            rid = f"{n:02x}{i:02x}" * 3
            rows.append({"id": rid, "group": f"{n:04x}{i:04x}" if distinct else f"{(i % 4) + (1 if n == 1 else 0):08x}",     # side 1 shares groups 1-3 with the others, plus group 4
                         "values": {"pace": pc + rnd.uniform(-noise, noise), "flat": fc + rnd.uniform(-noise * 8, noise * 8)}})
            ids.append(rid)
        assign[f"s{n}"] = ids
    return F.make_table("flow-tsv", "1", FEATS, rows, F.provenance("flow-profile-tsv", "reference", len(rows))), assign


class T(unittest.TestCase):
    def build(self, sides, **kw):
        t, a = table(sides)
        return C.build(t, a, "delivery-reference", **kw), t, a

    def test_two_sides_pass_the_exchange_checker_and_have_the_right_signs(self):
        c, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)])
        self.assertEqual(X.check_crate(c), [])
        e = c["relationship"]["pairs"][0]["features"]
        self.assertGreater(e["flat"]["effect"], 0.9); self.assertLess(e["pace"]["effect"], -0.9)        # s1 flatter, slower: first side higher on flat only
        self.assertLess(e["pace"]["overlap"], 0.1)
        self.assertEqual(c["relationship"]["kind"], "contrast")
        self.assertGreater(c["relationship"]["separability"], 0.95)

    def test_the_bundle_says_which_way_a_positive_effect_points(self):
        c, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)])
        self.assertEqual(c["relationship"]["orientation"], "positive_means_first_side_higher")

    def test_instrument_versions_flow_from_the_table_into_the_bundle(self):
        t, a = table([(3.0, 55.0), (5.0, 25.0)])
        t["provenance"]["instruments"] = {"speech-model": "distil-small.en"}
        c = C.build(t, a, "delivery-reference")
        self.assertEqual(c["universe"]["instruments"], {"speech-model": "distil-small.en"})
        self.assertEqual(X.check_crate(c), [])
        c2, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)])
        self.assertNotIn("instruments", c2["universe"])

    def test_a_five_persona_cast_is_one_crate(self):
        c, _, _ = self.build([(3.0, 55.0), (3.8, 40.0), (4.6, 28.0), (5.4, 48.0), (6.2, 20.0)])
        self.assertEqual(X.check_crate(c), [])
        self.assertEqual((len(c["sides"]), len(c["relationship"]["pairs"]), c["relationship"]["kind"]), (5, 10, "cast"))
        self.assertGreater(c["relationship"]["distinctness"], 0.9)

    def test_close_personas_lower_distinctness(self):
        far, _, _ = self.build([(3.0, 55.0), (6.0, 20.0)])
        near, _, _ = self.build([(3.0, 55.0), (3.1, 54.0), (6.0, 20.0)])      # s1 and s2 are nearly the same persona
        self.assertLess(near["relationship"]["distinctness"], far["relationship"]["distinctness"])

    def test_features_option_restricts_the_profile(self):
        c, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)], only_features=["flat"])
        self.assertEqual(list(c["sides"]["s1"]["profile"]), ["flat"])
        self.assertEqual(c["relationship"]["carriers"], ["flat"])
        t, a = table([(3.0, 55.0), (5.0, 25.0)])
        with self.assertRaises(C.BuildError): C.build(t, a, "delivery-reference", only_features=["nope"])
        with self.assertRaises(C.BuildError): C.build(t, a, "delivery-reference", only_features=[])

    def test_bundle_holds_no_row_id_group_or_name(self):
        c, t, _ = self.build([(3.0, 55.0), (5.0, 25.0)])
        blob = json.dumps(c)
        for r in t["rows"]:
            self.assertNotIn(r["id"], blob); self.assertNotIn(r["group"], blob)

    def test_shared_groups_counted(self):
        c, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)])
        self.assertEqual(c["confounds"]["shared_groups"], 3)      # groups 1-3 appear on both sides; group 4 only on s1

    def test_deterministic_id_and_hashes(self):
        a, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)]); b, _, _ = self.build([(3.0, 55.0), (5.0, 25.0)])
        self.assertEqual(a, b)
        other, _, _ = self.build([(3.0, 55.0), (5.0, 25.5)])
        self.assertNotEqual(a["id"], other["id"])

    def test_confidence_follows_size_and_membership(self):
        t10, a10 = table([(3.0, 55.0), (5.0, 25.0)], distinct=True)
        self.assertEqual(C.build(t10, a10, "delivery-reference")["relationship"]["confidence"], "medium")   # 10 per side
        self.assertEqual(C.build(t10, a10, "delivery-reference", membership="assumed")["relationship"]["confidence"], "low")
        t, a = table([(3.0, 55.0), (5.0, 25.0)], per_side=5)
        self.assertEqual(C.build(t, a, "delivery-reference")["relationship"]["confidence"], "low")           # fewer than 8 per side

    def test_refusals(self):
        t, a = table([(3.0, 55.0), (5.0, 25.0)])
        def err(table_=t, assign=a, **kw):
            with self.assertRaises(C.BuildError) as cm: C.build(table_, assign, "delivery-reference", **kw)
            return str(cm.exception)
        self.assertIn("at least", err(assign={"s1": a["s1"][:1], "s2": a["s2"]}))                            # a side needs 2 tracks
        self.assertIn("both", err(assign={"s1": a["s1"], "s2": a["s2"] + a["s1"][:1]}))                       # a row on two sides
        self.assertIn("not in the table", err(assign={"s1": a["s1"], "s2": ["ffffffffffff"] + a["s2"][1:]}))
        self.assertIn("named s1", err(assign={"s1": a["s1"]}))
        self.assertIn("named s1", err(assign={"s1": a["s1"], "s3": a["s2"]}))
        bad = copy.deepcopy(t); del bad["provenance"]
        self.assertIn("provenance", err(table_=bad))

    def test_identical_sides_rarely_come_out_supported_even_with_many_personas(self):
        """Measured: at most a few percent of identical-sided crates are 'supported'; a loose bound here so the test is robust."""
        for centres in ([(4.0, 40.0)] * 2, [(4.0, 40.0)] * 5):
            false = 0
            for seed in range(120):
                t, a = table(centres, seed=seed, per_side=10, distinct=True)
                false += C.build(t, a, "delivery-reference")["relationship"]["evidence"] == "supported"
            self.assertLessEqual(false / 120, 0.08, centres)

    def test_identical_sides_with_artist_effects_rarely_come_out_supported(self):
        """Each artist has its own habit (a shift shared by all its tracks), the two sides are drawn from the same population. Tests on tracks
        would call this a finding most of the time; the artist-level test keeps the false rate at the nominal few percent."""
        def crate(seed, artists=15, per_artist=6):
            rnd, rows, assign = random.Random(seed), [], {"s1": [], "s2": []}
            for n in (1, 2):
                for art in range(artists):
                    shift = rnd.gauss(0, 1.0)
                    for i in range(per_artist):
                        rid = f"{n:02x}{art:02x}{i:02x}" * 2
                        rows.append({"id": rid, "group": f"{n:04x}{art:04x}", "values": {"pace": 4.0 + shift + rnd.gauss(0, 0.1), "flat": 40 + rnd.gauss(0, 1)}})
                        assign[f"s{n}"].append(rid)
            return F.make_table("flow-tsv", "1", FEATS, rows, F.provenance("flow-profile-tsv", "reference", len(rows))), assign
        false = naive = 0
        for seed in range(120):
            t, a = crate(seed)
            false += C.build(t, a, "delivery-reference")["relationship"]["evidence"] == "supported"
            e = C.rank_biserial([r["values"]["pace"] for r in t["rows"] if r["id"] in a["s1"]], [r["values"]["pace"] for r in t["rows"] if r["id"] in a["s2"]])
            naive += abs(e) >= 0.2 and X.mw_pvalue(e, len(a["s1"]), len(a["s2"])) <= X.ALPHA / 2
        self.assertLessEqual(false / 120, 0.08)
        self.assertGreater(naive / 120, 0.3)          # the track-level test it replaces would have called many of these a finding

    def test_a_modest_real_difference_comes_out_supported(self):
        found = 0
        for seed in range(60):
            t, a = table([(4.0, 40.0), (4.35, 41.0)], seed=seed, per_side=20, distinct=True)
            found += C.build(t, a, "delivery-reference")["relationship"]["evidence"] == "supported"
        self.assertGreaterEqual(found / 60, 0.9)

    def test_tracks_of_one_artist_do_not_count_as_independent(self):
        """40 tracks a side, perfectly separated by an artist-level shift: with 20 artists a side it is supported, with 4 it cannot be."""
        def clustered(artists, seed=1):
            rnd, rows, assign = random.Random(seed), [], {"s1": [], "s2": []}
            for n, centre in ((1, 3.0), (2, 5.0)):
                for i in range(40):
                    art = i % artists
                    rid = f"{n:02x}{i:02x}" * 3
                    rows.append({"id": rid, "group": f"{n:04x}{art:04x}", "values": {"pace": centre + rnd.uniform(-0.3, 0.3), "flat": 40 + rnd.uniform(-1, 1)}})
                    assign[f"s{n}"].append(rid)
            return F.make_table("flow-tsv", "1", FEATS, rows, F.provenance("flow-profile-tsv", "reference", len(rows))), assign
        many = C.build(*clustered(20), "delivery-reference")["relationship"]
        few = C.build(*clustered(4), "delivery-reference")["relationship"]
        self.assertEqual(many["evidence"], "supported"); self.assertIn("pace", many["carriers"])
        self.assertEqual(few["evidence"], "exploratory"); self.assertEqual(few["carriers"], [])
        self.assertGreater(few["pairs"][0]["features"]["pace"]["p"], 0.02)                       # the track-level p would be about 1e-14
        self.assertAlmostEqual(few["pairs"][0]["features"]["pace"]["effect"], -1.0, places=2)    # the descriptive track-level effect is unchanged

    def test_a_tiny_crate_is_accepted_as_exploratory(self):
        """Three tracks against four, perfectly separated: a hypothesis (exact p = 2/35), never a finding on its own."""
        t, a = table([(3.0, 55.0), (6.0, 20.0)], per_side=4)
        a["s1"] = a["s1"][:3]
        c = C.build(t, a, "delivery-reference")
        self.assertEqual(X.check_crate(c), [])
        r = c["relationship"]
        self.assertEqual((r["evidence"], r["confidence"], r["carriers"], r["leaning"]), ("exploratory", "low", [], ["flat", "pace"]))
        self.assertAlmostEqual(r["pairs"][0]["features"]["pace"]["p"], 2 / 35, places=4)

    def test_identical_sides_give_an_exploratory_crate_with_nothing_leaning(self):
        t, a = table([(4.0, 40.0), (4.0, 40.0)], seed=3, per_side=10)
        r = C.build(t, a, "delivery-reference")["relationship"]
        self.assertEqual(r["evidence"], "exploratory"); self.assertEqual(r["leaning"], [])

    def test_only_features_measured_for_every_track_are_profiled(self):
        t, a = table([(3.0, 55.0), (6.0, 20.0)])
        del t["rows"][0]["values"]["flat"]                        # one track lacks 'flat'
        c = C.build(t, a, "delivery-reference")
        self.assertEqual(list(c["sides"]["s1"]["profile"]), ["pace"])
        for r in t["rows"]: r["values"].pop("pace", None); r["values"].pop("flat", None)
        t["rows"][1]["values"]["pace"] = 1.0
        with self.assertRaises(C.BuildError): C.build(t, a, "delivery-reference")

    def test_claims_and_predicates(self):
        t, a = table([(3.0, 55.0), (5.0, 25.0)])
        self.assertEqual(C.build(t, a, "delivery-reference", claim="claim-0123456789ab")["claim"], "claim-0123456789ab")
        self.assertNotIn("claim", C.build(t, a, "delivery-reference"))                    # unlabelled is normal
        pred = {"atom": "pace:slow"}
        c = C.build(t, a, "delivery-reference", predicate=pred)
        self.assertEqual((c["formed_by"], c["claim"]), ("predicate", X.claim_for_predicate(pred)))
        self.assertEqual(X.check_crate(c), [])
        with self.assertRaises(C.BuildError): C.build(t, a, "delivery-reference", predicate=pred, claim="claim-0123456789ab")
        with self.assertRaises(C.BuildError): C.build(t, a, "delivery-reference", predicate={"atom": "some artist"})
        t3, a3 = table([(3.0, 55.0), (4.5, 40.0), (6.0, 20.0)])
        with self.assertRaises(C.BuildError): C.build(t3, a3, "delivery-reference", claim="claim-0123456789ab")      # a cast cannot carry a claim

    def test_cli_writes_a_checked_bundle(self):
        import io, contextlib
        t, a = table([(3.0, 55.0), (5.0, 25.0)])
        d = Path(tempfile.mkdtemp())
        (d / "t.json").write_text(json.dumps(t)); (d / "a.json").write_text(json.dumps(a))
        out = d / "crates"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(C.main(["build", str(d / "t.json"), "--assign", str(d / "a.json"), "--purpose", "delivery-reference",
                                     "--matched", "loudness,tempo", "--out", str(out)]), 0)
        self.assertEqual(X.check_dir(d / "exchange_missing"), ({}, {"crate": 0, "card": 0, "prescription": 0}))
        (d / "ex").mkdir(); (d / "ex" / "crates").mkdir()
        for p in out.iterdir(): (d / "ex" / "crates" / p.name).write_text(p.read_text())
        self.assertEqual(X.check_dir(d / "ex")[0], {})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(C.main(["build", str(d / "t.json"), "--assign", str(d / "missing.json"), "--purpose", "mixed"]), 1)

if __name__ == "__main__":
    unittest.main()
