import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import features as F, persona
from test_features import FLOW_HEADER, flow_rows
from analyzers import flow_tsv
import tempfile, csv


def table():
    d = Path(tempfile.mkdtemp()); p = d / "f.tsv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t"); w.writerow(FLOW_HEADER); w.writerows(flow_rows())
    return flow_tsv.read(p)


def cal(**kw):
    c = {"status": "own-tracks", "n_tracks": 7, "rank_agreement": {"syl_per_voiced_s": 0.8}, "bias": {"syl_per_voiced_s": "low"}}
    c.update(kw); return c


class T(unittest.TestCase):
    def errs(self, mutate):
        t = table(); mutate(t); return F.validate(t)

    def test_adapters_carry_provenance_and_validate(self):
        t = table(); self.assertEqual(F.validate(t), [])
        self.assertEqual(t["provenance"]["n_tracks"], len(t["rows"]))
        self.assertEqual(t["provenance"]["calibration"], {"status": "none", "n_tracks": 0})

    def test_missing_provenance_refused_but_opt_out_exists_for_old_tables(self):
        t = table(); del t["provenance"]
        self.assertTrue(any("provenance is required" in e for e in F.validate(t)))
        self.assertEqual(F.validate(t, require_provenance=False), [])

    def test_free_text_and_unknown_keys_refused(self):
        self.assertTrue(self.errs(lambda t: t["provenance"].update(method="a whole sentence about lyrics")))
        self.assertTrue(self.errs(lambda t: t["provenance"].update(note="hello")))
        self.assertTrue(self.errs(lambda t: t["provenance"]["calibration"].update(comment="x")))
        self.assertTrue(self.errs(lambda t: t["provenance"].update(measured_on="my favourite artist")))

    def test_n_tracks_must_equal_rows(self):
        self.assertTrue(any("n_tracks" in e for e in self.errs(lambda t: t["provenance"].update(n_tracks=999))))

    def test_calibration_rules(self):
        ok = lambda t: t["provenance"].update(calibration=cal())
        self.assertEqual(self.errs(ok), [])
        for bad in (cal(status="none"), cal(n_tracks=0), cal(rank_agreement={"not_a_feature": 0.5}),
                    cal(rank_agreement={"syl_per_voiced_s": 1.5}), cal(bias={"syl_per_voiced_s": "terrible"}),
                    cal(rank_agreement={"syl_per_voiced_s": "high"})):
            self.assertTrue(self.errs(lambda t: t["provenance"].update(calibration=bad)), bad)

    def test_cards_carry_where_the_numbers_came_from(self):
        t = table(); t["provenance"]["calibration"] = cal()
        cards = persona.build_table(t, "voice", basis=True)
        self.assertTrue(cards)
        for c in cards:
            self.assertEqual(c["basis"]["calibration"], "own-tracks"); self.assertEqual(c["basis"]["analyzer"], "flow-tsv")
        blob = json.dumps(cards)
        for r in t["rows"]: self.assertNotIn(r["id"], blob); self.assertNotIn(r["group"], blob)
        self.assertNotIn("basis", persona.build_table(t, "voice")[0])   # off by default: legacy cards unchanged

if __name__ == "__main__":
    unittest.main()
