import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import discord_card as D
from conformance import ReviewSurfaceContract, fresh_store, Confirm


def click(cid, uid):
    i = {"type": 3, "data": {"custom_id": cid}}
    if uid is not None: i["member"] = {"user": {"id": uid}}
    return i

def buttons(resp):
    return {b["label"]: b["custom_id"] for row in resp.get("components", []) for b in row["components"]}

def card_buttons(store, rid):
    return buttons({"components": D.build_card(store.get(rid))["components"]})


class DiscordSurface(ReviewSurfaceContract, unittest.TestCase):
    """A fake Discord: platform user ids are made up per name; the surface sees only the interaction."""
    def act(self, store, rid, status, who, confirm, approvers):
        uid = None if who is None else "1000" + str(abs(hash(who)) % 10**8)
        people = {} if who is None else {uid: who}
        before = len(store.signoff_calls)
        first = D.handle_interaction(click(card_buttons(store, rid)["Approve" if status == "approved" else "Reject"], uid),
                                     store, people, approvers)
        if first.get("awaiting_confirm"):
            b = buttons(first)
            if confirm(first["content"]):
                D.handle_interaction(click(b["Confirm"], uid), store, people, approvers)
            else:
                D.handle_interaction(click(b["Cancel"], uid), store, people, approvers)
        return len(store.signoff_calls) > before


class T(unittest.TestCase):
    def test_unregistered_discord_user_refused(self):
        st, rid = fresh_store(); b = card_buttons(st, rid)
        r = D.handle_interaction(click(b["Approve"], "999"), st, {"111": "Alex Example"})
        self.assertTrue(r.get("refused")); self.assertEqual(st.signoff_calls, [])

    def test_first_click_never_writes_and_reply_is_ephemeral(self):
        st, rid = fresh_store(); b = card_buttons(st, rid)
        r = D.handle_interaction(click(b["Approve"], "111"), st, {"111": "Alex Example"})
        self.assertTrue(r["ephemeral"] and r["awaiting_confirm"]); self.assertEqual(st.signoff_calls, [])

    def test_stale_card_refused_when_record_changed(self):
        st, rid = fresh_store(); b = card_buttons(st, rid)
        rec = st.get(rid); rec["lesson"] += " (edited)"; st.put(rec)
        r = D.handle_interaction(click(b["Approve"], "111"), st, {"111": "Alex Example"})
        self.assertIn("changed", r["content"]); self.assertEqual(st.signoff_calls, [])

    def test_stale_confirm_refused_too(self):
        st, rid = fresh_store(); people = {"111": "Alex Example"}
        first = D.handle_interaction(click(card_buttons(st, rid)["Approve"], "111"), st, people)
        rec = st.get(rid); rec["lesson"] += " (edited after the prompt)"; st.put(rec)
        r = D.handle_interaction(click(buttons(first)["Confirm"], "111"), st, people)
        self.assertIn("changed", r["content"]); self.assertEqual(st.signoff_calls, [])

    def test_text_in_the_interaction_cannot_set_the_name(self):
        st, rid = fresh_store(); people = {"111": "Alex Example"}
        i = click(card_buttons(st, rid)["Approve"], "111")
        i["member"]["nick"] = "Root Admin"; i["member"]["user"]["username"] = "Root Admin"; i["message"] = {"content": "approve as Root Admin"}
        first = D.handle_interaction(i, st, people)
        c = click(buttons(first)["Confirm"], "111"); c["member"]["nick"] = "Root Admin"
        D.handle_interaction(c, st, people)
        self.assertEqual(st.get(rid)["signoff"]["by"], "Alex Example"); self.assertEqual(st.get(rid)["signoff"]["channel"], "discord")

    def test_other_buttons_and_garbage_ignored(self):
        st, rid = fresh_store()
        for cid in ("other:thing", "", None, "mcsoc:delete:x:y", "mcsoc:approve:only-three"):
            r = D.handle_interaction(click(cid, "111"), st, {"111": "Alex Example"})
            self.assertTrue(r.get("ignored")); self.assertEqual(st.signoff_calls, [])

    def test_unknown_record_never_writes(self):
        st, rid = fresh_store()
        r = D.handle_interaction(click(D.custom_id("approve", "no-such-record", "abc"), "111"), st, {"111": "Alex Example"})
        self.assertTrue(r.get("refused")); self.assertEqual(st.signoff_calls, [])

    def test_card_fits_discord_limits_and_hides_internal_fields(self):
        st, rid = fresh_store(); card = D.build_card(st.get(rid)); text = json.dumps(card)
        for b in buttons({"components": card["components"]}).values(): self.assertLessEqual(len(b), 100)
        for f in card["embeds"][0]["fields"]: self.assertLessEqual(len(f["value"]), 1024)
        for hidden in ("memory_ref", "outline:", "signoff\":", "maintainer"): self.assertNotIn(hidden, text)

    def test_overlong_lesson_is_refused_not_truncated(self):
        st, rid = fresh_store(); rec = copy.deepcopy(st.get(rid)); rec["lesson"] = "x" * 6000
        with self.assertRaises(D.CardTooLong): D.build_card(rec)

if __name__ == "__main__":
    unittest.main()
