import copy, json, re, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import replication as R, exchange as X
from test_exchange import make_crate, prof, UNIVERSE

CLAIM = "claim-0123456789ab"
UP = (prof(3.4, 49.0), prof(5.0, 30.0))      # s1 slower, flatter than s2: pace effect negative, flat effect positive
DOWN = (prof(5.0, 30.0), prof(3.4, 49.0))    # the opposite orientation


def exchange(specs):
    """specs: list of dicts {profiles, counts, claim, universe changes, seed}. Returns a temp exchange directory."""
    d = Path(tempfile.mkdtemp()); (d / "crates").mkdir()
    for n, sp in enumerate(specs):
        cid = f"crate-{n:012x}"
        c = make_crate(list(sp.get("profiles", UP)), counts=sp.get("counts", [3, 4]), strength=sp.get("strength", 1.0), cid=cid, hash_seed=sp.get("seed", n))
        if sp.get("claim", CLAIM): c["claim"] = sp.get("claim", CLAIM)
        c["universe"].update(sp.get("universe", {}))
        (d / "crates" / f"{cid}.json").write_text(json.dumps(c))
    return d


def feature(out, f="syl_per_voiced_s", group=0):
    return out["groups"][group]["features"][f]


class T(unittest.TestCase):
    def test_sign_test_known_values(self):
        self.assertAlmostEqual(R.sign_test_p(10, 0), 2 * 0.5 ** 10)
        self.assertAlmostEqual(R.sign_test_p(5, 5), 1.0)
        self.assertAlmostEqual(R.sign_test_p(4, 0), 0.125)
        self.assertEqual(R.sign_test_p(0, 0), 1.0)

    def test_ten_tiny_crates_none_proven_alone_replicate_together(self):
        out = R.summarize(exchange([{} for _ in range(10)]))
        g = out["groups"][0]
        self.assertEqual((g["crates"], g["supported_crates"]), (10, 0))        # 3 against 4 can never be supported on its own
        for f, expected_up in (("syl_per_voiced_s", 0), ("flat_pct", 10)):
            r = g["features"][f]
            self.assertEqual((r["verdict"], r["s1_higher"]), ("replicated", expected_up))
            self.assertAlmostEqual(r["sign_test_p"], 2 * 0.5 ** 10, places=5)
            self.assertLess(r["combined_p"], 1e-6); self.assertEqual(r["agreement"], 1.0)
        self.assertAlmostEqual(feature(out, "flat_pct")["combined_effect"], 1.0); self.assertAlmostEqual(feature(out)["combined_effect"], -1.0)

    def test_fewer_than_three_crates_is_insufficient(self):
        out = R.summarize(exchange([{}, {}]))
        self.assertEqual(feature(out)["verdict"], "insufficient")

    def test_four_crates_leaning_the_same_way_is_only_suggestive(self):
        r = feature(R.summarize(exchange([{} for _ in range(4)])), "flat_pct")
        self.assertAlmostEqual(r["sign_test_p"], 0.125)            # 4 of 4 cannot reach the shared 5% level on the sign test
        self.assertEqual(r["verdict"], "suggestive")

    def test_mixed_directions_are_inconsistent(self):
        out = R.summarize(exchange([{"profiles": UP} for _ in range(5)] + [{"profiles": DOWN} for _ in range(5)]))
        for f in ("syl_per_voiced_s", "flat_pct"):
            r = feature(out, f)
            self.assertEqual((r["verdict"], r["s1_higher"], r["s1_lower"]), ("inconsistent", 5 if f == "flat_pct" else 5, 5))
            self.assertAlmostEqual(r["combined_effect"], 0.0)
            self.assertGreater(r["heterogeneity"], 0.9)

    def test_incompatible_measurements_are_never_combined(self):
        out = R.summarize(exchange([{"universe": {"analyzer_version": "1"}} for _ in range(5)] + [{"universe": {"analyzer_version": "2"}} for _ in range(5)]))
        self.assertEqual(len(out["groups"]), 2)                    # two groups of five, not one of ten
        self.assertEqual({g["crates"] for g in out["groups"]}, {5})
        out = R.summarize(exchange([{"universe": {"measured_on": "own"}} for _ in range(3)] + [{} for _ in range(3)]))
        self.assertEqual(len(out["groups"]), 2)
        out = R.summarize(exchange([{"claim": "claim-aaaaaaaaaaaa"} for _ in range(3)] + [{"claim": "claim-bbbbbbbbbbbb"} for _ in range(3)]))
        self.assertEqual(len(out["groups"]), 2)                    # different claims are different questions

    def test_identical_crates_count_once(self):
        out = R.summarize(exchange([{"seed": "same"} for _ in range(6)] + [{"seed": 1}, {"seed": 2}]))
        self.assertEqual(out["groups"][0]["crates"], 3); self.assertEqual(out["left_out"]["duplicate"], 5)

    def test_crates_without_a_claim_casts_and_invalid_crates_are_left_out(self):
        d = exchange([{} for _ in range(4)] + [{"claim": None} for _ in range(2)])
        cast = make_crate([prof(3.0, 55.0), prof(3.8, 40.0), prof(4.6, 28.0)], kind="cast", cid="crate-00000000ffff", hash_seed="c")
        (d / "crates" / "crate-00000000ffff.json").write_text(json.dumps(cast))
        (d / "crates" / "crate-00000000eeee.json").write_text("{not json")
        out = R.summarize(d)
        self.assertEqual(out["groups"][0]["crates"], 4)
        self.assertEqual({k: v for k, v in out["left_out"].items() if v}, {"no_claim": 2, "not_two_sided": 1, "invalid": 1})

    def test_output_is_numbers_and_ids_only(self):
        blob = json.dumps(R.summarize(exchange([{} for _ in range(5)])))
        self.assertFalse(re.search(r"[0-9a-f]{40,}", blob))        # no content hash
        self.assertNotIn("crate-", blob)                           # no crate ids either

    def test_crates_with_no_difference_are_not_counted_for_either_direction(self):
        same = (prof(4.0, 40.0), prof(4.0, 40.0))
        r = feature(R.summarize(exchange([{} for _ in range(4)] + [{"profiles": same} for _ in range(3)])), "flat_pct")
        self.assertEqual((r["crates"], r["s1_higher"], r["s1_lower"], r["agreement"]), (7, 4, 0, 1.0))

    def test_mixed_directions_cancel_in_the_combined_statistic(self):
        r = feature(R.summarize(exchange([{"profiles": UP} for _ in range(5)] + [{"profiles": DOWN} for _ in range(5)])), "flat_pct")
        self.assertAlmostEqual(r["combined_z"], 0.0, places=6); self.assertGreater(r["combined_p"], 0.99)

    def test_the_combined_effect_is_weighted_by_crate_size(self):
        big = {"counts": [100, 100], "strength": 0.2}
        r = feature(R.summarize(exchange([big] + [{} for _ in range(3)])), "flat_pct")      # one large weak crate, three tiny perfect ones
        self.assertLess(r["combined_effect"], 0.4)                                          # unweighted it would be 0.8

    def test_three_quarters_agreement_is_not_enough(self):
        r = feature(R.summarize(exchange([{"profiles": UP} for _ in range(12)] + [{"profiles": DOWN} for _ in range(4)])), "flat_pct")
        self.assertEqual(r["agreement"], 0.75)
        self.assertLess(r["combined_p"], 0.001)                    # strong on the combined statistic, but the crates do not agree enough
        self.assertEqual(r["verdict"], "no-clear-pattern")

    def test_the_shared_5_percent_level_needs_seven_agreeing_crates_with_two_features(self):
        six = feature(R.summarize(exchange([{} for _ in range(6)])), "flat_pct")
        seven = feature(R.summarize(exchange([{} for _ in range(7)])), "flat_pct")
        self.assertAlmostEqual(six["sign_test_p"], 0.03125); self.assertEqual(six["verdict"], "suggestive")     # beats 0.05 but not 0.05 / 2
        self.assertAlmostEqual(seven["sign_test_p"], 0.015625); self.assertEqual(seven["verdict"], "replicated")

    def test_cli(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(R.main(["summary", str(exchange([{} for _ in range(3)]))]), 0)
        self.assertEqual(json.loads(buf.getvalue())["groups"][0]["crates"], 3)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main([]), 2)

if __name__ == "__main__":
    unittest.main()
