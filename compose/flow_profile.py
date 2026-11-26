"""Measure delivery FLOW of a vocal stem, numbers only: syllable rate and pitch motion over ALL voiced frames (singing_profile.py only sees sustained notes).
  venv-speaker/bin/python reference-stats/flow_profile.py KEY [KEY...]      (KEY = folder name under work-audio/sep/htdemucs, e.g. Example_Artist_Example_Track)
  venv-speaker/bin/python reference-stats/flow_profile.py --file ARTIST TITLE vocals.wav   (any vocal-only wav)
Appends to reference-stats/flow_profile.tsv.  f0 is cached next to the stem (f0.npy).
Measures:
  syl_per_voiced_s  syllable nuclei per second of voiced time (articulation rate)   syl_per_s  per second of whole track (density)
  phrase_gap_s      median silence between phrases (gaps >= 0.25 s)                 voiced_pct share of frames voiced
  pitch_sd_st       median over 2 s windows of the pitch standard deviation, semitones (how much the voice moves while talking/rapping)
  pitch_step_st     median absolute pitch change between neighbouring syllables, semitones
  pitch_span_st     5th-95th percentile of all voiced pitch in the track, semitones
  flat_pct          share of voiced frames within 1 semitone of their 2 s window median (monotone delivery)
Syllable nuclei: peaks of the 2-6 band-limited loudness (300-3000 Hz, 40 ms smoothing) that rise 2.5 dB above the surrounding trough, at least 80 ms apart, on voiced frames.

Validated measures (added 2026-11-13). The ones above are kept so older tables and voice cards stay comparable, but in a known-manipulation test on real vocal
stems (speed, pitch level, pitch movement and silences changed by known amounts; 20 tracks) three of them were weak: syl_per_voiced_s reports about three quarters
of a speed change, pitch_sd_st and pitch_span_st about half of a change in pitch movement, and phrase_gap_s moves the wrong way. Prefer these:
  heard_syl_per_active_s  syllables in the words the speech server hears (rhyme_profile.timed_words, cmudict counts), per ACTIVE second. Needs intelligible English;
                          left blank when the heard words cover under 30% of the active time (heard_cover_pct). The words stay in memory, only the count is kept.
  active_s                seconds where the speech-band level is within 35 dB of the stem's 95th percentile
  pause_share_pct         share of the stem inside pauses; pauses_per_min: their number. A pause is 0.25 s or longer more than 18 dB below the 95th percentile, not at the edges.
  npitch_median_st, npitch_sd_st, npitch_step_st, npitch_span_st   pitch level (MIDI semitones), spread, step and span as above, from a neural pitch tracker (RMVPE)
Not validated: the absolute syllable count (needs known lyrics). Pause TIME over-responds to speed, which is why only the share and the count are reported.
The neural tracker needs torch and the RMVPE module and weights already on disk (FLOW_RMVPE_DIR, default ../seed-vc-work/seed-vc); it runs on the GPU when torch
has one (FLOW_DEV overrides; the card is shared, check nvidia-smi first) and its pitch is cached next to the stem. Recommended launch, nothing to install:
  venv-roformer/bin/python reference-stats/flow_profile.py [--no-heard] [--no-neural] KEY...     (pyworld and cmudict are picked up from the sibling environments)
A measure whose tool is missing is left blank and said so on stderr, never guessed."""
import os, sys, json, glob, re
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt, find_peaks
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
for _env in ("venv-speaker", "venv-roformer", "venv-rhyme"):   # appended AFTER the running environment's own packages, so its torch and numpy always win
    sys.path += glob.glob(os.path.join(HERE, "..", _env, "lib", "python%d.%d" % sys.version_info[:2], "site-packages"))
import pyworld as pw
RMVPE_DIR = os.environ.get("FLOW_RMVPE_DIR", os.path.join(HERE, "..", "seed-vc-work", "seed-vc"))
WORK = os.path.join(HERE, "work-audio")
SR = 22050
FRAME = 0.01

def load_mono(p):
    tmp = p + ".mono.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p, "-ac", "1", "-ar", str(SR), "-acodec", "pcm_s16le", tmp], check=True)
    r, x = wavfile.read(tmp); os.remove(tmp)
    return x.astype(np.float64) / 32768.0

def env_db(b, hop, smooth):
    n = len(b) // hop; db = 20 * np.log10(np.sqrt((b[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12) + 1e-9)
    return np.convolve(db, np.ones(smooth) / smooth, mode="same")

def runs(mask):
    d = np.diff(np.r_[0, mask.astype(int), 0]); return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))

