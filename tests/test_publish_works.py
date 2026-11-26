"""Approved derived works on the static site: only approved, verify-clean works; no approver names or references. Offline."""
import json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import gate  # noqa: E402
from publishers import static_site  # noqa: E402


class FakeWorks:
    def __init__(self, works, errors=None):
        self.works = {w["id"]: w for w in works}
        self.errors = errors or {}

    def list(self):
        return sorted(self.works)

    def get(self, rid):
        return self.works[rid]

    def verify(self, rid):
        return self.errors.get(rid, [])


def work(wid, status="approved", by="Maintainer"):
    return {"id": wid, "form": "spoken-rhyme", "lesson_ids": ["incident-squid-acl-shared-egress-denial"],
            "status": "approved" if status == "approved" else "draft", "content": "[Intro]\nA line & a <tag>\n",
            "redaction": {"status": "passed"},
            "signoff": {"status": status, "by": by, "channel": "chat", "at": "2026-11-16T02:25:40Z"},
            "memory_ref": "outline:secret-ref-123"}


class PublishWorksTests(unittest.TestCase):
    def test_only_approved_works_are_published(self):
        store = FakeWorks([work("song-a"), work("song-b", status="pending")])
        ok, errors = gate.publishable_works(store)
        self.assertEqual([w["id"] for w in ok], ["song-a"])
        self.assertEqual(errors, {})

    def test_a_failing_approved_work_is_reported_not_skipped(self):
        store = FakeWorks([work("song-a")], errors={"song-a": ["approval: redaction has not passed"]})
        ok, errors = gate.publishable_works(store)
        self.assertEqual(ok, [])
        self.assertIn("song-a", errors)

    def test_page_has_the_work_text_escaped_and_no_approver_or_reference(self):
        out = tempfile.mkdtemp()
        static_site.publish([], out, works=[work("song-a")])
        page = (Path(out) / "index.html").read_text()
        self.assertIn("Derived works", page)
        self.assertIn("A line &amp; a &lt;tag&gt;", page)
        self.assertNotIn("Maintainer", page)
        self.assertNotIn("secret-ref-123", page)
        self.assertNotIn("memory_ref", page)

    def test_default_page_is_unchanged_without_works(self):
        out = tempfile.mkdtemp()
        static_site.publish([], out)
        self.assertNotIn("Derived works", (Path(out) / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
