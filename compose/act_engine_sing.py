"""Engine adapter for the Act seam (mc-soc/act.py): renders one sheet with sing.py and measures the voice alone.

Given a lyric sheet the adapter runs sing.py with --stems, which writes the voice part before the mix (no separator needed),
then runs measure_voice_act.py under venv-speaker to get the card's measures. It returns exactly {values, seconds}; act.py
refuses anything else. Measures the measurer cannot give are left out, so act.py reports them as unscored, not as zero.

Rules this keeps:
  * the sheet must be a lyrics-*.txt file in this folder, so the render name (song-*.wav) is predictable and new;
  * it refuses to run if the output song-*.wav already exists (a render is never overwritten);
  * the stems are scratch audio: they are kept, not deleted, until the owner says testing is done.

The speech server is needed for sing.py and for the heard-words count; neither is started or checked here.
Tests use a fake runner (test_act_engine_sing.py); no render has been made through this adapter yet.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # the repo root holds act.py and personas_link.py
import act  # noqa: E402  (the engine base class and the contract live there)

MEASURER_PY = os.environ.get("MCSOC_MEASURER_PY", sys.executable)   # a Python that has the pitch tracker installed
MEASURER = os.path.join(HERE, "measure_voice_act.py")
LINTER = os.path.join(HERE, "lint_lyrics.py")


def long_lines(sheet):
    """Lines the lyric linter flags as LONG (more syllables than their slot can carry). Empty when the sheet is clean.
    A sheet that is not on disk yet is not linted here; sing.py fails on it when it renders."""
    if not os.path.exists(sheet):
        return []
    out = subprocess.run([sys.executable, LINTER, sheet], capture_output=True, text=True, check=True).stdout
    return [l.strip() for l in out.splitlines() if l.lstrip().startswith("LONG")]


def persona_link(persona_id):
    """The persona link file for this id (checked by personas_link.py before use)."""
    import personas_link
    links, errors = personas_link.load_all()
    if persona_id not in links:
        raise ValueError(f"persona {persona_id!r} is not a valid link: {errors.get(persona_id + '.json', 'not found')}")
    return links[persona_id]


def make_persona_beat(style, bpm, runner=subprocess.run):
    """A beat for this style and tempo, made once and reused. Same bars and fills as the render recipe in the log."""
    out = os.path.join(HERE, f"beat-persona-{style}-{int(round(bpm))}.wav")
    if not os.path.exists(out):
        runner([sys.executable, "make_beat.py", "--style", style, "--bpm", str(int(round(bpm))), "--bars", "40",
                "--intro-bars", "4", "--fills", "--out", out], cwd=HERE, check=True, capture_output=True, text=True)
    return out


def render_paths(sheet):
    """The same names sing.py chooses: song-*.wav for the mix, song-*.voice.wav for the voice stem."""
    base = os.path.splitext(os.path.basename(sheet))[0].replace("lyrics", "song", 1)
    mix = os.path.join(HERE, base + ".wav")
    return mix, os.path.join(HERE, base + ".voice.wav")


class SingEngine(act.Engine):
    name = "sing-stems"

    def __init__(self, sheet, beat=None, bpm=None, voice=None, extra_args=(), runner=subprocess.run,
                 allow_long_reason=None, persona=None):
        if os.path.dirname(os.path.abspath(sheet)) != HERE or not os.path.basename(sheet).startswith("lyrics"):
            raise ValueError("sheet must be a lyrics-*.txt file in this folder")
        self.sheet = os.path.basename(sheet)
        self.runner = runner
        self.persona = persona
        extra = list(extra_args)
        if persona:
            # the persona link (mc-soc/personas/links) supplies the voice and the production values its card calls for
            link = persona_link(persona)
            s = link.get("settings") or {}
            voice = link["voice"]
            bpm = s.get("bpm", bpm)
            extra = list(s.get("sing", [])) + extra
            if s.get("beat_style"):
                if bpm is None:
                    raise ValueError("a persona with a beat style needs a bpm")
                beat = make_persona_beat(s["beat_style"], float(bpm), runner)
        if bpm is None:
            raise ValueError("bpm is required (or a persona that sets it)")
        self.beat = beat
        self.bpm = float(bpm)
        self.voice = voice
        self.extra_args = extra
        self.mix, self.stem = render_paths(self.sheet)
        if os.path.exists(self.mix):
            raise ValueError(f"{os.path.basename(self.mix)} already exists; choose a new sheet name")
        # Writing-stage rule: a sheet with LONG lines is not rendered. The only way past is a logged reason.
        flags = long_lines(os.path.join(HERE, self.sheet))
        if flags and not (allow_long_reason or "").strip():
            raise ValueError(f"{self.sheet} has {len(flags)} LONG line(s); fix them, or pass allow_long_reason with the style reason")
        self.allow_long_reason = (allow_long_reason or "").strip() or None
        self.long_flags = flags

    def render(self, tgt):
        cmd = [sys.executable, "sing.py", "--lyrics", self.sheet, "--beat", self.beat, "--bpm", str(self.bpm),
               "--stems", "--no-play"] + (["--voice", self.voice] if self.voice else []) + self.extra_args
        self.runner(cmd, cwd=HERE, check=True, capture_output=True, text=True)
        if not os.path.exists(self.stem):
            raise RuntimeError("sing.py did not write the voice stem")
        measures = sorted(tgt["bands"])
        out = self.runner([MEASURER_PY, MEASURER, self.stem] + measures, capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        values = {k: data["values"][k] for k in measures if k in data.get("values", {})}
        return {"values": values, "seconds": data["seconds"]}
