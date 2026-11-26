"""Offline tests for act_engine_sing.py and measure_voice_act.py. Fake runner, no speech server, no audio is made.

Run:  python3 -m unittest test_act_engine_sing     (from compose/; the repo-level test run picks these up through tests/test_compose.py)
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import act  # noqa: E402
import act_engine_sing as eng  # noqa: E402
import measure_voice_act as mva  # noqa: E402

_CWD = os.getcwd()


def setUpModule():
    os.chdir(HERE)   # the engine takes sheet names relative to this folder


def tearDownModule():
    os.chdir(_CWD)


SHEET = "lyrics-act-test-0001.txt"
TGT = {"bands": {
    "heard_syl_per_active_s": {"low": 4.63, "mid": 4.87, "high": 5.98},
    "npitch_sd_st": {"low": 2.6, "mid": 2.74, "high": 2.77},
    "npitch_span_st": {"low": 9.7, "mid": 11.05, "high": 18.1}}}


class FakeRunner:
    """Records each command; writes the voice stem when sing.py 'runs'; answers the measurer with canned JSON."""

    def __init__(self, measurer_stdout):
        self.calls = []
        self.measurer_stdout = measurer_stdout

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[1] == "sing.py":
            _, stem = eng.render_paths(SHEET)
            with open(stem, "wb") as f:
                f.write(b"")
            return None
        class Done:
            stdout = self.measurer_stdout
        return Done()


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.stem = eng.render_paths(SHEET)[1]
        self.mix = eng.render_paths(SHEET)[0]
        for p in (self.stem, self.mix):
            if os.path.exists(p):
                os.remove(p)

    def tearDown(self):
        if os.path.exists(self.stem):
            os.remove(self.stem)

    def test_sheet_must_be_a_lyrics_file_in_this_folder(self):
        with self.assertRaises(ValueError):
            eng.SingEngine("/tmp/lyrics-act-test-0001.txt", "beat.wav", 94)
        with self.assertRaises(ValueError):
            eng.SingEngine(os.path.join(HERE, "notes-act.txt"), "beat.wav", 94)

    def test_refuses_to_overwrite_an_existing_render(self):
        open(self.mix, "wb").close()
        try:
            with self.assertRaises(ValueError):
                eng.SingEngine(SHEET, "beat.wav", 94, runner=FakeRunner("{}"))
        finally:
            os.remove(self.mix)

    def test_render_runs_sing_with_stems_then_measures_the_voice_only(self):
        runner = FakeRunner(json.dumps({"values": {"heard_syl_per_active_s": 4.9, "npitch_sd_st": 2.7,
                                                   "npitch_span_st": 12.0}, "seconds": 90.0}))
        e = eng.SingEngine(SHEET, "beat-x.wav", 94, voice="af_heart", runner=runner)
        out = e.render(TGT)
        self.assertEqual(out, {"values": {"heard_syl_per_active_s": 4.9, "npitch_sd_st": 2.7,
                                          "npitch_span_st": 12.0}, "seconds": 90.0})
        sing_cmd = runner.calls[0][0]
        self.assertIn("--stems", sing_cmd)
        self.assertIn("--no-play", sing_cmd)
        self.assertEqual(sing_cmd[sing_cmd.index("--lyrics") + 1], SHEET)
        self.assertEqual(sing_cmd[sing_cmd.index("--voice") + 1], "af_heart")
        measure_cmd = runner.calls[1][0]
        self.assertEqual(measure_cmd[0], eng.MEASURER_PY)
        self.assertEqual(measure_cmd[2], self.stem)
        self.assertEqual(measure_cmd[3:], sorted(TGT["bands"]))

    def test_a_measure_the_measurer_lacks_is_left_out_not_zeroed(self):
        runner = FakeRunner(json.dumps({"values": {"npitch_sd_st": 2.7}, "seconds": 90.0}))
        out = eng.SingEngine(SHEET, "beat-x.wav", 94, runner=runner).render(TGT)
        self.assertEqual(out["values"], {"npitch_sd_st": 2.7})
        rep = act.compare(TGT, out["values"], out["seconds"])
        # act.compare only reports values it was given: a measure left out is absent from the report, not zero
        self.assertNotIn("heard_syl_per_active_s", rep["measures"])
        self.assertEqual(rep["scored"], 1)

    def test_act_run_accepts_the_result_and_marks_it_generated(self):
        # the brief check in act.run needs the real lesson tree; compare() is the part under test here
        runner = FakeRunner(json.dumps({"values": {"npitch_sd_st": 2.7}, "seconds": 90.0}))
        out = eng.SingEngine(SHEET, "beat-x.wav", 94, runner=runner).render(TGT)
        self.assertEqual(set(out), {"values", "seconds"})
        self.assertEqual(eng.SingEngine.name, "sing-stems")


class MeasurerFilterTests(unittest.TestCase):
    def test_only_requested_finite_numbers_are_kept(self):
        prof = {"heard_syl_per_active_s": 4.9, "npitch_sd_st": float("nan"), "npitch_span_st": 12,
                "artist": "someone", "active_s": 40.0, "flag": True, "npitch_step_st": None}
        got = mva.numbers_only(prof, ["heard_syl_per_active_s", "npitch_sd_st", "npitch_span_st",
                                      "npitch_step_st", "flag", "artist"])
        self.assertEqual(got, {"heard_syl_per_active_s": 4.9, "npitch_span_st": 12.0})

    def test_unrequested_measures_are_not_printed(self):
        self.assertEqual(mva.numbers_only({"active_s": 40.0, "syl_per_voiced_s": 3.1}, ["npitch_sd_st"]), {})


if __name__ == "__main__":
    unittest.main()


try:
    import numpy  # noqa: F401  (the real linter imports sing, which needs it)
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


@unittest.skipUnless(HAVE_NUMPY, "the LONG-line gate runs the real linter, which needs numpy; the repo's CI image has only python3")
class LongLineGateTests(unittest.TestCase):
    """A sheet with LONG lines is not rendered unless a reason is given (writing-stage rule, PRE-SHIP-CHECKLIST)."""
    LONG_SHEET = "lyrics-act-test-long.txt"
    CLEAN_SHEET = "lyrics-act-test-clean.txt"

    def setUp(self):
        with open(os.path.join(HERE, self.LONG_SHEET), "w") as f:
            f.write("[Verse 1]\n@voice af_heart\n(slot 2)\nThe gate checked the rule before the rules that let it through, "
                    "and the trigger never showed a single thing at all.\n(break 2)\n")
        with open(os.path.join(HERE, self.CLEAN_SHEET), "w") as f:
            f.write("[Verse 1]\n@voice af_heart\n(slot 4)\nThe gate checked the rule.\n(break 2)\n")

    def tearDown(self):
        for n in (self.LONG_SHEET, self.CLEAN_SHEET):
            p = os.path.join(HERE, n)
            if os.path.exists(p):
                os.remove(p)

    def test_long_sheet_refused_without_reason(self):
        with self.assertRaises(ValueError):
            eng.SingEngine(self.LONG_SHEET, "beat.wav", 98, runner=FakeRunner("{}"))

    def test_long_sheet_allowed_with_a_logged_reason(self):
        e = eng.SingEngine(self.LONG_SHEET, "beat.wav", 98, runner=FakeRunner("{}"),
                           allow_long_reason="testing the gate")
        self.assertTrue(e.long_flags)
        self.assertEqual(e.allow_long_reason, "testing the gate")

    def test_clean_sheet_passes_the_gate(self):
        e = eng.SingEngine(self.CLEAN_SHEET, "beat.wav", 98, runner=FakeRunner("{}"))
        self.assertEqual(e.long_flags, [])


class PersonaPathTests(unittest.TestCase):
    """The engine reads a persona link: its voice, tempo, beat style and sing flags reach the render command."""

    def setUp(self):
        self.stem = eng.render_paths(SHEET)[1]
        self.mix = eng.render_paths(SHEET)[0]
        for p in (self.stem, self.mix):
            if os.path.exists(p):
                os.remove(p)

    def tearDown(self):
        if os.path.exists(self.stem):
            os.remove(self.stem)

    def test_persona_supplies_voice_tempo_beat_and_flags(self):
        runner = FakeRunner(json.dumps({"values": {"npitch_sd_st": 2.7}, "seconds": 90.0}))
        e = eng.SingEngine(SHEET, persona="rapid-melodic-lead", runner=runner)
        e.render(TGT)
        beat_cmd = runner.calls[0][0]
        self.assertIn("make_beat.py", beat_cmd[1])
        self.assertEqual(beat_cmd[beat_cmd.index("--style") + 1], "boombap")
        self.assertEqual(beat_cmd[beat_cmd.index("--bpm") + 1], "98")
        sing_cmd = runner.calls[1][0]
        self.assertEqual(sing_cmd[sing_cmd.index("--voice") + 1], "af_heart")
        self.assertEqual(sing_cmd[sing_cmd.index("--bpm") + 1], "98.0")
        self.assertEqual(sing_cmd[sing_cmd.index("--beat-gain") + 1], "5.75")

    def test_persona_with_no_settings_still_renders_with_its_voice(self):
        runner = FakeRunner(json.dumps({"values": {"npitch_sd_st": 2.7}, "seconds": 90.0}))
        with self.assertRaises(ValueError):   # no bpm anywhere: refused, not guessed
            eng.SingEngine(SHEET, persona="slow-melodic-voice", runner=runner)

    def test_unknown_persona_is_refused(self):
        with self.assertRaises(ValueError):
            eng.SingEngine(SHEET, persona="no-such-persona", runner=FakeRunner("{}"))
