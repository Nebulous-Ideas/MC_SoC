"""Memory adapters for MC SOC. Stdlib only.

The core sees one interface:  list() -> [id], get(id) -> record, put(record) -> memory_ref
Implementations: FileMemory (a directory of JSON, also the local cache) and
OutlineMemory (records stored as a JSON code block in one Outline doc each).

Outline auth: OUTLINE_URL (e.g. https://outline.example) and OUTLINE_API_TOKEN come
from the environment only. They are never read from or written to a file here.

Sign-off rule: approval is set by a person in the memory system. Pull carries it
into the cache; push refuses to change a remote signoff, so a local run can never
approve anything.
"""
import json, os, re, urllib.request, urllib.error

BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)


class FileMemory:
    def __init__(self, directory):
        self.dir = directory

    def _path(self, rid):
        return os.path.join(self.dir, rid + ".json")

    def list(self):
        return sorted(f[:-5] for f in os.listdir(self.dir) if f.endswith(".json"))

    def get(self, rid):
        with open(self._path(rid)) as f:
            return json.load(f)

    def put(self, record):
        os.makedirs(self.dir, exist_ok=True)
        with open(self._path(record["id"]), "w") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
        return record.get("memory_ref")

    def set_signoff(self, rid, signoff, extra=None):
        self.put(_with_signoff(self.get(rid), signoff, extra))


def _with_signoff(record, signoff, extra=None):
    out = dict(record)
    out["signoff"] = signoff
    out.update(extra or {})
    return out


def render_doc(record):
    """Outline doc body for a record (first line is a human note, then the JSON)."""
    status = record["signoff"]["status"]
    return ("Lesson record (schema v%s). Sign-off: %s. Comment here to discuss; a person sets "
            "`signoff` below when approving.\n\n```json\n%s\n```\n"
            % (record["schema_version"], status, json.dumps(record, indent=2)))


def parse_doc(text):
    m = BLOCK.search(text)
    if not m:
        raise ValueError("no ```json block in document")
    return json.loads(m.group(1))


class OutlineMemory:
    def __init__(self, collection_id, base_url=None, token=None, post=None):
        self.collection_id = collection_id
        self.base = (base_url or os.environ.get("OUTLINE_URL", "")).rstrip("/")
        self._token = token or os.environ.get("OUTLINE_API_TOKEN", "")
        self._post_fn = post  # injectable for tests
        if not post and not (self.base and self._token):
            raise RuntimeError("set OUTLINE_URL and OUTLINE_API_TOKEN in the environment")

    def _post(self, endpoint, body):
        if self._post_fn:
            return self._post_fn(endpoint, body)
        req = urllib.request.Request(
            f"{self.base}/api/{endpoint}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._token})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Outline {endpoint} -> HTTP {e.code}") from None  # no body: may echo secrets

    def _docs(self):
        out, offset = [], 0
        while True:
            r = self._post("documents.list", {"collectionId": self.collection_id, "limit": 100, "offset": offset})
            out += r["data"]
            if len(r["data"]) < 100:
                return out
            offset += 100

    def list(self):
        return sorted(d["title"] for d in self._docs())

    def get(self, rid):
        for d in self._docs():
            if d["title"] == rid:
                rec = parse_doc(d["text"])
                rec.setdefault("memory_ref", "outline:" + d["id"])
                return rec
        raise KeyError(rid)

    def put(self, record):
        ref = record.get("memory_ref", "")
        if ref.startswith("outline:"):
            doc_id = ref[len("outline:"):]
            remote = parse_doc(self._post("documents.info", {"id": doc_id})["data"]["text"])
            if remote.get("signoff") != record.get("signoff"):
                raise PermissionError("remote signoff differs from local; sign-off is changed only in the memory system (pull first)")
            self._post("documents.update", {"id": doc_id, "text": render_doc(record)})
            return ref
        r = self._post("documents.create", {"title": record["id"], "text": render_doc(record),
                                            "collectionId": self.collection_id, "publish": True})
        return "outline:" + r["data"]["id"]


def _outline_set_signoff(self, rid, signoff, extra=None):
    """The ONLY write path for sign-off. Called by review.py after a human confirmation."""
    for d in self._docs():
        if d["title"] == rid:
            rec = parse_doc(d["text"])
            self._post("documents.update", {"id": d["id"], "text": render_doc(_with_signoff(rec, signoff, extra))})
            return
    raise KeyError(rid)


OutlineMemory.set_signoff = _outline_set_signoff


def pull(remote, cache, force=False):
    """Remote -> cache (remote is canonical). Without force, refuses to overwrite a cache
    record whose non-sign-off content differs from remote (a local edit not yet pushed)."""
    def body(r):
        return {k: v for k, v in r.items() if k != "signoff"}
    changed = []
    for rid in remote.list():
        rec = remote.get(rid)
        try:
            local = cache.get(rid)
        except FileNotFoundError:
            local = None
        if local == rec:
            continue
        if local is not None and not force and body(local) != body(rec):
            raise RuntimeError(f"{rid}: local edits would be overwritten; push them or use --force")
        cache.put(rec)
        changed.append(rid)
    return changed


def push(cache, remote):
    """Cache -> remote, one record at a time. Returns ids pushed."""
    pushed = []
    for rid in cache.list():
        rec = cache.get(rid)
        ref = remote.put(rec)
        if rec.get("memory_ref") != ref:
            rec["memory_ref"] = ref
            cache.put(rec)
        pushed.append(rid)
    return pushed


class WorksStore:
    """Derived works over any memory adapter (FileMemory or OutlineMemory, one collection each).

    lessons: a memory adapter holding lesson records; a work may name only approved, verify-clean lessons.
    set_signoff is delegated to the adapter's own sign-off write, and approving also sets status to approved.
    Sign-off is still written only through review.decide.
    """
    def __init__(self, base, lessons):
        self.base = base
        self.lessons = lessons

    def list(self):
        return self.base.list()

    def get(self, rid):
        return self.base.get(rid)

    def put(self, work):
        return self.base.put(work)

    def set_signoff(self, rid, signoff):
        extra = {"status": "approved"} if signoff.get("status") == "approved" else None
        self.base.set_signoff(rid, signoff, extra)

    def verify(self, rid):
        """Verify-derived errors for one work, against the lesson records it names. Used by review.precheck."""
        import verify as V
        from pathlib import Path
        here = Path(__file__).resolve().parent
        schema = json.loads((here / "schema" / "derived-work.schema.json").read_text())
        lessons = {lid: self.lessons.get(lid) for lid in self.lessons.list()}
        work = {k: v for k, v in self.get(rid).items() if k != "memory_ref"}  # the adapter's pointer, not part of the work
        errs = V.verify_derived(work, schema, rid, lessons)
        # verify_derived checks redaction only for works already marked approved; this one is about to be
        if work.get("redaction", {}).get("status") != "passed":
            errs.append("approval: redaction has not passed")
        return errs


def FileWorks(directory, lessons):
    """Derived works in a folder of JSON (works/). Used by the CLI and the tests."""
    return WorksStore(FileMemory(directory), lessons)


def OutlineWorks(collection_id, lessons, **kw):
    """Derived works in an Outline collection, one document each, as lesson records are."""
    return WorksStore(OutlineMemory(collection_id, **kw), lessons)
