# LOCAL ONLY. QA report for a rendered song: says which lines and sections to listen to before anything is shared.
# Checks (none of them decides that a song is good; a person listens to what is flagged):
#   words    the speech recognizer hears each line; words the sheet has that are not heard are flagged (catches 'lone' for 'loan').
#   tail     high-frequency energy at the end of a line against its body, judged only where the line end is loud enough
#            (catches the sibilant 'loans' tail; the 2026-11-18 Shoulders take).
#   balance  backing against voice per 10 s section, in dB (reference median about 3.7 dB above the voice).
#   clip     peaks at or over 0.99 in the voice or backing stem.
# usage: venv-speaker/bin/python qa_render.py SHEET.txt NAME [--out report.txt]
#   reads NAME.voice.wav, NAME.beat.wav, NAME.lines.json in this folder; NAME is the render name (song-...).
# The speech recognizer is the one rhyme_profile.timed_words uses (the speech server); numbers and flags only, no lyric text kept.
import json, os, re, sys, difflib
import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "reference-stats"))


def fmt_time(t):
    """Seconds below a minute as 45.3s; a minute or more as m:ss.s, to match the playback window."""
    if t < 60:
        return f"{t:6.2f}s"
    m = int(t // 60)
    return f"{m}:{t - 60 * m:04.1f}"


def norm_words(text):
    text = re.sub(r"\{[^}]*\}", "", text)          # respellings like read{red}: the spoken word is the base word
    return [w for w in re.findall(r"[a-z']+", text.lower()) if w]


def load(path):
    x, sr = sf.read(path)
    return (x.mean(axis=1) if x.ndim > 1 else x), sr


def hf_excess(seg, sr):
    s = seg * np.hanning(len(seg))
    S = np.abs(np.fft.rfft(s)) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / sr)
    hi = S[(f > 4000) & (f < 9000)].sum()
    lo = S[(f > 200) & (f < 2000)].sum() + 1e-12
    return 10 * np.log10(hi / lo + 1e-12)


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    sheet, name = argv[0], argv[1]
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else None
    voice, sr = load(os.path.join(HERE, f"{name}.voice.wav"))
    beat, _ = load(os.path.join(HERE, f"{name}.beat.wav"))
    lines = json.load(open(os.path.join(HERE, f"{name}.lines.json")))
    flags = []

    # --- words: what the recognizer hears in each line window against what the sheet says ---
    import rhyme_profile as rp
    heard = rp.timed_words(os.path.join(HERE, f"{name}.voice.wav"))
    for t, d, text in lines:
        want = norm_words(text)
        if not want:
            continue
        got = [w for s, e, w in heard if s >= t - 0.25 and e <= t + d + 0.25]
        got = norm_words(" ".join(got))
        sm = difflib.SequenceMatcher(a=want, b=got).ratio()
        if sm < 0.8:
            miss = [w for w in want if w not in got]
            flags.append(("words", t, f"heard {' '.join(got) or 'nothing'}; missing {', '.join(miss) or 'order only'}"))

    # --- tail: loud line ends with more hiss than their body ---
    for t, d, text in lines:
        if d < 0.8:
            continue
        a, b = int((t + 0.1) * sr), int((t + d - 0.35) * sr)
        c, e = int((t + d - 0.15) * sr), int((t + d) * sr)
        body, tail = voice[a:b], voice[c:e]
        if len(body) < 100 or len(tail) < 50:
            continue
        rb, rt = np.sqrt(np.mean(body ** 2)), np.sqrt(np.mean(tail ** 2))
        if rt < rb * 10 ** (-25 / 20) or rt < 10 ** (-45 / 20):   # judged only when the line end is audible (above -45 dBFS) and near the body's level
            continue
        ex = hf_excess(tail, sr) - hf_excess(body, sr)
        if ex > 5:
            flags.append(("tail", t, f"line end {ex:+.1f} dB more hiss than its body"))

    # --- balance: backing against voice per 10 s section ---
    n = min(len(voice), len(beat))
    w = int(10 * sr)
    for i in range(0, n - w, w):
        v, bb = voice[i:i + w], beat[i:i + w]
        act = []
        for j in range(0, len(v) - int(sr), int(sr)):
            rv = np.sqrt(np.mean(v[j:j + int(sr)] ** 2)); rb2 = np.sqrt(np.mean(bb[j:j + int(sr)] ** 2))
            if rv > 10 ** (-40 / 20) and rb2 > 0:
                act.append(20 * np.log10(rb2 / rv))
        if len(act) >= 3:
            med = float(np.median(act))
            if not (1.5 <= med <= 6.0):
                flags.append(("balance", i / sr, f"backing {med:+.1f} dB against the voice in this 10 s (reference about +3.7)"))

    # --- clip: peaks at full scale ---
    for label, stem in (("voice", voice), ("beat", beat)):
        k = int(np.sum(np.abs(stem) >= 0.99))
        if k:
            flags.append(("clip", 0.0, f"{label} stem has {k} samples at full scale"))

    flags.sort(key=lambda r: r[1])
    lines_out = [f"QA {name}: {len(flags)} flag(s)  (sheet {os.path.basename(sheet)})"]
    for kind, t, why in flags:
        lines_out.append(f"  {fmt_time(t):>9s}  {kind:8s} {why}")
    if not flags:
        lines_out.append("  nothing flagged by the checks; still listen to the whole song once")
    report = "\n".join(lines_out)
    print(report)
    if out_path:
        open(out_path, "w").write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
