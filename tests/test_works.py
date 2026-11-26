"""Derived works: sign-off through review.decide, the same routine as lesson records. Offline; works in a temp folder."""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import memory, review  # noqa: E402

WORK = "song-egress-shared-path"


class WorksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wdir = os.path.join(self.tmp, "works")
        os.makedirs(self.wdir)
        shutil.copy(HERE / "works" / (WORK + ".json"), self.wdir)
        self.lessons = memory.FileMemory(str(HERE / "records"))
        self.store = memory.FileWorks(self.wdir, self.lessons)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _set_redaction_passed(self):
        w = self.store.get(WORK)
        w["redaction"] = {"status": "passed", "method": "checked by a person for the text",
                          "checked_at": "2026-11-16T00:00:00-07:00"}
        self.store.put(w)

    def _decide(self, status="approved", user="Maintainer", confirm=lambda _: True):
        return review.decide(self.store, WORK, status, user, confirm, channel="chat",
                             now=None, model_note="test")

    def test_refused_while_redaction_is_pending(self):
        with self.assertRaises(review.ReviewError):
            self._decide()
        self.assertEqual(self.store.get(WORK)["signoff"]["status"], "pending")

    def test_approved_once_redaction_passed_and_status_follows(self):
        self._set_redaction_passed()
        so = self._decide()
        self.assertEqual(so["by"], "Maintainer")
        w = self.store.get(WORK)
        self.assertEqual(w["signoff"]["status"], "approved")
        self.assertEqual(w["status"], "approved")
        self.assertEqual(w["signoff"]["note_model"], "test")

    def test_unnamed_or_unattended_refused_before_any_dialog(self):
        self._set_redaction_passed()
        asked = []
        with self.assertRaises(review.ReviewError):
            self._decide(user="", confirm=lambda t: asked.append(t) or True)
        with self.assertRaises(review.ReviewError):
            self._decide(user="claude", confirm=lambda t: asked.append(t) or True)
        self.assertEqual(asked, [])

    def test_no_confirmation_changes_nothing(self):
        self._set_redaction_passed()
        with self.assertRaises(review.ReviewError):
            self._decide(confirm=lambda _: False)
        self.assertEqual(self.store.get(WORK)["signoff"]["status"], "pending")

    def test_work_naming_an_unapproved_lesson_cannot_be_approved(self):
        self._set_redaction_passed()
        w = self.store.get(WORK)
        w["lesson_ids"] = ["news-clawjacked-localhost-websocket"]  # pending in the records
        self.store.put(w)
        with self.assertRaises(review.ReviewError):
            self._decide()

    def test_reject_is_recorded_without_redaction(self):
        so = self._decide(status="rejected")
        self.assertEqual(so["status"], "rejected")
        self.assertEqual(self.store.get(WORK)["signoff"]["status"], "rejected")
        self.assertEqual(self.store.get(WORK)["status"], "draft")


class OutlineWorksTests(unittest.TestCase):
    """The same works rules over a fake Outline collection (no network)."""

    def setUp(self):
        self.work = json.loads((HERE / "works" / (WORK + ".json")).read_text())
        self.work["redaction"] = {"status": "passed", "method": "checked by a person for the text",
                                  "checked_at": "2026-11-16T00:00:00-07:00"}
        self.docs = {"d1": {"id": "d1", "title": WORK,
                            "text": "work\n```json\n" + json.dumps(self.work, indent=1) + "\n```"}}
        self.calls = []

        def post(endpoint, body):
            self.calls.append(endpoint)
            if endpoint == "documents.list":
                return {"data": list(self.docs.values())}
            if endpoint == "documents.info":
                return {"data": self.docs[body["id"]]}
            if endpoint == "documents.update":
                self.docs[body["id"]]["text"] = body["text"]
                return {"data": self.docs[body["id"]]}
            raise AssertionError(endpoint)

        self.lessons = memory.FileMemory(str(HERE / "records"))
        self.store = memory.OutlineWorks("works-collection", self.lessons, base_url="http://x", token="t", post=post)

    def test_approval_writes_signoff_and_status_into_the_document(self):
        review.decide(self.store, WORK, "approved", "Maintainer", lambda _: True, channel="chat", model_note="test")
        got = self.store.get(WORK)
        self.assertEqual(got["signoff"]["status"], "approved")
        self.assertEqual(got["status"], "approved")
        self.assertEqual(self.calls.count("documents.update"), 1)

    def test_pending_redaction_refused_and_document_untouched(self):
        self.work["redaction"]["status"] = "pending"
        self.docs["d1"]["text"] = "work\n```json\n" + json.dumps(self.work, indent=1) + "\n```"
        with self.assertRaises(review.ReviewError):
            review.decide(self.store, WORK, "approved", "Maintainer", lambda _: True)
        self.assertNotIn("documents.update", self.calls)


if __name__ == "__main__":
    unittest.main()
