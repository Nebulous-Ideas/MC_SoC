import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gate, publish, release

REC = json.loads((ROOT / "records" / "history-mcp-schema-overhead.json").read_text())

def approved(i="one"):
    r = json.loads(json.dumps(REC)); r["id"] = i
    r["signoff"] = {"status": "approved", "by": "P", "channel": "chat", "at": "2026-11-11T19:00:00Z"}
    r["evidence"][0]["ref"] = "https://example.org/a"; return r

def store(*recs):
    d = Path(tempfile.mkdtemp()); (d / "r").mkdir()
    for r in recs: (d / "r" / f"{r['id']}.json").write_text(json.dumps(r))
    return d

class T(unittest.TestCase):
    def test_make_check_and_publish_from_release(self):
        d = store(approved("one"), approved("two"))
        m = gate.make_release(d / "r", "r1")
        self.assertEqual([x["id"] for x in m["records"]], ["one", "two"])
        (d / "r1.json").write_text(json.dumps(m))
        sys.argv = ["x", "static-site", "--release", str(d / "r1.json"), "--records", str(d / "r"), "--out", str(d / "pub")]
        self.assertEqual(publish.main(), 0); self.assertTrue((d / "pub" / "index.html").exists())

    def test_changed_record_blocks_release(self):
        d = store(approved("one")); m = gate.make_release(d / "r", "r1")
        r = approved("one"); r["lesson"] += " edited"; (d / "r" / "one.json").write_text(json.dumps(r))
        with self.assertRaises(ValueError): gate.load_release(m, d / "r")

    def test_unapproved_or_missing_blocks_release(self):
        d = store(approved("one")); m = gate.make_release(d / "r", "r1")
        r = approved("one"); r["signoff"] = {"status": "pending"}; (d / "r" / "one.json").write_text(json.dumps(r))
        with self.assertRaises(ValueError): gate.load_release(m, d / "r")
        (d / "r" / "one.json").unlink()
        with self.assertRaises(ValueError): gate.load_release(m, d / "r")

    def test_no_records_or_bad_record_refuses_make(self):
        with self.assertRaises(ValueError): gate.make_release(store(REC and {**REC, "id": "p", "signoff": {"status": "pending"}}) / "r", "x")
        bad = approved("bad"); bad["lesson"] += " see http://u:pw12345@h/x"
        with self.assertRaises(ValueError): gate.make_release(store(approved("one"), bad) / "r", "x")

    def test_release_files_are_not_overwritten(self):
        d = store(approved("one"))
        sys.argv = ["x", "make", "r1", "--records", str(d / "r"), "--out", str(d / "rel")]
        self.assertEqual(release.main(), 0); self.assertEqual(release.main(), 1)

if __name__ == "__main__":
    unittest.main()
