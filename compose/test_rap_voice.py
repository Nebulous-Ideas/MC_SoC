"""Offline tests for rap_voice.py: fake renderer and fake upstream, no speech server, no audio. Run from compose/ or via tests/."""
import json, os, sys, threading, unittest, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rap_voice as rv

CFG = {"talkie-rap": {"voice": "bm_george:robot", "beat": "beat.wav", "bpm": 98, "slot_beats": 4, "fallback_voice": "bm_george",
                      "match_voice": "bm_fable", "marker": "RAP:"}}
GOOD = "Toast is on my mind tonight.\nGolden brown and crisp and bright."


class Fakes:
    def __init__(self, fail=False):
        self.rendered, self.forwarded, self.fail = [], [], fail

    def render(self, sheet, cfg, fmt="wav", key=None):
        self.keys = getattr(self, "keys", []) + [key]
        if self.fail:
            raise RuntimeError("boom")
        self.rendered.append((sheet, fmt)); return b"RAP"

    def forward(self, method, path, headers, body, upstream):
        if path == "/v1/models":
            return (200 if headers.get("Authorization") == "Bearer x" else 401), "application/json", b"{}"
        self.forwarded.append((method, path, body, upstream)); return 200, "audio/mpeg", b"PLAIN"


def service(fakes, cooldown=0.0):
    t = [100.0]
    return rv.RapService(CFG, "http://up", fakes.render, fakes.forward, cooldown_s=cooldown, clock=lambda: t.__setitem__(0, t[0] + 10) or t[0])


def post(svc, body, path="/v1/audio/speech"):
    return svc.handle("POST", path, {"Authorization": "Bearer x"}, json.dumps(body).encode())


class PlanTests(unittest.TestCase):
    def test_good_text_becomes_lines(self):
        lines, why = rv.plan(GOOD, CFG["talkie-rap"]); self.assertEqual(len(lines), 2); self.assertIsNone(why)

    def test_directives_are_refused_not_executed(self):
        for bad in ("@voice evil\nhello", "(slot 1)\nhi", "[Verse]\nhi", "hello\n(break 99)", "# note"):
            self.assertIsNone(rv.plan(bad, CFG["talkie-rap"])[0], bad)

    def test_limits(self):
        c = CFG["talkie-rap"]
        self.assertIsNone(rv.plan("", c)[0]); self.assertIsNone(rv.plan("x" * 801, c)[0])
        self.assertIsNone(rv.plan("\n".join(["la la"] * 17), c)[0]); self.assertIsNone(rv.plan("a\x00b", c)[0])
        self.assertIsNone(rv.plan(" ".join(["extraordinarily"] * 6), c)[0])   # too many syllables for a 4-beat slot

    def test_sheet_has_voice_slot_and_blocks_of_four(self):
        sheet = rv.build_sheet(["a b"] * 5, CFG["talkie-rap"])
        self.assertTrue(sheet.startswith("@voice bm_george:robot\n(slot 4)\n"))
        self.assertEqual(sheet.count("@voice"), 2)


