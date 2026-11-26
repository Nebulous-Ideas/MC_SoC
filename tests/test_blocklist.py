import csv, json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from incident import blocklist as B

class Resp:
    def __init__(self, text): self.t = text.encode()
    def read(self, n=-1): return self.t if n < 0 else self.t[:n]
    def __enter__(self): return self
    def __exit__(self, *a): pass

def opener(bodies):
    def f(req, timeout=0): return Resp(bodies[req.full_url])
    return f

FEED = "# comment\n198.51.100.7\n203.0.113.0/28 ; sbl\n0.0.0.0 Bad.Example.org\n10.0.0.5\n127.0.0.1\n192.0.2.0/8\nnot a thing\nbad.example.org\n"
DAY = 86400.0 * 20000

class ParseTests(unittest.TestCase):
    def test_valid_forms_and_refusals(self):
        e, skipped = B.parse_feed(FEED)
        kinds = {x for x in e}
        self.assertIn(("ip", "198.51.100.7"), kinds); self.assertIn(("cidr", "203.0.113.0/28"), kinds); self.assertIn(("domain", "bad.example.org"), kinds)
        self.assertNotIn(("ip", "10.0.0.5"), kinds); self.assertNotIn(("ip", "127.0.0.1"), kinds)
        self.assertTrue(all("/8" not in v for _, v in kinds))
        self.assertGreaterEqual(skipped, 3)

    def test_allowlist_drops_addresses_ranges_and_subdomains(self):
        e, _ = B.parse_feed("198.51.100.7\n203.0.113.9\nx.cdn.example.org\nother.example.net\n", allow=["198.51.100.0/24", "cdn.example.org"])
        self.assertEqual(sorted(e), [("domain", "other.example.net"), ("ip", "203.0.113.9")])

    def test_csv_column(self):
        e, _ = B.parse_feed("id,addr\n1,198.51.100.7\n2,10.1.1.1\n", kind="csv:1")
        self.assertEqual(e, [("ip", "198.51.100.7")])

    def test_single_host_range_becomes_an_address_and_wide_ranges_are_refused(self):
        self.assertEqual(B.classify("198.51.100.7/32"), ("ip", "198.51.100.7"))
        self.assertIsNone(B.classify("198.51.0.0/15"))

class BuildTests(unittest.TestCase):
    def cfg(self, d, **kw):
        c = {"out_dir": d, "feeds": [{"name": "feed-a", "url": "https://feeds.example.org/a.txt"}]}; c.update(kw); return c

    def read(self, d, name):
        with open(os.path.join(d, name), newline="") as f: return list(csv.DictReader(f)) if name.endswith(".csv") else f.read()

    def test_writes_three_files_and_keeps_first_seen(self):
        with tempfile.TemporaryDirectory() as d:
            op = opener({"https://feeds.example.org/a.txt": FEED})
            r = B.build(self.cfg(d), op, now=DAY)
            self.assertIsNone(r["feed-a"]["error"])
            rows = self.read(d, "blocklist_ip.csv"); self.assertEqual(rows[0]["key"], "198.51.100.7"); first = rows[0]["first_seen"]
            self.assertIn("203.0.113.0/28,feed-a", self.read(d, "blocklist_cidr.txt"))
            B.build(self.cfg(d), op, now=DAY + 3 * 86400)
            self.assertEqual(self.read(d, "blocklist_ip.csv")[0]["first_seen"], first)

    def test_shrink_guard_keeps_the_previous_list(self):
        with tempfile.TemporaryDirectory() as d:
            big = "".join(f"198.51.100.{i}\n" for i in range(1, 21))
            B.build(self.cfg(d), opener({"https://feeds.example.org/a.txt": big}), now=DAY)
            r = B.build(self.cfg(d), opener({"https://feeds.example.org/a.txt": "198.51.100.1\n"}), now=DAY + 86400)
            self.assertTrue(r["feed-a"]["kept_previous"]); self.assertEqual(len(self.read(d, "blocklist_ip.csv")), 20)

    def test_entries_age_out(self):
        with tempfile.TemporaryDirectory() as d:
            B.build(self.cfg(d, max_age_days=10), opener({"https://feeds.example.org/a.txt": "198.51.100.7\n"}), now=DAY)
            B.build(self.cfg(d, max_age_days=10, feeds=[{"name": "feed-a", "url": "https://feeds.example.org/b.txt"}]),
                    opener({"https://feeds.example.org/b.txt": "198.51.100.8\n"}), now=DAY + 30 * 86400)
            self.assertEqual([r["key"] for r in self.read(d, "blocklist_ip.csv")], ["198.51.100.8"])

    def test_http_url_oversize_feed_and_bad_name_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            r = B.build(self.cfg(d, feeds=[{"name": "a", "url": "http://feeds.example.org/a.txt"}]), opener({}), now=DAY)
            self.assertIn("https", r["a"]["error"])
            r = B.build(self.cfg(d, feeds=[{"name": "a", "url": "https://feeds.example.org/a.txt"}]), opener({"https://feeds.example.org/a.txt": "x" * (B.MAX_BYTES + 10)}), now=DAY)
            self.assertIn("size cap", r["a"]["error"])
            with self.assertRaises(B.BlocklistError): B.build(self.cfg(d, feeds=[{"name": "a,b\n", "url": "https://feeds.example.org/a.txt"}]), opener({}), now=DAY)

    def test_one_failing_feed_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as d:
            feeds = [{"name": "bad", "url": "https://feeds.example.org/missing.txt"}, {"name": "ok", "url": "https://feeds.example.org/a.txt"}]
            r = B.build(self.cfg(d, feeds=feeds), opener({"https://feeds.example.org/a.txt": "198.51.100.7\n"}), now=DAY)
            self.assertTrue(r["bad"]["error"]); self.assertIsNone(r["ok"]["error"])
            self.assertEqual(self.read(d, "blocklist_ip.csv")[0]["list"], "ok")

if __name__ == "__main__":
    unittest.main()