def activity(b):
    """Active seconds, pauses and syllable-nucleus frames (10 ms index) from the speech-band signal b."""
    e = env_db(b, 220, 5); ref = np.percentile(e, 95); fr = 220 / SR; out = dict(active_s=round(float((e > ref - 35).sum() * fr), 1))
    quiet = e <= ref - 18; gaps = [(a, c) for a, c in runs(quiet) if a > 0 and c < len(e) and (c - a) * fr >= 0.25]
    out.update(pause_share_pct=round(100 * sum(c - a for a, c in gaps) / max(len(e), 1), 1), pauses_per_min=round(60 * len(gaps) / max(len(e) * fr, 1e-9), 1))
    e5 = env_db(b, 110, 4); a5 = e5 > np.percentile(e5, 95) - 35; pk, _ = find_peaks(e5, distance=10, prominence=2.0)
    return out, [int(p * 110 / SR / FRAME) for p in pk if a5[p]]

_rmvpe = None
def neural_f0(vpath, cache):
    """RMVPE pitch, Hz per 10 ms frame, 0 = unvoiced. One minute at a time, so a long stem needs no more memory than a short one."""
    global _rmvpe
    if os.path.exists(cache): return np.load(cache)
    import importlib.util, torch
    if _rmvpe is None:
        spec = importlib.util.spec_from_file_location("rmvpe", os.path.join(RMVPE_DIR, "modules", "rmvpe.py")); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        w = glob.glob(os.path.join(RMVPE_DIR, "checkpoints", "models--lj1995--VoiceConversionWebUI", "snapshots", "*", "rmvpe.pt"))[0]
        _rmvpe = mod.RMVPE(w, is_half=False, device=os.environ.get("FLOW_DEV") or ("cuda" if torch.cuda.is_available() else "cpu"))
    x = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", vpath, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout, dtype=np.float32).copy()
    parts = []
    for s in range(0, len(x), 960000):
        c = x[s:s + 960000]
        if len(c) < 1600: break
        with torch.no_grad(): f = np.asarray(_rmvpe.infer_from_audio(c, thred=0.03), dtype=np.float32)
        k = len(c) // 160; parts.append(np.pad(f[:k], (0, max(0, k - len(f)))))
    f0 = np.concatenate(parts) if parts else np.zeros(0, np.float32); np.save(cache, f0); return f0

def neural_pitch(f0, nuc):
    v = f0 > 0
    if v.sum() < 100: return {}
    midi = np.where(v, 69 + 12 * np.log2(np.maximum(f0, 1) / 440.0), np.nan); a = midi[v]; sds = []
    for s in range(0, len(midi) - 200, 200):
        m = midi[s:s + 200]; m = m[~np.isnan(m)]
        if len(m) >= 80: sds.append(np.std(m))
    vals = []
    for p in nuc:
        seg = midi[max(0, p - 3):p + 4]; seg = seg[~np.isnan(seg)]
        if len(seg): vals.append(np.median(seg))
    return dict(npitch_median_st=round(float(np.median(a)), 2), npitch_sd_st=round(float(np.median(sds)), 2) if sds else None,
                npitch_step_st=round(float(np.median(np.abs(np.diff(vals)))), 2) if len(vals) > 2 else None,
                npitch_span_st=round(float(np.percentile(a, 95) - np.percentile(a, 5)), 1))

_pron = None
def heard(vpath, active_s):
    """Syllables in the heard words per active second. The words are counted and dropped; nothing but numbers leaves this function."""
    global _pron
    import rhyme_profile as rp
    if _pron is None: _pron = rp.cmu_pron()
    def nsyl(w):
        w = re.sub(r"[^a-z']", "", w.lower())
        if not w: return 0
        p = _pron(w)
        return sum(ph[-1].isdigit() for ph in p) if p else max(1, len(re.findall(r"[aeiouy]+", w)))
    ws = rp.timed_words(vpath); cover = sum(en - st for st, en, _ in ws) / max(active_s, 1e-9)
    return dict(heard_syl_per_active_s=round(sum(nsyl(w) for _, _, w in ws) / active_s, 2) if cover >= 0.30 and active_s > 0 else None, heard_cover_pct=round(100 * cover))

NEW = ("active_s", "heard_syl_per_active_s", "heard_cover_pct", "pause_share_pct", "pauses_per_min", "npitch_median_st", "npitch_sd_st", "npitch_step_st", "npitch_span_st")

