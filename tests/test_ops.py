import http.server, json, os, sys, tempfile, threading, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ops_check

class H(http.server.BaseHTTPRequestHandler):
    seen_auth = []
    def do_GET(self):
        H.seen_auth.append(self.headers.get("Authorization"))
        self.send_response(404 if self.path == "/missing" else 200); self.end_headers()
    def log_message(self, *a): pass

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H); cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def r(self, checks): return {c["name"]: c for c in ops_check.run({"checks": checks})}

    def test_http_tcp_disk_env(self):
        os.environ["OPS_T_SET"] = "x"; os.environ.pop("OPS_T_UNSET", None)
        r = self.r([
            {"name": "up", "type": "http", "url": f"http://127.0.0.1:{self.port}/"},
            {"name": "gone", "type": "http", "url": f"http://127.0.0.1:{self.port}/missing"},
            {"name": "down", "type": "http", "url": "http://127.0.0.1:1/", "timeout": 1},
            {"name": "port", "type": "tcp", "host": "127.0.0.1", "port": self.port},
            {"name": "port-closed", "type": "tcp", "host": "127.0.0.1", "port": 1, "timeout": 1},
            {"name": "disk", "type": "disk", "path": "/", "max_used_pct": 100},
            {"name": "disk-full", "type": "disk", "path": "/", "max_used_pct": -1},
            {"name": "env-ok", "type": "env", "names": ["OPS_T_SET"]},
            {"name": "env-bad", "type": "env", "names": ["OPS_T_SET", "OPS_T_UNSET"]}])
        got = {k: v["status"] for k, v in r.items()}
        self.assertEqual(got, {"up": "ok", "gone": "fail", "down": "fail", "port": "ok", "port-closed": "fail",
                               "disk": "ok", "disk-full": "fail", "env-ok": "ok", "env-bad": "fail"})
        self.assertEqual(r["env-bad"]["detail"], "unset: OPS_T_UNSET")

    def test_bearer_never_echoed_and_skipped_when_unset(self):
        os.environ["OPS_T_TOKEN"] = "sekrit-value-123"; os.environ.pop("OPS_T_NOTOKEN", None)
        r = self.r([{"name": "a", "type": "http", "url": f"http://127.0.0.1:{self.port}/", "bearer_env": "OPS_T_TOKEN"},
                    {"name": "b", "type": "http", "url": f"http://127.0.0.1:{self.port}/", "bearer_env": "OPS_T_NOTOKEN"}])
        self.assertEqual((r["a"]["status"], r["b"]["status"]), ("ok", "skip"))
        self.assertIn("Bearer sekrit-value-123", H.seen_auth)
        self.assertNotIn("sekrit", json.dumps(r))

    def test_verify_and_exit_code(self):
        r = self.r([{"name": "v", "type": "verify", "root": str(ROOT)}]); self.assertEqual(r["v"]["status"], "ok")
        d = Path(tempfile.mkdtemp()); cfg = d / "c.json"
        cfg.write_text(json.dumps({"checks": [{"name": "optional", "type": "tcp", "host": "127.0.0.1", "port": 1, "timeout": 1, "required": False}]}))
        sys.argv = ["x", "--config", str(cfg)]; self.assertEqual(ops_check.main(), 0)
        cfg.write_text(json.dumps({"checks": [{"name": "must", "type": "tcp", "host": "127.0.0.1", "port": 1, "timeout": 1}]}))
        self.assertEqual(ops_check.main(), 1)

if __name__ == "__main__":
    unittest.main()
