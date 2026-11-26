import copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import exchange as X

FEATS = ("syl_per_voiced_s", "flat_pct")
UNIVERSE = {"purpose": "delivery-reference", "measured_on": "reference", "analyzer": "flow-tsv", "analyzer_version": "1", "calibration": "none"}


def prof(pace, flat):
    return {"syl_per_voiced_s": {"p10": pace - 0.4, "median": pace, "p90": pace + 0.4}, "flat_pct": {"p10": flat - 4.0, "median": flat, "p90": flat + 4.0}}


def make_crate(profiles, kind="contrast", membership="chosen", confidence="medium", cid="crate-0123456789ab", counts=None, strength=0.8, hash_seed=None, groups=None, **over):
    """A consistent crate from side profiles: effects follow the medians (magnitude `strength`), and p-values, carriers, leaning and the
    evidence tier are computed with the checker's own functions."""
    ids = [f"s{i + 1}" for i in range(len(profiles))]
    counts = counts or [10 + n for n in range(len(profiles))]
    sides = {i: {"count": counts[n], "groups": (groups[n] if groups else counts[n]), "content_hash": (f"{n + 1:x}" * 64) if hash_seed is None else hashlib.sha256(f"{hash_seed}-{n}".encode()).hexdigest(), "profile": p} for n, (i, p) in enumerate(zip(ids, profiles))}
    pairs, m = [], len(FEATS) * len(ids) * (len(ids) - 1) // 2
    carriers, leaning = set(), set()
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            feats = {}
            for f in FEATS:
                ma, mb = sides[a]["profile"][f]["median"], sides[b]["profile"][f]["median"]
                eff = strength if ma > mb else -strength if ma < mb else 0.0
                pv = round(X.mw_pvalue(eff, sides[a]["groups"], sides[b]["groups"]), 6)
                feats[f] = {"effect": eff, "group_effect": eff, "overlap": 0.1, "p": pv}
                if abs(eff) >= 0.2 and X.mw_pvalue(eff, sides[a]["groups"], sides[b]["groups"]) <= X.ALPHA / m: carriers.add(f)
                elif abs(eff) >= X.LEAN: leaning.add(f)
            pairs.append({"a": a, "b": b, "features": feats})
    leaning -= carriers
    best = [max((abs(v["effect"]) + 1) / 2 for v in p["features"].values()) for p in pairs]
    evidence = "supported" if carriers else "exploratory"
    c = {"schema_version": 1, "kind": "crate", "id": cid, "universe": copy.deepcopy(UNIVERSE), "formed_by": "operator", "sides": sides, "membership": membership,
         "relationship": {"kind": kind, "orientation": X.ORIENTATION, "confidence": confidence if evidence == "supported" else "low", "evidence": evidence,
                          "separability": max(best), "distinctness": min(best), "carriers": sorted(carriers), "leaning": sorted(leaning), "pairs": pairs},
         "confounds": {"shared_groups": 1, "matched_on": ["loudness"]}}
    c.update(over)
    return c


TWO = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)])
CAST = make_crate([prof(3.0, 55.0), prof(3.8, 40.0), prof(4.6, 28.0), prof(5.4, 48.0), prof(6.2, 20.0)], kind="cast")
CRATE = TWO
CARD = {"schema_version": 1, "kind": "card", "card": "slow-deadpan", "voice_or_beat": "voice", "crate": "crate-0123456789ab", "side": "s1", "n_tracks": 9,
        "traits": ["pace:slow", "delivery:deadpan"],
        "measured": {"syl_per_voiced_s": {"p10": 2.6, "median": 3.4, "p90": 3.8}, "flat_pct": {"p10": 46.0, "median": 49.0, "p90": 53.0}},
        "thresholds": {"pace_fast_min": 4.49, "pace_slow_max": 4.06, "flat_min": 45.0, "melodic_max": 37.0},
        "form_hint": ["skit"],
        "basis": {"analyzer": "flow-tsv", "analyzer_version": "1", "method": "flow-profile-tsv", "measured_on": "reference", "calibration": "none"}}
CARD_FILE = "slow-deadpan--crate-0123456789ab-s1.json"
RX = {"schema_version": 1, "kind": "prescription", "id": "rx-0123456789ab", "engine": "ying", "parameter": "hook_speed", "unit": "ratio",
      "value": 1.25, "tested_low": 1.0, "tested_high": 1.5, "flat_low": 1.2, "flat_high": 1.3, "confidence": "medium", "n_raters": 3, "n_trials": 14}
