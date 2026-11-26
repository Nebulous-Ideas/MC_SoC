"""
title: MC SOC review
description: Review and sign off MC SOC lesson records from OpenMOLE chat. Wraps the mc-soc code (verify, pull, review) so the chat and the CLI share one gate.
requirements:
version: 0.4.0

Tried in OpenMOLE (Open WebUI v0.13.2) on 2026-11-11: listing and approving from chat work;
`__user__` carries the logged-in person's name and `__event_call__` "confirmation" shows a
dialog. The "input" dialog (the approver's own note) works in this version; if
it does not appear the note is skipped and the approval still goes through.
Needs the mc-soc code mounted read-only at MCSOC_PATH (default /opt/mc-soc).

Secrets: OUTLINE_URL and OUTLINE_API_TOKEN are read from the container environment by
mc-soc/memory.py. Do not put the token in a Valve.

Safety: the model can call these tools but cannot approve. `approve`/`reject` take the
name from the platform's __user__, never from a model-supplied argument, and need a
click on a confirmation dialog. The `comment` argument is the assistant's, and is stored
as signoff.note_model, apart from the note the person types.
"""
import os
import sys

try:
    from pydantic import BaseModel, Field
except ImportError:  # local import for tests only; Open WebUI always has pydantic
    BaseModel = object

    def Field(default=None, **_):
        return default


def _load():
    path = os.environ.get("MCSOC_PATH", "/opt/mc-soc")
    if path not in sys.path:
        sys.path.insert(0, path)
    import memory, review, verify
    return memory, review, verify


class Tools:
    class Valves(BaseModel):
        collection_id: str = Field(default="b168dc15-7b02-4fb2-93da-065eb68a5fac",
                                   description="Outline collection holding lesson records")
        works_collection_id: str = Field(default="4502b817-b7d1-4602-9b06-7cb7cfe1bfd2",
                                         description="Outline collection holding derived works")

    def __init__(self):
        self.valves = self.Valves()

    def _store(self, kind="record"):
        memory, _, _ = _load()
        if kind == "work":
            return memory.OutlineWorks(self.valves.works_collection_id,
                                       memory.OutlineMemory(self.valves.collection_id))
        return memory.OutlineMemory(self.valves.collection_id)

    def list_works(self) -> str:
        """List derived work ids with their sign-off status."""
        s = self._store("work")
        return "\n".join(f"{w}: {s.get(w)['signoff']['status']}" for w in s.list()) or "no works"

    def show_work(self, work_id: str) -> str:
        """Show one derived work (its text, source lessons, redaction and sign-off) for review.
        :param work_id: the work id, e.g. song-egress-shared-path
        """
        _, review, _ = _load()
        return review.present(self._store("work").get(work_id))

    def check_work(self, work_id: str) -> str:
        """Run the checks on a derived work: schema, redaction, source lessons approved, sign-off rules.
        :param work_id: the work id
        """
        errs = self._store("work").verify(work_id)
        return "ok" if not errs else "errors:\n" + "\n".join(errs)

    async def approve_work(self, work_id: str, comment: str = "", __user__: dict = None, __event_call__=None) -> str:
        """Approve a derived work. Needs the logged-in person to confirm in a dialog.
        :param work_id: the work id
        :param comment: optional short comment from the assistant; stored separately and labelled as model-written
        """
        return await self._decide(work_id, "approved", comment, __user__, __event_call__, kind="work")

    async def reject_work(self, work_id: str, comment: str = "", __user__: dict = None, __event_call__=None) -> str:
        """Reject a derived work. Needs the logged-in person to confirm in a dialog.
        :param work_id: the work id
        :param comment: optional short comment from the assistant; stored separately and labelled as model-written
        """
        return await self._decide(work_id, "rejected", comment, __user__, __event_call__, kind="work")

    def list_records(self) -> str:
        """List lesson record ids with their sign-off status."""
        s = self._store()
        return "\n".join(f"{r}: {s.get(r)['signoff']['status']}" for r in s.list()) or "no records"

    def show_record(self, record_id: str) -> str:
        """Show one lesson record for review.
        :param record_id: the record id, e.g. history-mcp-schema-overhead
        """
        _, review, _ = _load()
        return review.present(self._store().get(record_id))

    def check_record(self, record_id: str) -> str:
        """Run the verify checks (schema, redaction by value, evidence refs, sign-off rules) on a record.
        :param record_id: the record id
        """
        _, review, verify = _load()
        errs, notes, _ = verify.verify_record(self._store().get(record_id), review.SCHEMA, record_id)
        return "ok" if not errs else "errors:\n" + "\n".join(errs)

    async def approve(self, record_id: str, comment: str = "", __user__: dict = None, __event_call__=None) -> str:
        """Approve a record. Needs the logged-in person to confirm in a dialog.
        :param record_id: the record id
        :param comment: optional short comment from the assistant; stored separately and labelled as model-written
        """
        return await self._decide(record_id, "approved", comment, __user__, __event_call__)

    async def reject(self, record_id: str, comment: str = "", __user__: dict = None, __event_call__=None) -> str:
        """Reject a record. Needs the logged-in person to confirm in a dialog.
        :param record_id: the record id
        :param comment: optional short comment from the assistant; stored separately and labelled as model-written
        """
        return await self._decide(record_id, "rejected", comment, __user__, __event_call__)

    async def _decide(self, record_id, status, comment, user, event_call, kind="record"):
        _, review, _ = _load()
        if event_call is None:
            return "refused: no confirmation dialog available"
        try:  # refuse before asking the person anything
            review.precheck(self._store() if kind == "record" else self._store(kind), record_id, status, (user or {}).get("name"), review.approvers_from_env())
        except review.ReviewError as e:
            return f"refused: {e}"
        answers = {}

        def ask(question):  # review.decide wants a sync callback; the dialog is async
            return answers.get("ok", False)

        # Ask first (async), then let review.decide run its checks with that answer.
        ok = await event_call({"type": "confirmation",
                               "data": {"title": "MC SOC sign-off", "message": f"{status.upper()} {record_id}?"}})
        answers["ok"] = bool(ok)
        note = ""
        if ok:  # the person's own words; skipped quietly if this Open WebUI has no input dialog
            try:
                typed = await event_call({"type": "input", "data": {
                    "title": "MC SOC sign-off note", "message": "Optional note (your words). Leave empty to skip.",
                    "placeholder": "why you approved or rejected"}})
                note = typed.strip() if isinstance(typed, str) else ""
            except Exception:
                note = ""
        try:
            review.decide(self._store() if kind == "record" else self._store(kind), record_id, status, (user or {}).get("name"), ask,
                          note, channel="chat", model_note=(comment or "").strip(),
                          approvers=review.approvers_from_env())
        except review.ReviewError as e:
            return f"refused: {e}"
        return f"{status}: {record_id}"
