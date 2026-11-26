#!/usr/bin/env python3
"""Review surface: how a person sees a record and records a decision. Stdlib only.

A surface is anything that can (1) show a record to a named person and (2) get that
person's confirmation. The decision logic lives here once; surfaces only supply
the authenticated name and a confirm() callback. Implementations:
  - this CLI (a person at a terminal)
  - openmole_tool.py (Open WebUI / OpenMOLE chat; name from the platform's __user__,
    confirmation from a dialog the person clicks)

Rules enforced here, for every surface:
  - the name comes from the platform, never from model or record text, and is not
    a non-human name (unattended, bot, claude, ...)
  - a person must confirm; a refused or missing confirmation changes nothing
  - approval needs the record to pass verify (schema, redaction by value, evidence)
  - the write goes to the memory system's set_signoff, the only sign-off write path
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import verify as V
import memory
import notifier

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "schema" / "lesson-record.schema.json").read_text())


class ReviewError(Exception):
    pass


def present(record):
    """Plain-text view of a record or a derived work for a reviewer."""
    if "lesson_ids" in record and "content" in record:  # a derived work
        return (f"{record['id']}  [derived work, form: {record['form']}]\n"
                f"from lessons: {', '.join(record['lesson_ids'])}\n\n"
                f"{record['content']}\n"
                f"redaction: {record['redaction']['status']}\n"
                f"sign-off: {record['signoff']['status']}")
    ev = "\n".join(f"  - {e['claim']}  <{e['ref']}>" for e in record["evidence"])
    return (f"{record['id']}  [{record['source']['kind']}: {record['source']['system']}]\n"
            f"source: {record['source']['ref']}\n\n"
            f"What happened: {record['what_happened']}\n\nLesson: {record['lesson']}\n\n"
            f"Evidence:\n{ev}\n\nsign-off: {record['signoff']['status']}")


def approvers_from_env(env=None):
    """Allow-list of approver names from MCSOC_APPROVERS (comma-separated, case-insensitive).

    Returns None when unset, meaning "any named human the platform vouches for" (the original
    behaviour). Set it to restrict approval to listed people."""
    import os
    raw = (env if env is not None else os.environ).get("MCSOC_APPROVERS", "")
    names = {n.strip().lower() for n in raw.split(",") if n.strip()}
    return names or None


def precheck(store, rid, status, user_name, approvers=None):
    """Everything that can refuse a decision without asking the person. Returns (record, name).

    approvers: optional collection of allowed names (lower-case); a name not in it is refused.
    Run this before showing any dialog, so nobody confirms something that will be refused."""
    if status not in ("approved", "rejected"):
        raise ReviewError("status must be approved or rejected")
    name = (user_name or "").strip()
    if not name or name.lower() in V.NON_HUMAN:
        raise ReviewError("no named human user; refusing")
    if approvers is not None and name.lower() not in {a.lower() for a in approvers}:
        raise ReviewError(f"{name} is not on the approvers list; refusing")
    record = store.get(rid)
    if record["signoff"]["status"] == status:
        raise ReviewError(f"{rid} is already {status}")
    if status == "approved":
        if hasattr(store, "verify"):  # a works store checks itself against its lessons
            errs = store.verify(rid)
        else:
            errs, _, _ = V.verify_record(record, SCHEMA, rid)
        if errs:
            raise ReviewError("cannot approve, verify failed: " + "; ".join(errs))
    return record, name


def decide(store, rid, status, user_name, confirm, note="", channel="chat", now=None, model_note="", approvers=None):
    """Record a human decision. Returns the new signoff dict.

    store: a memory adapter with get() and set_signoff().
    confirm: callable(summary_text) -> bool, answered by the person, not the model.
    note: text the person typed. model_note: text the assistant supplied (stored separately).
    """
    _, name = precheck(store, rid, status, user_name, approvers)
    if not confirm(f"{status.upper()} {rid} as {name}?"):
        raise ReviewError("not confirmed; nothing changed")
    signoff = {"status": status, "by": name, "channel": channel,
               "at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if note:  # typed by the person
        signoff["note"] = note
    if model_note:  # supplied by the assistant: kept apart, never in the human's field
        signoff["note_model"] = model_note
    store.set_signoff(rid, signoff)
    notifier.emit("signoff", f"{rid}: {status}")  # no-op unless NOTIFY_HUB is set; never raises
    return signoff


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("op", choices=["show", "approve", "reject"])
    ap.add_argument("id")
    ap.add_argument("--as", dest="user", help="your name (the person at the keyboard)")
    ap.add_argument("--cache", default=str(HERE / "records"))
    ap.add_argument("--note", default="")
    ap.add_argument("--works", action="store_true", help="act on a derived work in works/ instead of a lesson record")
    a = ap.parse_args()
    store = memory.FileWorks(str(HERE / "works"), memory.FileMemory(a.cache)) if a.works else memory.FileMemory(a.cache)
    if a.op == "show":
        print(present(store.get(a.id))); return 0
    print(present(store.get(a.id)), "\n")
    try:
        s = decide(store, a.id, "approved" if a.op == "approve" else "rejected", a.user,
                   lambda q: input(q + " [y/N] ").strip().lower() == "y", a.note, channel="chat")
    except ReviewError as e:
        print("refused:", e); return 1
    print("recorded:", json.dumps(s))
    print("note: this edits the local cache; the memory system's copy is canonical. Pull/push never changes sign-off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
