"""Crate maker: the sampler applies the declared rules, refuses thin sides, and the example runs end to end. Offline."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import crate_maker.sample as S  # noqa: E402

EX = HERE / "crate_maker" / "example"


def rules(**over):
    base = {"seed": 7, "min_seconds": 120, "max_seconds": 360, "max_per_artist": 3, "min_artists": 2,
            "require_tags": [], "exclude_tags": ["live"], "sides": {"s1": {"tags_all": ["spoken"]}, "s2": {"tags_all": ["sung"]}}}
    base.update(over)
    return base


class SamplerTests(unittest.TestCase):
    def setUp(self):
        self.rows = S.load_library(EX / "library.tsv")

    def test_the_example_sample_matches_the_rules(self):
        picked, counts = S.sample(self.rows, dict(S.DEFAULTS, **rules()))
        self.assertEqual(counts, {"s1": {"tracks": 9, "artists": 3}, "s2": {"tracks": 9, "artists": 3}})
        self.assertFalse(any(r["tags"] & {"live"} for _, r in picked))             # excluded by tag
        self.assertFalse(any(r["seconds"] < 120 for _, r in picked))                # outside the window

    def test_the_cap_and_the_seed_are_respected(self):
        r = dict(S.DEFAULTS, **rules(max_per_artist=1))
        _, counts = S.sample(self.rows, r)
        self.assertTrue(all(c["tracks"] == c["artists"] for c in counts.values()))
        a = S.sample(self.rows, dict(S.DEFAULTS, **rules()))[0]
        b = S.sample(self.rows, dict(S.DEFAULTS, **rules()))[0]
        self.assertEqual([x[1]["title"] + x[1]["artist"] for x in a], [x[1]["title"] + x[1]["artist"] for x in b])

    def test_a_side_with_too_few_artists_is_refused(self):
        thin = dict(S.DEFAULTS, **rules(sides={"s1": {"tags_all": ["spoken"]}, "s2": {"tags_all": ["live"]}}, min_artists=2))
        with self.assertRaises(ValueError):
            S.sample(self.rows, thin)

    def test_the_same_track_listed_twice_is_picked_once(self):
        # two library rows that differ only in case of the title are one track (same opaque id); the sampler must pick it once
        dup = self.rows + [dict(r, title=r["title"].swapcase()) for r in self.rows if "spoken" in r["tags"]]
        picked, counts = S.sample(dup, dict(S.DEFAULTS, **rules()))
        ids = [S.F.opaque(r["artist"], r["title"]) for _, r in picked]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(counts, {"s1": {"tracks": 9, "artists": 3}, "s2": {"tracks": 9, "artists": 3}})

    def test_sides_never_overlap_and_an_empty_side_is_refused(self):
        same = dict(S.DEFAULTS, **rules(sides={"s1": {"tags_all": ["spoken"]}, "s2": {"tags_all": ["spoken"]}}))
        with self.assertRaises(ValueError):   # the first side takes every match, so the second is empty
            S.sample(self.rows, same)


class EndToEndTests(unittest.TestCase):
    def test_sample_then_crate_then_checker(self):
        d = Path(tempfile.mkdtemp())
        sample = subprocess.run([sys.executable, "-I", str(HERE / "crate_maker" / "sample.py"), str(EX / "library.tsv"),
                                 str(EX / "rules.json"), "--out", str(d)], capture_output=True, text=True, cwd=HERE)
        self.assertEqual(sample.returncode, 0, sample.stdout + sample.stderr)
        self.assertNotIn("Artist", sample.stdout)                                   # counts only, no names
        build = subprocess.run([sys.executable, "-I", str(HERE / "crate_builder.py"), "build", str(EX / "features.json"),
                                "--assign", str(d / "assign.json"), "--purpose", "delivery-reference", "--kind", "contrast",
                                "--membership", "chosen", "--confidence", "low", "--out", str(d / "crates")],
                               capture_output=True, text=True, cwd=HERE)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        crate = next((d / "crates").glob("*.json"))
        exch = d / "exch"; (exch / "crates").mkdir(parents=True)
        (exch / "crates" / crate.name).write_text(crate.read_text())
        check = subprocess.run([sys.executable, "-I", str(HERE / "exchange.py"), "check", str(exch)],
                               capture_output=True, text=True, cwd=HERE)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertNotIn("Artist", crate.read_text())                              # the bundle holds no names


if __name__ == "__main__":
    unittest.main()


class AnyTagTests(unittest.TestCase):
    def test_tags_any_matches_one_of_the_list(self):
        row = {"tags": {"Relaxed"}}
        self.assertEqual(S.side_of(row, {"calm": {"tags_any": ["Laid-Back/Mellow", "Relaxed"]}}), "calm")
        self.assertIsNone(S.side_of({"tags": {"Dance"}}, {"calm": {"tags_any": ["Relaxed"]}}))
