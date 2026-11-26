import json, shutil, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import decide

def tree(pending_only=False):
    d = Path(tempfile.mkdtemp())
    shutil.copytree(ROOT / "records", d / "records"); shutil.copytree(ROOT / "personas", d / "personas")
    (d / "schema").mkdir(); return d

class T(unittest.TestCase):
    def test_only_approved_get_a_brief(self):
        ids = {b["lesson"] for b in decide.propose(ROOT)}
        self.assertIn("history-mcp-schema-overhead", ids)
        self.assertNotIn("news-clawjacked-localhost-websocket", ids)  # sign-off pending

    def test_options_use_matching_voice_cards_and_unmapped_beats(self):
        d = tree()   # a card written here, so the test does not depend on which cards the current reference table happens to yield
        (d / "personas" / "slow-deadpan.json").write_text(json.dumps({"schema_version": 1, "card": "slow-deadpan", "kind": "voice", "n_tracks": 4,
            "traits": ["pace:slow", "delivery:deadpan"], "measured": {}, "form_hint": ["skit", "spoken-rhyme"], "thresholds": {}}))
        b = {x["lesson"]: x for x in decide.propose(d)}["incident-llm-deep-context-corruption"]
        forms = {o["form"]: o for o in b["options"]}
        self.assertEqual(set(forms), {"spoken-rhyme", "skit"})
        self.assertIn("slow-deadpan", forms["skit"]["voice_cards"])
        self.assertTrue(b["beat_cards"]); self.assertIn("not mapped", b["note"])

    def test_verify_failure_stops_the_run(self):
        d = tree(); p = next((d / "records").glob("history-*.json"))
        r = json.loads(p.read_text()); r["what_happened"] += " password=hunter2hunter2"; p.write_text(json.dumps(r))
        with self.assertRaises(ValueError): decide.propose(d)

    def test_output_has_no_names_or_notes(self):
        text = json.dumps(decide.propose(ROOT))
        for hidden in ("maintainer", "signoff", "memory_ref", "outline:", "note_model"):
            self.assertNotIn(hidden, text)

if __name__ == "__main__":
    unittest.main()