CRATE_FILE = "crate-0123456789ab.json"


def tree(**bundles):
    d = Path(tempfile.mkdtemp())
    for sub, items in (("crates", bundles.get("crates", [])), ("cards", bundles.get("cards", [])), ("prescriptions", bundles.get("rx", []))):
        for name, b in items:
            (d / sub).mkdir(exist_ok=True); (d / sub / name).write_text(json.dumps(b))
    return d


def good():
    return tree(crates=[(CRATE_FILE, CRATE)], cards=[(CARD_FILE, CARD)], rx=[("rx-0123456789ab.json", RX)])


def deep(base, path, value):
    b = copy.deepcopy(base); d = b
    for k in path[:-1]: d = d[k]
    d[path[-1]] = value
    return b


def mut(base, **kw):
    b = copy.deepcopy(base); b.update(kw); return b


class T(unittest.TestCase):
    def bad(self, sub, name, bundle):
        d = good(); (d / sub / name).write_text(json.dumps(bundle))
        problems, _ = X.check_dir(d); return problems.get(f"{sub}/{name}", [])

    def crate_bad(self, bundle):
        return self.bad("crates", CRATE_FILE, bundle)

    def test_a_clean_exchange_passes(self):
        problems, counts = X.check_dir(good())
        self.assertEqual(problems, {}); self.assertEqual(counts, {"crate": 1, "card": 1, "prescription": 1})

    def test_empty_exchange_is_fine(self):
        self.assertEqual(X.check_dir(tempfile.mkdtemp()), ({}, {"crate": 0, "card": 0, "prescription": 0}))

    def test_a_cast_of_five_personas_in_one_crate_passes(self):
        self.assertEqual(self.crate_bad(CAST), [])
        self.assertEqual(len(CAST["relationship"]["pairs"]), 10)    # 5 choose 2

    def test_side_count_and_names(self):
        one = copy.deepcopy(TWO); del one["sides"]["s2"]
        self.assertTrue(self.crate_bad(one))
        nine = make_crate([prof(3.0 + n * 0.3, 50.0 - n * 3) for n in range(9)], kind="cast")
        self.assertTrue(self.crate_bad(nine))
        renamed = copy.deepcopy(TWO); renamed["sides"]["Some Artist"] = renamed["sides"].pop("s2")
        self.assertTrue(self.crate_bad(renamed))
        gap = copy.deepcopy(TWO)                                  # s1 and s3, with the pairs renamed to match: only the naming rule can refuse it
        gap["sides"]["s3"] = gap["sides"].pop("s2")
        for p in gap["relationship"]["pairs"]: p["b"] = "s3"
        self.assertTrue(any("named s1, s2" in e for e in self.crate_bad(gap)))

    def test_pairs_must_cover_every_pair_once(self):
        missing = copy.deepcopy(CAST); missing["relationship"]["pairs"].pop()
        self.assertTrue(self.crate_bad(missing))
        dup = copy.deepcopy(CAST); dup["relationship"]["pairs"].append(copy.deepcopy(dup["relationship"]["pairs"][0]))
        self.assertTrue(self.crate_bad(dup))
        backwards = copy.deepcopy(CAST); p = backwards["relationship"]["pairs"][0]; p["a"], p["b"] = p["b"], p["a"]
        self.assertTrue(self.crate_bad(backwards))

    def test_orientation_must_be_stated_and_must_be_the_one_the_checker_assumes(self):
        self.assertEqual(TWO["relationship"]["orientation"], "positive_means_first_side_higher")
        missing = copy.deepcopy(TWO); del missing["relationship"]["orientation"]
        self.assertTrue(any("orientation" in e for e in self.crate_bad(missing)))
        flipped = deep(TWO, ("relationship", "orientation"), "positive_means_second_side_higher")
        self.assertTrue(any("orientation" in e for e in self.crate_bad(flipped)))

    def test_instruments_in_the_universe_are_optional_and_checked_by_shape(self):
        self.assertEqual(self.crate_bad(deep(TWO, ("universe", "instruments"), {"speech-model": "distil-small.en"})), [])
        self.assertTrue(any("instruments" in e for e in self.crate_bad(deep(TWO, ("universe", "instruments"), {"Speech Model": "x"}))))
        self.assertTrue(any("instruments" in e for e in self.crate_bad(deep(TWO, ("universe", "instruments"), "distil"))))

    def test_kind_must_fit_the_number_of_sides(self):
        self.assertTrue(self.crate_bad(deep(CAST, ("relationship", "kind"), "contrast")))
        self.assertTrue(self.crate_bad(deep(TWO, ("relationship", "kind"), "cast")))
        self.assertEqual(self.crate_bad(deep(TWO, ("relationship", "kind"), "nested")), [])

    def test_ordered_needs_a_monotone_feature(self):
        mono = make_crate([prof(3.0, 40.0), prof(4.0, 35.0), prof(5.0, 30.0)], kind="ordered")
        self.assertEqual(self.crate_bad(mono), [])
        zig = make_crate([prof(3.0, 40.0), prof(5.0, 45.0), prof(4.0, 30.0)], kind="ordered")
        self.assertTrue(any("ordered" in e for e in self.crate_bad(zig)))

    def test_extra_keys_and_free_text_refused(self):
        self.assertTrue(self.crate_bad(mut(CRATE, note="my favourite rapper")))
        self.assertTrue(self.bad("cards", CARD_FILE, mut(CARD, title="A Name")))
        self.assertTrue(self.bad("prescriptions", "rx-0123456789ab.json", mut(RX, comment="x")))

    def test_names_cannot_hide_in_enum_fields(self):
        self.assertTrue(self.crate_bad(deep(CRATE, ("universe", "purpose"), "some artist name")))
        self.assertTrue(self.bad("cards", CARD_FILE, mut(CARD, card="some-artist")))
        self.assertTrue(self.bad("prescriptions", "rx-0123456789ab.json", mut(RX, parameter="Some Name")))
        self.assertTrue(self.bad("cards", CARD_FILE, mut(CARD, traits=["pace:slow", "delivery:Some Name"])))

    def test_thresholds_and_ranges_must_be_numbers_in_order(self):
        c = copy.deepcopy(CARD); c["measured"]["flat_pct"] = {"p10": 60.0, "median": 49.0, "p90": 53.0}
        self.assertTrue(self.bad("cards", CARD_FILE, c))
        c = copy.deepcopy(CARD); c["thresholds"]["flat_min"] = "high"
        self.assertTrue(self.bad("cards", CARD_FILE, c))
        c = copy.deepcopy(CARD); c["thresholds"]["flat_min"] = float("nan")
        self.assertTrue(self.bad("cards", CARD_FILE, c))

    def test_a_card_cut_with_the_validated_measures_passes_and_instruments_cannot_be_mixed(self):
        new = mut(CARD, measured={"heard_syl_per_active_s": {"p10": 2.6, "median": 3.4, "p90": 3.8}, "npitch_sd_st": {"p10": 1.0, "median": 1.4, "p90": 1.9},
                                  "pause_share_pct": {"p10": 9.0, "median": 18.0, "p90": 30.0}},
                  thresholds={"heard_pace_fast_min": 4.3, "heard_pace_slow_max": 3.7, "spread_melodic_min": 2.6, "spread_flat_max": 1.9})
        self.assertEqual(self.bad("cards", CARD_FILE, new), [])
        self.assertTrue(self.bad("cards", CARD_FILE, mut(new, thresholds=CARD["thresholds"])))           # validated ranges under the older threshold names
        self.assertTrue(self.bad("cards", CARD_FILE, mut(CARD, thresholds=new["thresholds"])))           # and the other way round
        self.assertTrue(self.bad("cards", CARD_FILE, mut(new, thresholds=dict(new["thresholds"], flat_min=45.0))))   # names from both
        self.assertTrue(self.bad("cards", CARD_FILE, deep(new, ("measured", "flat_pct"), {"p10": 46.0, "median": 49.0, "p90": 53.0})))

    def test_tiny_sides_are_allowed_but_not_one_track_and_cards_still_need_three(self):
        self.assertEqual(self.crate_bad(make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[2, 3])), [])
        self.assertTrue(self.crate_bad(deep(CRATE, ("sides", "s1", "count"), 1)))
        self.assertTrue(self.crate_bad(deep(CRATE, ("sides", "s2", "groups"), 0)))
        self.assertTrue(self.bad("cards", CARD_FILE, mut(CARD, n_tracks=2)))

    def test_cross_checks_between_card_and_crate(self):
        self.assertTrue(any("exceeds" in e for e in self.bad("cards", CARD_FILE, mut(CARD, n_tracks=11))))   # side s1 has 10 tracks
        self.assertTrue(any("exceeds" in e for e in self.bad("cards", "slow-deadpan--crate-0123456789ab-s2.json", mut(CARD, side="s2", n_tracks=12))))
        for k, v in (("measured_on", "own"), ("analyzer", "other-tool"), ("analyzer_version", "2")):
            c = copy.deepcopy(CARD); c["basis"][k] = v
            self.assertTrue(any("differs" in e for e in self.bad("cards", CARD_FILE, c)), k)
        d = tree(cards=[(CARD_FILE, CARD)])   # no crate bundle at all
        self.assertTrue(any("not in crates" in e for e in X.check_dir(d)[0]["cards/" + CARD_FILE]))
        self.assertTrue(self.bad("cards", "slow-deadpan--crate-0123456789ab-s5.json", mut(CARD, side="s5")))   # the crate has only two sides

    def test_file_name_must_match_the_bundle(self):
        d = good(); (d / "crates" / CRATE_FILE).rename(d / "crates" / "crate-ffffffffffff.json")
        self.assertTrue(any("file name" in e for e in X.check_dir(d)[0]["crates/crate-ffffffffffff.json"]))

    def test_free_form_values_in_identifier_fields_are_refused(self):
        self.assertTrue(self.bad("prescriptions", "rx-0123456789ab.json", mut(RX, engine="a" * 3, unit="https://u:pw12345@h/x")))

    def test_prescription_value_inside_tested_range(self):
        self.assertTrue(self.bad("prescriptions", "rx-0123456789ab.json", mut(RX, value=9.0)))
        r = copy.deepcopy(RX); del r["flat_high"]
        self.assertTrue(self.bad("prescriptions", "rx-0123456789ab.json", r))

    def test_unlabelled_crate_is_normal_and_a_predicate_needs_the_right_formed_by(self):
        self.assertEqual(X.check_dir(good())[0], {})    # formed_by operator, no predicate
        pred = {"op": "all", "args": [{"atom": "pace:slow"}, {"op": "not", "args": [{"atom": "delivery:melodic"}]}]}
        ok = mut(CRATE, formed_by="predicate", predicate=pred)
        self.assertEqual(self.crate_bad(ok), [])
        self.assertTrue(self.crate_bad(mut(CRATE, predicate=pred)))
        self.assertTrue(self.crate_bad(mut(CRATE, formed_by="predicate")))
        self.assertTrue(self.crate_bad(mut(ok, predicate={"atom": "some artist"})))
        self.assertTrue(self.crate_bad(mut(ok, predicate={"op": "all", "args": [{"atom": "pace:slow"}]})))
        deep_pred = {"atom": "pace:slow"}
        for _ in range(4): deep_pred = {"op": "not", "args": [deep_pred]}
        self.assertTrue(self.crate_bad(mut(ok, predicate=deep_pred)))

    def test_relationship_numbers_must_be_consistent(self):
        self.assertTrue(self.crate_bad(deep(CRATE, ("relationship", "separability"), 0.60)))
        self.assertTrue(self.crate_bad(deep(CAST, ("relationship", "distinctness"), 0.99)))
        self.assertTrue(self.crate_bad(deep(CRATE, ("relationship", "pairs"), [deep(CRATE["relationship"]["pairs"][0], ("features", "flat_pct", "effect"), 1.5)])))
        flipped = copy.deepcopy(CRATE); flipped["relationship"]["pairs"][0]["features"]["flat_pct"]["effect"] = -0.8   # says s1 lower, but its median is higher
        flipped["relationship"]["separability"] = flipped["relationship"]["distinctness"] = 0.9
        self.assertTrue(any("median" in e for e in self.crate_bad(flipped)))
        up = copy.deepcopy(CRATE); up["relationship"]["pairs"][0]["features"]["syl_per_voiced_s"]["effect"] = 0.8   # says s1 higher, but its median is lower
        self.assertTrue(any("median" in e for e in self.crate_bad(up)))
        self.assertTrue(self.crate_bad(deep(CRATE, ("relationship", "carriers"), [])))
        self.assertTrue(self.crate_bad(deep(CRATE, ("relationship", "carriers"), ["not_a_feature"])))

    def test_a_tiny_crate_is_an_exploratory_hypothesis_not_a_finding(self):
        """3 tracks against 4, perfectly separated, has an exact two-sided p of 2/35: it can never be a finding on its own."""
        tiny = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[3, 4], strength=1.0)
        self.assertEqual(self.crate_bad(tiny), [])
        r = tiny["relationship"]
        self.assertEqual((r["evidence"], r["confidence"], r["carriers"], sorted(r["leaning"])), ("exploratory", "low", [], sorted(FEATS)))
        self.assertAlmostEqual(r["pairs"][0]["features"]["pace" if False else "syl_per_voiced_s"]["p"], 2 / 35, places=4)
        claimed = copy.deepcopy(tiny); claimed["relationship"].update(evidence="supported", carriers=sorted(FEATS), leaning=[])
        self.assertTrue(any("carriers must be exactly" in e for e in self.crate_bad(claimed)))
        confident = copy.deepcopy(tiny); confident["relationship"]["confidence"] = "high"
        self.assertTrue(any("exploratory" in e for e in self.crate_bad(confident)))

    def test_leaning_and_evidence_must_match_the_numbers(self):
        tiny = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[3, 4], strength=1.0)
        no_lean = copy.deepcopy(tiny); no_lean["relationship"]["leaning"] = []
        self.assertTrue(any("leaning must be exactly" in e for e in self.crate_bad(no_lean)))
        extra_lean = copy.deepcopy(tiny); extra_lean["relationship"]["leaning"] = ["syl_per_voiced_s", "flat_pct", "not_a_feature"]
        self.assertTrue(self.crate_bad(extra_lean))
        flipped = copy.deepcopy(tiny); flipped["relationship"]["evidence"] = "supported"     # carriers are still empty
        self.assertTrue(any("supported when there is at least one carrier" in e for e in self.crate_bad(flipped)))
        solid = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[40, 40])
        self.assertEqual(solid["relationship"]["evidence"], "supported")
        downgraded = copy.deepcopy(solid); downgraded["relationship"]["evidence"] = "exploratory"
        self.assertTrue(any("supported when there is at least one carrier" in e for e in self.crate_bad(downgraded)))
        self.assertTrue(self.crate_bad(deep(solid, ("relationship", "evidence"), "proven")))

    def test_p_is_recomputed_at_the_level_of_artist_groups(self):
        """The same group effect is a finding with many artists and only exploratory with few: p comes from the group counts, not the track counts."""
        many = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[40, 40], groups=[20, 20], confidence="medium")
        few = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[40, 40], groups=[4, 4])
        self.assertEqual(X.check_crate(many), []); self.assertEqual(X.check_crate(few), [])
        self.assertEqual(many["relationship"]["evidence"], "supported"); self.assertEqual(few["relationship"]["evidence"], "exploratory")
        f = "flat_pct"
        self.assertLess(many["relationship"]["pairs"][0]["features"][f]["p"], 0.001)
        self.assertGreater(few["relationship"]["pairs"][0]["features"][f]["p"], 0.02)          # 4 against 4 artists can never reach the shared bar
        lying = copy.deepcopy(few); lying["relationship"]["pairs"][0]["features"][f]["p"] = many["relationship"]["pairs"][0]["features"][f]["p"]
        self.assertTrue(X.check_crate(lying))
        gone = copy.deepcopy(many); del gone["relationship"]["pairs"][0]["features"][f]["group_effect"]
        self.assertTrue(X.check_crate(gone))

    def test_p_values_are_recomputed_exactly(self):
        wrong = copy.deepcopy(CRATE); wrong["relationship"]["pairs"][0]["features"]["flat_pct"]["p"] = 0.5
        self.assertTrue(any("p should be" in e for e in self.crate_bad(wrong)))
        nop = copy.deepcopy(CRATE); del nop["relationship"]["pairs"][0]["features"]["flat_pct"]["p"]
        self.assertTrue(self.crate_bad(nop))

    def test_the_same_effect_is_a_finding_on_big_sides_only(self):
        weak_small = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], strength=0.3)       # sides of 10 and 11
        weak_big = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], counts=[400, 400], strength=0.3)
        self.assertEqual((weak_small["relationship"]["evidence"], weak_big["relationship"]["evidence"]), ("exploratory", "supported"))
        self.assertEqual(self.crate_bad(weak_small), []); self.assertEqual(self.crate_bad(weak_big), [])

    def test_exact_distribution_matches_brute_force(self):
        import itertools
        for na, nb in ((2, 3), (3, 4), (4, 4), (5, 3), (1, 6)):
            vals, counts = list(range(na + nb)), [0] * (na * nb + 1)
            for comb in itertools.combinations(vals, na):
                other = [v for v in vals if v not in comb]
                counts[sum(a > b for a in comb for b in other)] += 1
            self.assertEqual(counts, X.mw_counts(na, nb))
        self.assertAlmostEqual(X.mw_pvalue(1.0, 3, 4), 2 / 35); self.assertAlmostEqual(X.mw_pvalue(1.0, 2, 3), 0.2)
        self.assertEqual(X.mw_pvalue(0.0, 5, 5), 1.0)
        self.assertAlmostEqual(X.mw_pvalue(0.4, 50, 50), X.mw_pvalue(0.4, 51, 50), places=3)      # exact and normal agree across the switch

    def test_more_personas_raise_the_bar_for_a_finding(self):
        """Adding personas shares the 5% level across more comparisons, so the same effect on the same side sizes can stop being a finding."""
        two = make_crate([prof(3.4, 49.0), prof(5.0, 30.0)], strength=0.65)
        cast = make_crate([prof(3.0, 55.0), prof(3.8, 40.0), prof(4.6, 28.0), prof(5.4, 48.0), prof(6.2, 20.0)], kind="cast", strength=0.65)
        self.assertEqual((two["relationship"]["evidence"], cast["relationship"]["evidence"]), ("supported", "exploratory"))
        self.assertEqual(self.crate_bad(two), []); self.assertEqual(self.crate_bad(cast), [])
        claimed = copy.deepcopy(cast); claimed["relationship"].update(evidence="supported", carriers=sorted(FEATS), leaning=[])
        self.assertTrue(self.crate_bad(claimed))

    def test_claims(self):
        claim = "claim-0123456789ab"
        self.assertEqual(self.crate_bad(mut(TWO, claim=claim)), [])
        self.assertTrue(self.crate_bad(mut(TWO, claim="my favourite artist")))           # not an id
        self.assertTrue(any("two-sided" in e for e in self.crate_bad(mut(CAST, claim=claim))))     # a cast has no consistent orientation
        pred = {"op": "all", "args": [{"atom": "pace:slow"}, {"atom": "delivery:deadpan"}]}
        swapped = {"op": "all", "args": [{"atom": "delivery:deadpan"}, {"atom": "pace:slow"}]}
        self.assertEqual(X.claim_for_predicate(pred), X.claim_for_predicate(swapped))      # argument order does not matter
        self.assertNotEqual(X.claim_for_predicate(pred), X.claim_for_predicate({"atom": "pace:slow"}))
        ok = mut(TWO, formed_by="predicate", predicate=pred, claim=X.claim_for_predicate(pred))
        self.assertEqual(self.crate_bad(ok), [])
        self.assertTrue(any("derived from the predicate" in e for e in self.crate_bad(mut(ok, claim=claim))))     # cannot be chosen freely

    def test_all_sides_profile_the_same_features(self):
        c = copy.deepcopy(CRATE); del c["sides"]["s2"]["profile"]["flat_pct"]
        self.assertTrue(self.crate_bad(c))

    def test_assumed_membership_can_only_claim_low_confidence(self):
        self.assertTrue(self.crate_bad(mut(CRATE, membership="assumed")))
        low = deep(mut(CRATE, membership="assumed"), ("relationship", "confidence"), "low")
        self.assertEqual(self.crate_bad(low), [])
        self.assertTrue(self.crate_bad(mut(CRATE, membership="guessed")))

    def test_confound_indicators(self):
        self.assertTrue(self.crate_bad(deep(CRATE, ("confounds", "shared_groups"), 99)))
        self.assertTrue(self.crate_bad(deep(CRATE, ("confounds", "matched_on"), ["loudness", "my favourite artist"])))
        self.assertEqual(self.crate_bad(deep(CRATE, ("confounds", "matched_on"), [])), [])

    def test_cli_exit_codes_and_summary(self):
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(X.main(["check", str(good())]), 0)
            d = good(); (d / "crates" / CRATE_FILE).write_text("{not json")
            self.assertEqual(X.main(["check", str(d)]), 1)
            self.assertEqual(X.main(["summary", str(good())]), 0)

if __name__ == "__main__":
    unittest.main()
