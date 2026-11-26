import copy, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import memory

REC = json.loads((ROOT / "records" / "history-mcp-schema-overhead.json").read_text())
REC["signoff"] = {"status": "pending"}  # fixture must not depend on the live record's sign-off

class FakeOutline:
    """Just enough of the Outline API for the adapter."""
    def __init__(self):
        self.docs, self.n = {}, 0
        self.calls = []
    def __call__(self, ep, body):
        self.calls.append(ep)
        if ep == "documents.list":
            return {"data": [dict(d) for d in self.docs.values()]}
        if ep == "documents.info":
            return {"data": dict(self.docs[body["id"]])}
        if ep == "documents.update":
            self.docs[body["id"]]["text"] = body["text"]; return {"data": {}}
        if ep == "documents.create":
            self.n += 1; i = "doc%d" % self.n
            self.docs[i] = {"id": i, "title": body["title"], "text": body["text"]}
            return {"data": {"id": i}}
        raise AssertionError(ep)

class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = memory.FileMemory(self.tmp.name)
        self.fake = FakeOutline()
        self.remote = memory.OutlineMemory("c1", post=self.fake)
    def tearDown(self): self.tmp.cleanup()

    def test_roundtrip_render_parse(self):
        self.assertEqual(memory.parse_doc(memory.render_doc(REC)), REC)

    def test_push_creates_then_pull_matches(self):
        r = copy.deepcopy(REC); r.pop("memory_ref", None)
        self.cache.put(r)
        self.assertEqual(memory.push(self.cache, self.remote), [r["id"]])
        self.assertTrue(self.cache.get(r["id"])["memory_ref"].startswith("outline:"))
        other = memory.FileMemory(tempfile.mkdtemp())
        self.assertEqual(memory.pull(self.remote, other), [r["id"]])
        self.assertEqual(other.get(r["id"]), self.cache.get(r["id"]))

    def test_push_cannot_approve(self):
        self.cache.put(copy.deepcopy(REC)); r = self.cache.get(REC["id"])
        r.pop("memory_ref"); self.cache.put(r); memory.push(self.cache, self.remote)
        r = self.cache.get(REC["id"])
        r["signoff"] = {"status": "approved", "by": "x", "at": "2026-11-11T12:00:00Z", "channel": "chat"}
        self.cache.put(r)
        with self.assertRaises(PermissionError):
            memory.push(self.cache, self.remote)

    def test_pull_carries_remote_signoff_and_protects_local_edits(self):
        r = copy.deepcopy(REC); r.pop("memory_ref", None); self.cache.put(r)
        memory.push(self.cache, self.remote)
        doc = next(iter(self.fake.docs.values()))
        remote_rec = memory.parse_doc(doc["text"])
        remote_rec["signoff"] = {"status": "approved", "by": "alex", "at": "2026-11-11T12:00:00Z", "channel": "memory-system"}
        doc["text"] = memory.render_doc(remote_rec)
        self.assertEqual(memory.pull(self.remote, self.cache), [r["id"]])
        self.assertEqual(self.cache.get(r["id"])["signoff"]["by"], "alex")
        local = self.cache.get(r["id"]); local["lesson"] = "edited locally"; self.cache.put(local)
        with self.assertRaises(RuntimeError):
            memory.pull(self.remote, self.cache)

    def test_missing_env_is_error(self):
        with self.assertRaises(RuntimeError):
            memory.OutlineMemory("c1", base_url="", token="")

if __name__ == "__main__":
    unittest.main()
