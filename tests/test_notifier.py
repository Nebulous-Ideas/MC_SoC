import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import notifier


class T(unittest.TestCase):
    def test_off_by_default(self):
        called = []
        self.assertFalse(notifier.emit("signoff", "x: approved", env={}, run=lambda *a, **k: called.append(1)))
        self.assertEqual(called, [])

    def test_sends_only_event_fields_to_hub(self):
        seen = {}
        class R: returncode = 0
        def run(cmd, input, **k):
            seen["cmd"], seen["ev"] = cmd, json.loads(input); return R()
        ok = notifier.emit("signoff", "rec-1: approved", env={"NOTIFY_HUB": "/hub", "NOTIFY_ROUTES": "/r.json"}, run=run)
        self.assertTrue(ok)
        self.assertEqual(seen["ev"], {"system": "mc-soc", "kind": "signoff", "severity": "info", "title": "rec-1: approved"})
        self.assertIn("/hub/notify.py", seen["cmd"]); self.assertIn("-I", seen["cmd"])

    def test_failure_never_raises(self):
        def boom(*a, **k): raise OSError("no hub")
        self.assertFalse(notifier.emit("signoff", "t", env={"NOTIFY_HUB": "/hub"}, run=boom))


if __name__ == "__main__":
    unittest.main()
