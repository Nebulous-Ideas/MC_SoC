"""Conformance cases for review surfaces. Stdlib only.

A review surface (CLI, chat tool, Discord card, MR approval, ...) proves it keeps the contract in
docs/design.md (decision 13) by subclassing ReviewSurfaceContract together with unittest.TestCase and
supplying `act`. Nothing here knows about any platform; the surface is the fake of its own platform.

    act(store, rid, status, who, confirm, approvers) -> bool

  who        the identity the PLATFORM vouches for (a string), or None when the platform gave none
  confirm    callable(prompt_text) -> bool: the person's deliberate act. The surface calls it at most
             once, only after every refusal check has passed, and acts only if it returns True
  approvers  None (anyone named) or a collection of allowed names
  returns    True if the surface reported the decision as recorded, False if it refused
"""
import copy, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import memory
from test_memory import FakeOutline, REC


def fresh_store(corrupt=False):
    """A memory store holding one pending record. The store records every set_signoff call."""
    fake = FakeOutline(); st = memory.OutlineMemory("c1", post=fake)
    r = copy.deepcopy(REC); r.pop("memory_ref", None)
    st._post("documents.create", {"title": r["id"], "text": memory.render_doc(r), "collectionId": "c1"})
    if corrupt:  # a secret-shaped value the redaction scan must catch, whatever the field is called
        doc = next(iter(fake.docs.values()))
        rec = memory.parse_doc(doc["text"]); rec["lesson"] += " see http://u:pw12345@h/x"
        doc["text"] = memory.render_doc(rec)
    st.signoff_calls = []
    real = st.set_signoff
    def spy(rid, so):
        st.signoff_calls.append((rid, copy.deepcopy(so))); return real(rid, so)
    st.set_signoff = spy
    return st, r["id"]


class Confirm:
    """A confirmation callback that counts how often it was asked and what it was shown."""
    def __init__(self, answer=True): self.answer, self.asked = answer, []
    def __call__(self, text): self.asked.append(text); return self.answer


class ReviewSurfaceContract:
    def act(self, store, rid, status, who, confirm, approvers):  # pragma: no cover - supplied by the surface
        raise NotImplementedError

    def test_contract_person_confirms_and_signoff_is_written_once(self):
        st, rid = fresh_store(); c = Confirm(True)
        self.assertTrue(self.act(st, rid, "approved", "Alex Example", c, None))
        self.assertEqual(len(st.signoff_calls), 1)
        so = st.get(rid)["signoff"]
        self.assertEqual((so["status"], so["by"]), ("approved", "Alex Example"))
        self.assertTrue(so["channel"]); self.assertTrue(so["at"])

    def test_contract_person_is_shown_what_they_sign(self):
        st, rid = fresh_store(); c = Confirm(True)
        self.act(st, rid, "approved", "Alex Example", c, None)
        self.assertEqual(len(c.asked), 1); self.assertIn(rid, c.asked[0])

    def test_contract_declined_confirmation_changes_nothing(self):
        st, rid = fresh_store()
        self.assertFalse(self.act(st, rid, "approved", "Alex Example", Confirm(False), None))
        self.assertEqual(st.signoff_calls, []); self.assertEqual(st.get(rid)["signoff"]["status"], "pending")

    def test_contract_no_identity_or_non_human_identity_refused_before_asking(self):
        for who in (None, "", "  ", "unattended", "Claude", "bot", "CI"):
            st, rid = fresh_store(); c = Confirm(True)
            self.assertFalse(self.act(st, rid, "approved", who, c, None), who)
            self.assertEqual(c.asked, [], who); self.assertEqual(st.signoff_calls, [], who)

    def test_contract_unlisted_person_refused_listed_person_accepted(self):
        st, rid = fresh_store(); c = Confirm(True)
        self.assertFalse(self.act(st, rid, "approved", "Mallory", c, {"alex example"}))
        self.assertEqual(c.asked, []); self.assertEqual(st.signoff_calls, [])
        self.assertTrue(self.act(st, rid, "approved", "Alex Example", Confirm(True), {"alex example"}))

    def test_contract_record_failing_verify_cannot_be_approved_and_nobody_is_asked(self):
        st, rid = fresh_store(corrupt=True); c = Confirm(True)
        self.assertFalse(self.act(st, rid, "approved", "Alex Example", c, None))
        self.assertEqual(c.asked, []); self.assertEqual(st.signoff_calls, [])

    def test_contract_already_decided_record_is_refused(self):
        st, rid = fresh_store()
        self.assertTrue(self.act(st, rid, "approved", "Alex Example", Confirm(True), None))
        c = Confirm(True)
        self.assertFalse(self.act(st, rid, "approved", "Alex Example", c, None))
        self.assertEqual(len(st.signoff_calls), 1)

    def test_contract_rejection_is_recorded_like_approval(self):
        st, rid = fresh_store()
        self.assertTrue(self.act(st, rid, "rejected", "Alex Example", Confirm(True), None))
        self.assertEqual(st.get(rid)["signoff"]["status"], "rejected")