def profile(artist, title, vpath, cache, want_heard=False, want_neural=False):
    """Library callers get the original measures plus the loudness-based ones; the heard rate and the neural pitch are opt-in (the command line turns both on)."""
    v = load_mono(vpath)
    if os.path.exists(cache): f0 = np.load(cache)
    else:
        f0, _ = pw.harvest(v, SR, f0_floor=70.0, f0_ceil=700.0, frame_period=FRAME * 1000); np.save(cache, f0)
    n = len(f0); voiced = f0 > 0; dur = n * FRAME
    midi = np.where(voiced, 69 + 12 * np.log2(np.maximum(f0, 1) / 440.0), np.nan)
    # loudness envelope in the speech band, one value per 10 ms frame
    sos = butter(4, [300, 3000], btype="band", fs=SR, output="sos")
    b = sosfiltfilt(sos, v)
    hop = int(FRAME * SR)
    rms = np.array([np.sqrt(np.mean(b[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(n)])
    db = 20 * np.log10(rms + 1e-9)
    k = np.ones(4) / 4; dbs = np.convolve(db, k, mode="same")
    peaks, props = find_peaks(dbs, distance=8, prominence=2.5)
    nuc = [p for p in peaks if voiced[min(n - 1, p)] and dbs[p] > dbs.max() - 40]
    vs = voiced.sum() * FRAME
    # phrase gaps: unvoiced runs >= 0.25 s lying between voiced stretches
    gaps = []; i = 0
    while i < n:
        if voiced[i]: i += 1; continue
        j = i
        while j < n and not voiced[j]: j += 1
        if i > 0 and j < n and (j - i) * FRAME >= 0.25: gaps.append((j - i) * FRAME)
        i = j
    # pitch motion
    w = int(2.0 / FRAME); sds = []; flat = 0; tot = 0
    for s in range(0, n - w, w):
        seg = midi[s:s + w]; m = seg[~np.isnan(seg)]
        if len(m) < 80: continue
        sds.append(np.std(m)); med = np.median(m); flat += (np.abs(m - med) <= 1).sum(); tot += len(m)
    steps = []
    last = None
    for p in nuc:
        a, c = max(0, p - 3), min(n, p + 4); seg = midi[a:c]; seg = seg[~np.isnan(seg)]
        if len(seg) == 0: continue
        m = np.median(seg)
        if last is not None: steps.append(abs(m - last))
        last = m
    allm = midi[~np.isnan(midi)]
    extra = dict.fromkeys(NEW); act, nuc5 = activity(b); extra.update(act)
    if want_neural:
        try: extra.update(neural_pitch(neural_f0(vpath, re.sub(r"\.npy$", "", cache) + ".rmvpe.npy"), nuc5))
        except Exception as e: print("neural pitch left blank:", type(e).__name__, file=sys.stderr)
    if want_heard:
        try: extra.update(heard(vpath, act["active_s"]))
        except Exception as e: print("heard syllable rate left blank:", type(e).__name__, file=sys.stderr)
    return dict(artist=artist, title=title, seconds=round(dur), voiced_pct=round(100 * vs / dur), syl_per_voiced_s=round(len(nuc) / max(vs, 1e-9), 2),
                syl_per_s=round(len(nuc) / dur, 2), phrase_gap_s=round(float(np.median(gaps)), 2) if gaps else 0,
                pitch_sd_st=round(float(np.median(sds)), 2) if sds else 0, pitch_step_st=round(float(np.median(steps)), 2) if steps else 0,
                pitch_span_st=round(float(np.percentile(allm, 95) - np.percentile(allm, 5)), 1) if len(allm) else 0,
                flat_pct=round(100 * flat / max(tot, 1)), **extra)

if __name__ == "__main__":
    out = os.path.join(HERE, "flow_profile.tsv"); rows = []
    want_heard = "--no-heard" not in sys.argv; want_neural = "--no-neural" not in sys.argv; sys.argv = [a for a in sys.argv if a not in ("--no-heard", "--no-neural")]
    if sys.argv[1] == "--file":
        jobs = [(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[4] + ".f0.npy")]
    else:
        jobs = []
        for key in sys.argv[1:]:
            d = os.path.join(WORK, "sep", "htdemucs", key)
            prefixes = [p for p in os.environ.get("MCSOC_ARTIST_PREFIXES", "").split(",") if p]   # multi-word artist folder prefixes, e.g. "Example_Artist"
            art = next((a for a in prefixes if key.startswith(a)), key.split("_")[0])
            ti = key[len(art) + 1:]
            jobs.append((art, ti, os.path.join(d, "vocals.wav"), os.path.join(d, "f0.npy")))
    for art, ti, vp, cache in jobs:
        try: r = profile(art, ti, vp, cache, want_heard, want_neural)
        except Exception as e: print("FAIL", art, ti, repr(e)); continue
        rows.append(r); print(json.dumps(r), flush=True)
    if rows:
        keys = list(rows[0].keys()); old = [l.rstrip("\n").split("\t") for l in open(out)] if os.path.exists(out) else []
        if old and old[0] != keys:   # the table predates some columns: keep its rows, leave the columns they lack blank
            if not set(old[0]) <= set(keys): sys.exit("flow_profile.tsv has columns this version does not write; rows printed above were not saved")
            body = [dict(zip(old[0], l)) for l in old[1:]]
            with open(out + ".tmp", "w") as fh:
                fh.write("\t".join(keys) + "\n")
                for d in body: fh.write("\t".join(d.get(k, "") for k in keys) + "\n")
            os.replace(out + ".tmp", out)
        with open(out, "a") as fh:
            if not old: fh.write("\t".join(keys) + "\n")
            for r in rows: fh.write("\t".join("" if r[k] is None else str(r[k]) for k in keys) + "\n")