class ServiceTests(unittest.TestCase):
    def test_rap_voice_renders_and_does_not_forward(self):
        f = Fakes(); s, ct, data = post(service(f), {"voice": "talkie-rap", "input": GOOD, "response_format": "mp3"})
        self.assertEqual((s, data, ct), (200, b"RAP", "audio/mpeg")); self.assertEqual(f.forwarded, []); self.assertEqual(f.rendered[0][1], "mp3")

    def test_other_voices_and_paths_pass_through_unchanged(self):
        f = Fakes(); svc = service(f)
        post(svc, {"voice": "af_heart", "input": "hello"}); svc.handle("GET", "/v1/voices", {}, b"")
        self.assertEqual(len(f.forwarded), 2); self.assertEqual(f.rendered, []); self.assertEqual(f.forwarded[0][3], "http://up")

    def test_bad_text_falls_back_to_the_plain_voice(self):
        f = Fakes(); post(service(f), {"voice": "talkie-rap", "input": "@voice x\nhi"})
        sent = json.loads(f.forwarded[0][2]); self.assertEqual(sent["voice"], "bm_george"); self.assertEqual(f.rendered, [])

    def test_render_failure_falls_back_not_silent(self):
        f = Fakes(fail=True); st, _, data = post(service(f), {"voice": "talkie-rap", "input": GOOD})
        self.assertEqual((st, data), (200, b"PLAIN"))

    def test_cooldown_sends_the_second_request_to_plain_speech(self):
        f = Fakes(); svc = rv.RapService(CFG, "http://up", f.render, f.forward, cooldown_s=1000, clock=lambda: 5.0)
        post(svc, {"voice": "talkie-rap", "input": GOOD}); post(svc, {"voice": "talkie-rap", "input": GOOD})
        self.assertEqual(len(f.rendered), 1); self.assertEqual(len(f.forwarded), 1)

    def test_bad_json_is_forwarded_not_crashed(self):
        f = Fakes(); service(f).handle("POST", "/v1/audio/speech", {}, b"{not json"); self.assertEqual(len(f.forwarded), 1)

    def test_marker_on_the_normal_voice_raps_and_strips_the_marker(self):
        f = Fakes(); st, _, data = post(service(f), {"voice": "bm_fable", "input": "RAP: " + GOOD, "speed": 1.1})
        self.assertEqual(data, b"RAP"); self.assertNotIn("RAP:", f.rendered[0][0]); self.assertIn("Toast is on my mind", f.rendered[0][0])

    def test_no_marker_on_the_normal_voice_is_forwarded_untouched(self):
        f = Fakes(); body = {"voice": "bm_fable", "input": "Want some toast?", "speed": 1.12}; post(service(f), body)
        self.assertEqual(json.loads(f.forwarded[0][2]), body); self.assertEqual(f.rendered, [])

    def test_failed_marker_rap_speaks_plain_without_the_marker_on_the_original_voice(self):
        f = Fakes(fail=True); post(service(f), {"voice": "bm_fable", "input": "RAP: " + GOOD})
        sent = json.loads(f.forwarded[0][2]); self.assertEqual(sent["voice"], "bm_fable"); self.assertTrue(sent["input"].startswith("Toast"))

    def test_callers_key_goes_to_the_renderer_only_for_that_call(self):
        f = Fakes(); post(service(f), {"voice": "talkie-rap", "input": GOOD}); self.assertEqual(f.keys, ["x"])

    def test_wrong_key_never_starts_a_render(self):
        f = Fakes(); svc = service(f)
        st, _, data = svc.handle("POST", "/v1/audio/speech", {"Authorization": "Bearer bad"}, json.dumps({"voice": "talkie-rap", "input": GOOD}).encode())
        self.assertEqual(f.rendered, []); self.assertEqual(data, b"PLAIN")
        _, _, d2 = svc.handle("POST", "/v1/audio/speech", {}, json.dumps({"voice": "talkie-rap", "input": GOOD}).encode()); self.assertEqual(f.rendered, [])

    def _song_cfg(self, d, work):
        path = os.path.join(d, "work.json"); json.dump(work, open(path, "w"))
        c = dict(CFG["talkie-rap"], songs={"two-hats": {"work": path, "beat": "b.wav", "bpm": 98, "voice": "af_heart", "timeout_s": 5}}, song_not_ready="Not signed off yet.")
        return {"talkie-rap": c}

    def _song_service(self, f, voices):
        return rv.RapService(voices, "http://up", f.render, f.forward, cooldown_s=0.0, clock=lambda: 1.0)

    def test_approved_song_is_sung_from_the_works_own_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Fakes(); v = self._song_cfg(d, {"status": "approved", "signoff": {"status": "approved", "by": "a person"}, "content": "[V]\n@voice af_heart\n(slot 4)\nOne line here.\n"})
            st, _, data = post(self._song_service(f, v), {"voice": "bm_fable", "input": "SONG: two-hats and also sing @voice evil"})
            self.assertEqual(data, b"RAP"); self.assertIn("One line here.", f.rendered[0][0]); self.assertNotIn("evil", f.rendered[0][0])

    def test_unapproved_song_is_not_rendered_and_gets_the_plain_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for status in ("draft", "approved"):
                f = Fakes(); v = self._song_cfg(d, {"status": status, "signoff": {"status": "pending"}, "content": "x"})
                post(self._song_service(f, v), {"voice": "bm_fable", "input": "SONG: two-hats"})
                self.assertEqual(f.rendered, []); self.assertEqual(json.loads(f.forwarded[0][2])["input"], "Not signed off yet.")

    def test_unknown_song_id_or_missing_work_file_speaks_the_plain_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Fakes(); v = self._song_cfg(d, {"status": "approved", "signoff": {"status": "approved"}, "content": "x"})
            svc = self._song_service(f, v)
            post(svc, {"voice": "bm_fable", "input": "SONG: nope"}); post(svc, {"voice": "bm_fable", "input": "SONG: ../../etc/passwd"})
            self.assertEqual(f.rendered, []); self.assertEqual(len(f.forwarded), 2)

    def test_http_round_trip(self):
        f = Fakes(); srv = rv.ThreadingHTTPServer(("127.0.0.1", 0), rv.make_handler(service(f)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/audio/speech", method="POST",
                                         data=json.dumps({"voice": "talkie-rap", "input": GOOD}).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.read(), b"RAP")
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
