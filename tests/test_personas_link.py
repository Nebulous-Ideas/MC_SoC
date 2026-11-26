"""Persona links: each link names an existing voice card, and its settings use only the allowed keys. Offline."""
import json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import personas_link as PL  # noqa: E402

CARDS = {"rapid-melodic": "voice", "slow-melodic": "voice", "fast-straight": "beat"}
GOOD = {"schema_version": 1, "id": "x", "voice": "af_heart", "card": "rapid-melodic", "beat": None,
        "settings": {"bpm": 98, "beat_style": "boombap", "sing": ["--beat-gain", "5.75"]}, "note": "n"}


class LinkTests(unittest.TestCase):
    def test_the_starter_links_pass(self):
        links, errors = PL.load_all()
        self.assertEqual(errors, {})
        self.assertIn("rapid-melodic-lead", links)
        self.assertIn("slow-melodic-voice", links)

    def test_a_good_link_passes(self):
        self.assertEqual(PL.check(GOOD, "x", CARDS), [])

    def test_unknown_card_or_beat_card_as_voice_is_refused(self):
        self.assertTrue(PL.check(dict(GOOD, card="nope"), "x", CARDS))
        self.assertTrue(PL.check(dict(GOOD, card="fast-straight"), "x", CARDS))

    def test_id_must_match_the_file(self):
        self.assertTrue(PL.check(GOOD, "other", CARDS))

    def test_voice_must_be_a_kokoro_name(self):
        self.assertTrue(PL.check(dict(GOOD, voice="Alice Smith"), "x", CARDS))

    def test_settings_allow_only_known_keys_and_types(self):
        self.assertTrue(PL.check(dict(GOOD, settings={"reference": "a track"}), "x", CARDS))
        self.assertTrue(PL.check(dict(GOOD, settings={"bpm": "98"}), "x", CARDS))
        self.assertTrue(PL.check(dict(GOOD, settings={"beat_style": "polka"}), "x", CARDS))
        self.assertTrue(PL.check(dict(GOOD, settings={"sing": [1, 2]}), "x", CARDS))

    def test_no_extra_fields(self):
        self.assertTrue(PL.check(dict(GOOD, artist="someone"), "x", CARDS))


if __name__ == "__main__":
    unittest.main()
