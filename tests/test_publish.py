import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish

REC = json.loads((ROOT / "records" / "history-mcp-schema-overhead.json").read_text())

def run(recs):
    d = Path(tempfile.mkdtemp()); out = d / "public"; (d / "r").mkdir()
    for r in recs: (d / "r" / f"{r['id']}.json").write_text(json.dumps(r))
    sys.argv = ["x", "static-site", "--records", str(d / "r"), "--out", str(out)]
    code = publish.main()
    return code, (out / "index.html").read_text() if (out / "index.html").exists() else ""

def approved(r):
    r = json.loads(json.dumps(r))
    r["signoff"] = {"status": "approved", "by": "Secret Person", "channel": "chat",
                    "at": "2026-11-11T19:00:00Z", "note": "private note", "note_model": "model note"}
    r["evidence"][0]["ref"] = "https://example.org/a"
    return r

class T(unittest.TestCase):
    def test_only_approved_published_and_private_fields_left_out(self):
        pend = json.loads(json.dumps(REC)); pend["id"] = "pending-one"; pend["signoff"] = {"status": "pending"}
        code, page = run([approved(REC), pend])
        self.assertEqual(code, 0)
        self.assertIn("history mcp schema overhead", page); self.assertNotIn("pending one", page)
        for hidden in ("Secret Person", "private note", "model note", "memory_ref", "outline:"):
            self.assertNotIn(hidden, page)
        self.assertIn("example.org", page); self.assertIn("internal reference", page)

    def test_failing_record_blocks_the_build(self):
        r = approved(REC); r["lesson"] += " see http://u:pw12345@h/x"
        code, page = run([r]); self.assertEqual(code, 1); self.assertEqual(page, "")

    def test_html_is_escaped(self):
        r = approved(REC); r["lesson"] = "<script>alert(1)</script>"
        _, page = run([r]); self.assertNotIn("<script>alert", page)

if __name__ == "__main__":
    unittest.main()

class TestRegistry(unittest.TestCase):
    def test_registry_lists_static_site_and_gate_is_shared(self):
        import publishers, gate
        self.assertIn("static-site", publishers.PUBLISHERS)
        ok, errors, skipped = gate.publishable(ROOT / "records")
        self.assertEqual(errors, {}); self.assertTrue(all(r["signoff"]["status"] == "approved" for r in ok))


class TestInternalHosts(unittest.TestCase):
    def test_placeholder_private_and_configured_hosts_are_not_linked(self):
        import os
        from publishers import static_site
        for u in ("http://10.1.2.3/x", "http://172.20.0.5/x", "http://box.local/x"):
            self.assertIn("internal reference", static_site.ref_html(u), u)
        self.assertIn("<a ", static_site.ref_html("https://docs.python.org/3/"))
        os.environ["MCSOC_INTERNAL_DOMAINS"] = "corp.test"
        try:
            self.assertIn("internal reference", static_site.ref_html("https://wiki.corp.test/x"))
        finally:
            del os.environ["MCSOC_INTERNAL_DOMAINS"]
