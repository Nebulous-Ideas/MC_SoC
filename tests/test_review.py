import asyncio, copy, json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import memory, review, openmole_tool
from test_memory import FakeOutline, REC

def fresh_store():
    fake = FakeOutline(); st = memory.OutlineMemory("c1", post=fake)
    r = copy.deepcopy(REC); r.pop("memory_ref", None)
    st._post("documents.create", {"title": r["id"], "text": memory.render_doc(r), "collectionId": "c1"})
    return st, fake, r["id"]

class T(unittest.TestCase):
    def test_approve_writes_signoff_with_confirmation(self):
        st, fake, rid = fresh_store()
        s = review.decide(st, rid, "approved", "Alex", lambda q: True)
        self.assertEqual((s["status"], s["by"], s["channel"]), ("approved", "Alex", "chat"))
        self.assertEqual(st.get(rid)["signoff"]["by"], "Alex")

    def test_no_confirmation_changes_nothing(self):
        st, _, rid = fresh_store()
        with self.assertRaises(review.ReviewError):
            review.decide(st, rid, "approved", "Alex", lambda q: False)
        self.assertEqual(st.get(rid)["signoff"]["status"], "pending")

    def test_non_human_and_blank_names_refused(self):
        st, _, rid = fresh_store()
        for n in ("unattended", "Claude", "", None):
            with self.assertRaises(review.ReviewError):
                review.decide(st, rid, "approved", n, lambda q: True)

    def test_cannot_approve_record_with_secret(self):
        st, fake, rid = fresh_store()
        doc = next(iter(fake.docs.values()))
        r = memory.parse_doc(doc["text"]); r["lesson"] += " see http://u:pw12345@h/x"
        doc["text"] = memory.render_doc(r)
        with self.assertRaises(review.ReviewError) as c:
            review.decide(st, rid, "approved", "Alex", lambda q: True)
        self.assertIn("redaction", str(c.exception))

    def test_tool_uses_platform_name_and_dialog(self):
        st, fake, rid = fresh_store()
        t = openmole_tool.Tools(); t._store = lambda: st
        yes = lambda ev: asyncio.sleep(0, True)
        no = lambda ev: asyncio.sleep(0, False)
        self.assertIn("refused", asyncio.run(t.approve(rid, __user__={"name": "Alex"}, __event_call__=no)))
        self.assertIn("refused", asyncio.run(t.approve(rid, __user__={"name": "Alex"})))
        self.assertIn("refused", asyncio.run(t.approve(rid, __user__={}, __event_call__=yes)))
        self.assertEqual(st.get(rid)["signoff"]["status"], "pending")
        self.assertEqual(asyncio.run(t.approve(rid, __user__={"name": "Alex"}, __event_call__=yes)), f"approved: {rid}")
        self.assertEqual(st.get(rid)["signoff"]["by"], "Alex")

    def test_notes_kept_apart(self):
        st, fake, rid = fresh_store()
        s = review.decide(st, rid, "approved", "Alex", lambda q: True, note="checked it myself", model_note="looks fine")
        self.assertEqual((s["note"], s["note_model"]), ("checked it myself", "looks fine"))
        st2, _, rid2 = fresh_store()
        s2 = review.decide(st2, rid2, "approved", "Alex", lambda q: True, model_note="looks fine")
        self.assertNotIn("note", s2); self.assertEqual(s2["note_model"], "looks fine")

    def test_tool_input_dialog_becomes_human_note(self):
        st, fake, rid = fresh_store()
        t = openmole_tool.Tools(); t._store = lambda: st
        async def ev(e):
            return True if e["type"] == "confirmation" else "I read the source"
        out = asyncio.run(t.approve(rid, comment="assistant says ok", __user__={"name": "Alex"}, __event_call__=ev))
        so = st.get(rid)["signoff"]
        self.assertEqual((so["note"], so["note_model"]), ("I read the source", "assistant says ok"))

    def test_refusals_happen_before_any_dialog(self):
        st, fake, rid = fresh_store()
        doc = next(iter(fake.docs.values()))
        r = memory.parse_doc(doc["text"]); r["lesson"] += " see http://u:pw12345@h/x"
        doc["text"] = memory.render_doc(r)
        t = openmole_tool.Tools(); t._store = lambda: st
        shown = []
        async def ev(e):
            shown.append(e["type"]); return True
        out = asyncio.run(t.approve(rid, __user__={"name": "Alex"}, __event_call__=ev))
        self.assertIn("refused", out); self.assertEqual(shown, [])
        out = asyncio.run(t.approve(rid, __user__={}, __event_call__=ev))
        self.assertIn("refused", out); self.assertEqual(shown, [])

    def test_push_still_cannot_change_signoff(self):
        st, fake, rid = fresh_store()
        review.decide(st, rid, "approved", "Alex", lambda q: True)
        local = memory.FileMemory(tempfile.mkdtemp())
        memory.pull(st, local)
        r = local.get(rid); r["signoff"] = {"status": "pending"}; local.put(r)
        with self.assertRaises(PermissionError):
            memory.push(local, st)

if __name__ == "__main__":
    unittest.main()
