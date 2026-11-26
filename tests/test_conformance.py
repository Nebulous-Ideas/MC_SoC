"""The shipped review surfaces run the shared contract; a deliberately broken one must fail it."""
import asyncio, io, os, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import review, openmole_tool
from conformance import ReviewSurfaceContract


class CliSurface(ReviewSurfaceContract, unittest.TestCase):
    """review.decide, the routine the CLI calls."""
    def act(self, store, rid, status, who, confirm, approvers):
        try:
            review.decide(store, rid, status, who, confirm, channel="cli", approvers=approvers)
        except review.ReviewError:
            return False
        return True


class OpenMoleSurface(ReviewSurfaceContract, unittest.TestCase):
    """The Open WebUI tool: identity from __user__, confirmation from a dialog."""
    def act(self, store, rid, status, who, confirm, approvers):
        t = openmole_tool.Tools(); t._store = lambda: store
        async def dialog(ev):
            return confirm(ev["data"]["message"]) if ev["type"] == "confirmation" else ""
        old = os.environ.get("MCSOC_APPROVERS")
        if approvers is None: os.environ.pop("MCSOC_APPROVERS", None)
        else: os.environ["MCSOC_APPROVERS"] = ",".join(approvers)
        try:
            call = t.approve if status == "approved" else t.reject
            out = asyncio.run(call(rid, __user__={"name": who} if who is not None else {}, __event_call__=dialog))
        finally:
            if old is None: os.environ.pop("MCSOC_APPROVERS", None)
            else: os.environ["MCSOC_APPROVERS"] = old
        return not out.startswith("refused")


class BrokenSurface(ReviewSurfaceContract, unittest.TestCase):
    """Trusts a model-supplied name, skips verify and the allow-list, and writes without asking."""
    def act(self, store, rid, status, who, confirm, approvers):
        store.set_signoff(rid, {"status": status, "by": who or "someone", "channel": "x", "at": "2026-01-01T00:00:00Z"})
        return True


class ContractCatchesBrokenSurface(unittest.TestCase):
    def test_broken_surface_fails_the_contract(self):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(_BROKEN[0])
        res = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        self.assertFalse(res.wasSuccessful())
        self.assertGreaterEqual(len(res.failures) + len(res.errors), 5)


# the broken surface exists only to be run by the test above, never as a normal test
_BROKEN = [BrokenSurface]  # in a list so test discovery does not collect it
del BrokenSurface

if __name__ == "__main__":
    unittest.main()
