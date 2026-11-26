#!/usr/bin/env python3
"""Review surface: a Discord card with Approve / Reject buttons. Stdlib only.

This file is the surface LOGIC only: it builds the card and turns a button interaction into a
decision. It does not talk to Discord. A transport (a bot using any Discord library, or an OpenClaw
channel if one can carry it) delivers `build_card` output and passes each interaction JSON to
`handle_interaction`. Shapes follow Discord's message and interaction JSON; the transport must also
verify Discord's request signature when it receives interactions over HTTP.

How it meets the review-surface contract (docs/design.md, decision 13):
  - identity: the Discord user id in the interaction, mapped to a name by `people` (id -> name,
    the maintainer's allow-list of reviewers). An id not in `people` is refused. Display names and
    anything in the message text are never used.
  - confirm: two steps. The first click (Approve/Reject on the card) only runs the refusal checks
    and answers, visible only to the clicker, with a Confirm / Cancel prompt. Only the Confirm
    click records a decision.
  - the text signed is the text shown: every button carries a hash of what the card displayed;
    if the record changed since the card was posted, the click is refused.
  - the write goes through review.decide -> set_signoff, with channel "discord".
Not built: a typed note (needs a Discord modal) and the transport itself.
"""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import review

PREFIX = "mcsoc"
EMBED_TOTAL_MAX = 5500   # Discord allows 6000 characters per embed; keep headroom
FIELD_MAX = 1024
BUTTON_PRIMARY, BUTTON_SECONDARY, BUTTON_SUCCESS, BUTTON_DANGER = 1, 2, 3, 4


class CardTooLong(Exception):
    """The lesson does not fit on a card, so a person could not read all of it here."""


def _shown(record):
    """Everything the card displays, in a fixed order. The hash covers exactly this."""
    return {"id": record["id"], "source": record["source"]["ref"], "what": record["what_happened"],
            "lesson": record["lesson"], "evidence": [[e["claim"], e["ref"]] for e in record["evidence"]],
            "signoff": record["signoff"]["status"]}


def shown_hash(record):
    return hashlib.sha256(json.dumps(_shown(record), sort_keys=True).encode()).hexdigest()[:12]


def custom_id(action, rid, h):
    cid = f"{PREFIX}:{action}:{rid}:{h}"
    if len(cid) > 100:  # Discord's limit
        raise CardTooLong(f"record id too long for a button: {rid}")
    return cid


def parse_custom_id(cid):
    parts = str(cid).split(":")
    if len(parts) != 4 or parts[0] != PREFIX:
        return None
    return {"action": parts[1], "rid": parts[2], "hash": parts[3]}


def _chunks(text):
    return [text[i:i + FIELD_MAX] for i in range(0, len(text), FIELD_MAX)] or [""]


def build_card(record):
    """The message to post for a record. Raises CardTooLong rather than cutting text off."""
    s = _shown(record)
    fields, total = [], len(s["id"]) + len(s["source"])
    def add(name, text):
        nonlocal total
        for n, part in enumerate(_chunks(text)):
            fields.append({"name": name if n == 0 else f"{name} (cont.)", "value": part}); total += len(part) + len(name)
    add("What happened", s["what"]); add("Lesson", s["lesson"])
    add("Evidence", "\n".join(f"- {c} <{r}>" for c, r in s["evidence"]))
    if total > EMBED_TOTAL_MAX or len(fields) > 25:
        raise CardTooLong(f"{s['id']} is too long to review in a card; use another surface")
    h = shown_hash(record)
    return {"embeds": [{"title": s["id"], "description": f"source: {s['source']}\nsign-off: {s['signoff']}", "fields": fields}],
            "components": [{"type": 1, "components": [
                {"type": 2, "style": BUTTON_SUCCESS, "label": "Approve", "custom_id": custom_id("approve", s["id"], h)},
                {"type": 2, "style": BUTTON_DANGER, "label": "Reject", "custom_id": custom_id("reject", s["id"], h)}]}]}


def _reply(text, components=None, **extra):
    out = {"ephemeral": True, "content": text}   # ephemeral: only the person who clicked sees it
    if components:
        out["components"] = [{"type": 1, "components": components}]
    out.update(extra); return out


def _user_id(interaction):
    user = (interaction.get("member") or {}).get("user") or interaction.get("user") or {}
    return str(user["id"]) if user.get("id") else None


STATUS = {"approve": "approved", "reject": "rejected"}


def handle_interaction(interaction, store, people, approvers=None, now=None):
    """Turn one button interaction into a response. Returns a dict for the transport to send.

    interaction: Discord interaction JSON (type 3, component click).
    people: {discord_user_id: name}, the reviewers who may use this surface.
    approvers: optional extra name allow-list passed on to review (see review.approvers_from_env)."""
    cid = parse_custom_id((interaction.get("data") or {}).get("custom_id"))
    if cid is None:
        return _reply("not an MC SOC button; ignoring", ignored=True)
    uid = _user_id(interaction)
    name = people.get(uid) if uid else None
    if not name:
        return _reply("refused: your Discord account is not a registered reviewer", refused=True)
    action, rid = cid["action"], cid["rid"]
    if action == "cancel":
        return _reply("cancelled; nothing changed")
    base = action[len("confirm-"):] if action.startswith("confirm-") else action
    if base not in STATUS:
        return _reply("not an MC SOC button; ignoring", ignored=True)
    status = STATUS[base]
    try:
        record = store.get(rid)
        if shown_hash(record) != cid["hash"]:
            return _reply("refused: this record changed since the card was posted; ask for a fresh card", refused=True)
        review.precheck(store, rid, status, name, approvers)   # every refusal, before anyone is asked
    except review.ReviewError as e:
        return _reply(f"refused: {e}", refused=True)
    except Exception as e:  # unknown record, store trouble: never fall through to a write
        return _reply(f"refused: {type(e).__name__}", refused=True)
    if action in STATUS:   # first click: show the prompt, change nothing
        h = cid["hash"]
        return _reply(f"{status.upper()} {rid} as {name}? Press Confirm to record it; Cancel to stop.",
                      [{"type": 2, "style": BUTTON_SUCCESS, "label": "Confirm", "custom_id": custom_id("confirm-" + base, rid, h)},
                       {"type": 2, "style": BUTTON_SECONDARY, "label": "Cancel", "custom_id": custom_id("cancel", rid, h)}],
                      awaiting_confirm=True)
    try:   # second click: the Confirm press is the person's deliberate act
        so = review.decide(store, rid, status, name, lambda q: True, channel="discord", approvers=approvers, now=now)
    except review.ReviewError as e:
        return _reply(f"refused: {e}", refused=True)
    return _reply(f"{status}: {rid}", recorded=True, signoff_status=so["status"])
