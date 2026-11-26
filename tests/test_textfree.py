import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import textfree
from textfree import TextFreeContract


def rhyme_numbers(audio, transcribe):
    """A toy analyzer: counts words and how many share the last letter. Reads the text, returns numbers."""
    words = transcribe(audio).split()
    ends = [w[-1] for w in words]
    return {"n_tokens": float(len(words)), "end_letter_share": max(ends.count(c) for c in set(ends)) / len(ends)}


class Good(TextFreeContract, unittest.TestCase):
    def analyze(self, transcribe): return rhyme_numbers("a.wav", transcribe)


def _leaky(kind):
    def f(transcribe):
        t = transcribe("a.wav")
        if kind == "file": open("debug.txt", "w").write(t)
        if kind == "tmp":
            import tempfile; open(tempfile.mktemp(), "w").write(t)
        if kind == "stdout": print(t)
        if kind == "stderr": print(t, file=sys.stderr)
        if kind == "result-key": return {t.split()[0]: 1.0}
        if kind == "result-str": return {"n_tokens": 1.0, "note": t}
        if kind == "exception": raise ValueError(f"bad line: {t}")
        if kind == "filename": open(t.split()[1] + ".json", "w").write("{}")
        return {"n_tokens": 1.0}
    return f


class HarnessCatchesLeaks(unittest.TestCase):
    def test_every_kind_of_leak_is_caught(self):
        for kind in ("file", "tmp", "stdout", "stderr", "result-key", "result-str", "exception", "filename"):
            with self.assertRaises(textfree.Leak, msg=kind):
                textfree.check(_leaky(kind))

    def test_clean_analyzer_passes_and_scratch_is_cleaned(self):
        self.assertEqual(textfree.check(_leaky("none")), {"n_tokens": 1.0})

if __name__ == "__main__":
    unittest.main()
