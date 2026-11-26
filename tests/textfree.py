"""Contract for text-free audio analyzers. Stdlib only.

An analyzer that must hear words (to measure rhyme, say) transcribes inside its own function and
returns numbers. The words must never leave it: not in the result, a file, stdout, stderr, a log,
an exception message or a leftover temp file. A new analyzer proves that by subclassing
TextFreeContract with a TestCase and supplying `analyze`:

    analyze(transcribe) -> dict      # call the analyzer under test; `transcribe(path)` is the injected
                                 # speech-to-text and returns the canary text below
The harness runs it in an empty working and temp directory and checks everything it could have left behind.
"""
import contextlib, io, os, sys, tempfile
CANARY = "zorblax quillfeather snarvet moondrizzle"   # words that occur nowhere else in the repo
CANARY_PARTS = CANARY.split()


class Leak(AssertionError):
    pass


def _scan_dir(root):
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            if any(w in fn.lower() for w in CANARY_PARTS):
                yield p, "file name"
            try:
                data = open(p, "rb").read().lower()
            except OSError:
                continue
            for w in CANARY_PARTS:
                if w.encode() in data:
                    yield p, f"contents ({w})"


def check(run):
    """Run `run(transcribe)` in a scratch directory; return its result or raise Leak."""
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as scratch:
        tmp = os.path.join(scratch, "tmp"); cwd = os.path.join(scratch, "cwd"); os.makedirs(tmp); os.makedirs(cwd)
        old = (os.getcwd(), tempfile.tempdir, os.environ.get("TMPDIR"))
        os.chdir(cwd); tempfile.tempdir = tmp; os.environ["TMPDIR"] = tmp
        result, exc = None, None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    result = run(lambda path: CANARY)
                except Exception as e:  # an exception message is also an output
                    exc = e
        finally:
            os.chdir(old[0]); tempfile.tempdir = old[1]
            if old[2] is None: os.environ.pop("TMPDIR", None)
            else: os.environ["TMPDIR"] = old[2]
        leaks = [f"{p[len(scratch):]}: {why}" for p, why in _scan_dir(scratch)]
        blob = (out.getvalue() + err.getvalue() + repr(result) + (str(exc) if exc else "") + repr(getattr(exc, "args", ""))).lower()
        leaks += [f"output text contains {w!r}" for w in CANARY_PARTS if w in blob]
    if leaks:
        raise Leak("; ".join(leaks))
    if exc is not None:
        raise exc
    return result


class TextFreeContract:
    def analyze(self, transcribe):  # pragma: no cover - supplied by the analyzer's test
        raise NotImplementedError

    def test_textfree_nothing_of_the_transcript_escapes(self):
        check(self.analyze)

    def test_textfree_result_is_only_finite_numbers(self):
        res = check(self.analyze)
        self.assertIsInstance(res, dict); self.assertTrue(res)
        for k, v in res.items():
            self.assertIsInstance(v, (int, float), k); self.assertNotIsInstance(v, bool, k)
            self.assertEqual(v, v, k); self.assertNotIn(abs(v), (float("inf"),), k)   # not NaN, not infinite
            self.assertFalse(any(w in k.lower() for w in ("text", "word", "line", "lyric", "transcript")), k)
