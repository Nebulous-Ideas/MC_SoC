"""Sung speech from our own voices: speak a line with the TTS voice, cut it into syllables, then move each syllable to a note (pitch) and a
length (time), and lay the notes on a beat grid. Talk-singing, not a singing model: it suits the robots and jingles.
Two methods: `world` (default; WORLD vocoder via pyworld, installed in venv-speaker: run with venv-speaker/bin/python; consonants stay at natural speed,
only the vowel is stretched, glides between notes, vibrato on long notes) and `rubber` (ffmpeg rubberband; warbly, kept for comparison).

  python3 melody.py --text "Run anything you like, except the one that bothers me" --voice am_michael \\
      --melody major --bpm 84 --beat beat-run-anything-except.wav --out sung-run-major

Melodies are MIDI notes, one per syllable, with a length in beats (see MELODIES). The syllable count of the text must match."""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

import sing
import words as W

SR = sing.SR if hasattr(sing, "SR") else 24000
PRON = json.load(open(os.path.join(sing.HERE, "pron.json"))) if os.path.exists(os.path.join(sing.HERE, "pron.json")) else {}


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def syllables(word):
    w = re.sub(r"[^a-z']", "", word.lower()).strip("'")
    if w in PRON:
        return max(1, len(PRON[w]))
    core = re.sub(r"ed$", "", w) if len(w) > 3 and w.endswith("ed") and w[-3] not in "td" else w     # approved, bothered: the -ed is silent
    groups = re.findall(r"[aeiouy]+", re.sub(r"e$", "", core) if len(core) > 2 and core.endswith("e") and core[-2] not in "aeiouy" else core)
    return max(1, len(groups))


def f0(x, sr, lo=70.0, hi=400.0):
    """Median fundamental frequency of a clip by autocorrelation over 40 ms frames; None if nothing is voiced."""
    n = int(sr * 0.04)
    out = []
    for s in range(0, max(1, len(x) - n), n // 2):
        fr = x[s:s + n]
        if len(fr) < n or np.abs(fr).max() < 0.02:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, "full")[n - 1:]
        lag_lo, lag_hi = int(sr / hi), int(sr / lo)
        if lag_hi >= len(ac) or ac[0] <= 0:
            continue
        seg = ac[lag_lo:lag_hi]
        k = int(seg.argmax())
        if seg[k] / ac[0] > 0.35:
            out.append(sr / (lag_lo + k))
    return float(np.median(out)) if out else None


def write(path, x, sr=SR):
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def stretch_shift(src, dst, tempo, pitch):
    """One syllable through rubberband: tempo > 1 shortens, pitch is a frequency ratio; formants kept so it stays the same voice."""
    sing.ffmpeg("-i", src, "-af", f"rubberband=tempo={tempo:.4f}:pitch={pitch:.4f}:formant=preserved:transients=smooth:pitchq=quality", "-ar", str(SR), "-ac", "1", dst)


AP_SCALE = float(os.environ.get("MELODY_AP", "1.0"))        # <1 makes the voiced part cleaner (less breath noise = less flutter)
VIBRATO = float(os.environ.get("MELODY_VIB", "0.14"))     # semitones of vibrato on long notes

MELODIES = {   # (MIDI notes, beats) for "Run anything you like, except the one that bothers me": 14 syllables, ~9.5 beats; a male voice sits near C3
    "major": ([52, 55, 57, 55, 52, 55, 57, 57, 55, 52, 55, 52, 50, 48], [0.5, 0.5, 0.5, 1, 0.5, 1, 0.5, 0.5, 0.5, 1, 0.5, 0.5, 0.5, 1.5]),
    "minor": ([45, 48, 50, 48, 45, 50, 52, 50, 48, 50, 48, 45, 43, 45], [0.5, 0.5, 0.5, 1, 0.5, 1, 0.5, 0.5, 0.5, 1, 0.5, 0.5, 0.5, 1.5]),
    "hook2": ([48, 50, 52, 50, 48, 50, 52, 53, 52, 50, 48, 50, 48, 45], [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.5]),   # "I can't tell which one that is, so it's yes to all of these"
    "hook3": ([50, 52, 50, 53, 52, 55, 53, 52, 50, 52, 50, 48, 45], [0.5, 1, 0.5, 1, 0.5, 1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.5]),             # "Approved, approved, approved, I'm approving anything"
    "hook4": ([48, 50, 52, 50, 48, 50, 53, 52, 50, 48, 50, 48, 45], [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1, 0.5, 0.5, 0.5, 0.5, 0.5, 1.5]),         # "Ask me for the thing you want, I'm up for everything"
    # "Becoming the keeper" hooks (A minor, male voice near A2): four lines of exactly four beats each
    "count8": ([45, 47, 48, 50, 52, 53, 55, 55, 57], [0.5] * 6 + [0.25, 0.25, 0.5]),                                          # "One, two, three, four, five, six, seven, eight" (the scale climbs as it counts)
    "nine10": ([57, 55, 53, 55, 57, 55, 53, 52, 50, 52], [0.75, 0.25, 0.25, 0.5, 0.5, 0.25, 0.25, 0.25, 0.25, 0.75]),   # "Nine is the number, and nine is the weight"
    "lock7": ([52, 50, 52, 50, 48, 50, 47], [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0]),                     # "Count it, log it, hold the lock"
    "keeper9": ([48, 50, 52, 50, 52, 50, 48, 47, 45], [0.5, 0.5, 0.5, 0.25, 0.5, 0.5, 0.25, 0.25, 0.75]),   # "Becoming the keeper of the clock"
    "chant": ([52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 50, 48], [0.5, 0.5, 0.5, 1, 0.5, 1, 0.5, 0.5, 0.5, 1, 0.5, 0.5, 0.5, 1.5]),
}


for _k in ('count8', 'nine10', 'lock7', 'keeper9'):   # chest-voice versions, 5 semitones lower
    MELODIES[_k + 'lo'] = ([n - 5 for n in MELODIES[_k][0]], MELODIES[_k][1])


def _clean_mask(v):
    """Voicing flickers on and off in the analysis: close gaps of up to 3 frames and drop blips of up to 2, so a vowel is one block."""
    v = v.copy()
    n = len(v)
    k = 0
    while k < n:
        if not v[k]:
            e = k
            while e < n and not v[e]:
                e += 1
            if 0 < k and e < n and e - k <= 3:
                v[k:e] = True
            k = e
        else:
            k += 1
    k = 0
    while k < n:
        if v[k]:
            e = k
            while e < n and v[e]:
                e += 1
            if e - k <= 2:
                v[k:e] = False
            k = e
        else:
            k += 1
    return v


def _smooth(sp, ap, width=5):
    """Average the spectral envelope (in the log domain) and the aperiodicity over a few frames so the joins and the analysis jitter do not flutter."""
    if len(sp) < width:
        return sp, ap
    ker = np.ones(width) / width
    lsp = np.log(np.maximum(sp, 1e-14))
    pad = width // 2
    lsp = np.vstack([np.convolve(np.pad(lsp[:, c], pad, mode="edge"), ker, mode="valid") for c in range(lsp.shape[1])]).T
    ap2 = np.vstack([np.convolve(np.pad(ap[:, c], pad, mode="edge"), ker, mode="valid") for c in range(ap.shape[1])]).T
    return np.exp(lsp), ap2


def world_render(x, sr, syl_spans, notes, beats, bpm):
    """Speech to singing with the WORLD vocoder: keep each syllable's spectral envelope (so it stays the same voice and the same word), keep
    consonants at natural speed, stretch only the voiced part (the vowel) to fill the note, and replace the pitch with the note, glided between
    notes, with a little vibrato on long ones."""
    import pyworld as pw
    x = x.astype(np.float64)
    fp = 5.0
    fr = fp / 1000.0
    f0_src, t = pw.harvest(x, sr, f0_floor=70.0, f0_ceil=400.0, frame_period=fp)
    f0_src = pw.stonemask(x, f0_src, t, sr)
    sp_src = pw.cheaptrick(x, f0_src, t, sr)
    ap_src = pw.d4c(x, f0_src, t, sr)
    step = 60.0 / bpm
    sps, aps, voiced_out, semis = [], [], [], []
    for (a, b), m, nb in zip(syl_spans, notes, beats):
        i0, i1 = int(a / fr), min(len(f0_src), max(int(a / fr) + 3, int(b / fr)))
        sp_s, ap_s, v = sp_src[i0:i1], ap_src[i0:i1], f0_src[i0:i1] > 0
        v = _clean_mask(v)
        total = max(int(nb * step / fr), 8)                      # frames this note owns, rest included
        sound = int(total * 0.94)                                # the last 6% is a breath
        vi = np.where(v)[0]
        seq_sp, seq_ap, seq_v = [], [], []
        if len(vi) < 6:                                          # no real vowel: natural speed
            seq_sp, seq_ap, seq_v = list(sp_s), list(ap_s), list(v)
        else:
            h, tl = max(2, int(len(vi) * 0.38)), max(2, int(len(vi) * 0.30))
            head_end, tail_start = vi[h - 1], vi[len(vi) - tl]
            mid = [j for j in range(head_end + 1, tail_start) if v[j]]
            natural = (i1 - i0) - len(mid)
            hold_n = max(len(mid), sound - natural)
            # the held part of the vowel: the middle frames, resampled to the note's length and smoothed hard (stretching raw frames makes the voice
            # flutter); the start and end of the syllable stay as spoken, so the word keeps its shape
            if len(mid) >= 2:
                src_t = np.linspace(0, 1, len(mid))
                dst_t = np.linspace(0, 1, hold_n)
                lsp = np.log(np.maximum(sp_s[mid], 1e-14))
                mid_sp = np.exp(np.vstack([np.interp(dst_t, src_t, lsp[:, c]) for c in range(lsp.shape[1])]).T)
                mid_ap = np.vstack([np.interp(dst_t, src_t, ap_s[mid][:, c]) for c in range(ap_s.shape[1])]).T
                mid_sp, mid_ap = _smooth(mid_sp, mid_ap, width=9)
                mid_ap = mid_ap * float(os.environ.get('MELODY_AP_SCALE', '1.0'))      # <1: less breath noise in held vowels (less falsetto-like)
            else:
                mid_sp = np.repeat(sp_s[head_end][None, :], hold_n, axis=0)
                mid_ap = np.repeat(ap_s[head_end][None, :], hold_n, axis=0)
            for j in range(len(v)):
                if j <= head_end or j >= tail_start or not v[j]:
                    seq_sp.append(sp_s[j]); seq_ap.append(ap_s[j]); seq_v.append(bool(v[j]))
                elif mid and j == mid[0]:
                    seq_sp.extend(list(mid_sp)); seq_ap.extend(list(mid_ap)); seq_v.extend([True] * hold_n)
        blk_sp, blk_ap, blk_v = np.array(seq_sp), np.array(seq_ap), np.array(seq_v, dtype=bool)
        if len(blk_sp) > sound and sound >= 8:                   # a syllable that is longer spoken than its note (fast notes): speak it faster, up to 2x, so later notes are not pushed late
            keep_n = max(sound, int(np.ceil(len(blk_sp) / 2.0)))
            idx = np.linspace(0, len(blk_sp) - 1, keep_n).round().astype(int)
            blk_sp, blk_ap, blk_v = blk_sp[idx], blk_ap[idx], blk_v[idx]
        blk_sp, blk_ap = _smooth(blk_sp, blk_ap)
        n_out = len(blk_sp)
        sps.append(blk_sp)
        aps.append(blk_ap)
        voiced_out.append(blk_v)
        semis.append(np.full(n_out, float(m)))
        pad = max(0, total - n_out)
        if pad:                                                  # the rest of the note: silence
            sps.append(np.full((pad, sp_src.shape[1]), 1e-14))
            aps.append(np.ones((pad, ap_src.shape[1])))
            voiced_out.append(np.zeros(pad, dtype=bool))
            semis.append(np.full(pad, float(m)))
    sp = np.ascontiguousarray(np.vstack(sps))
    ap = np.ascontiguousarray(np.vstack(aps))
    voiced = np.concatenate(voiced_out)
    semi = np.concatenate(semis)
    k = int(0.025 / fr)                                          # glide between notes: smooth the note curve (~25 ms each side)
    if k > 1:
        ker = np.hanning(2 * k + 1)
        ker /= ker.sum()
        semi = np.convolve(np.pad(semi, k, mode="edge"), ker, mode="valid")
    tt = np.arange(len(semi)) * fr                               # vibrato on sustained notes, fading in
    run = np.zeros(len(semi))
    c = 0
    for i in range(len(semi)):
        c = c + 1 if voiced[i] else 0
        run[i] = c * fr
    depth = np.clip((run - 0.30) / 0.30, 0, 1) * VIBRATO
    semi = semi + depth * np.sin(2 * np.pi * 5.5 * tt)
    f0 = np.where(voiced, 440.0 * 2 ** ((semi - 69) / 12.0), 0.0)
    ap = np.where(voiced[:, None], ap * AP_SCALE, ap)
    y = pw.synthesize(np.ascontiguousarray(f0), sp, ap, sr, fp)
    return y


def split_word(x, sr, s, e, n):
    """Syllable boundaries inside a word: the n-1 deepest energy valleys (at least 60 ms apart and clear of the word's edges); equal parts if the word has none."""
    if n == 1:
        return [s, e]
    a, b = int(s * sr), int(e * sr)
    seg = np.abs(x[a:b]) if b > a else np.zeros(1)
    hop = int(0.01 * sr)
    env = np.array([seg[i:i + hop * 2].mean() for i in range(0, max(1, len(seg) - hop * 2), hop)]) if len(seg) > hop * 3 else np.zeros(1)
    if len(env) < 6:
        return list(np.linspace(s, e, n + 1))
    env = np.convolve(env, np.ones(3) / 3, mode="same")
    lo, hi = max(1, int(len(env) * 0.15)), min(len(env) - 1, int(len(env) * 0.85))
    cands = sorted(range(lo, hi), key=lambda i: env[i])
    picked = []
    for i in cands:
        if all(abs(i - j) * 0.01 >= 0.06 for j in picked):
            picked.append(i)
        if len(picked) == n - 1:
            break
    if len(picked) < n - 1:
        return list(np.linspace(s, e, n + 1))
    cuts = sorted(s + i * 0.01 + 0.01 for i in picked)
    return [s] + cuts + [e]


def sing_line(text, voice, notes, beats, bpm, work, method="world"):
    wav_raw, wav = os.path.join(work, "raw.wav"), os.path.join(work, "line.wav")
    sing.speak(None, None, voice, "af_heart", text, wav_raw)
    sing.clean_clip(wav_raw, wav)
    x = sing.read_wav(wav)
    sr = SR
    ws = [w for w in re.findall(r"[A-Za-z']+", text)]
    nsyl = [syllables(w) for w in ws]
    if sum(nsyl) != len(notes):
        sys.exit(f"the text has {sum(nsyl)} syllables ({dict(zip(ws, nsyl))}) but the melody has {len(notes)} notes")
    spans = W.word_spans(wav)
    if len(spans) != len(ws):                       # the transcript disagreed with the text: spread the syllables over the whole clip
        total = sum(nsyl)
        edges = np.linspace(0, len(x) / sr, total + 1)
        syl_spans = [(edges[i], edges[i + 1]) for i in range(total)]
    else:
        syl_spans = []
        ends = [sp[2] for sp in spans]
        for k in range(len(spans)):          # the word timestamps end early: a word runs on to the next word's start, the last to the end of the clip
            ends[k] = len(x) / sr if k + 1 == len(spans) else max(ends[k] + 0.04, min(spans[k + 1][1], ends[k] + 0.25))
        for ((_, s, _e), n), e in zip(zip(spans, nsyl), ends):
            es = split_word(x, sr, max(0.0, s - 0.02), e, n)
            syl_spans += [(es[i], es[i + 1]) for i in range(n)]
    if method == "world":
        w24 = os.path.join(work, "line24.wav")
        sing.ffmpeg("-i", wav, "-ar", "24000", "-ac", "1", w24)
        import wave as _w
        with _w.open(w24) as w:
            x24 = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
        y = world_render(x24, 24000, syl_spans, notes, beats, bpm)
        y = np.interp(np.linspace(0, len(y) - 1, int(len(y) * sr / 24000)), np.arange(len(y)), y)
        return y / (np.abs(y).max() or 1.0) * 0.8
    base = f0(x, sr) or 120.0
    step = 60.0 / bpm
    total_s = sum(beats) * step + 0.5
    out = np.zeros(int(total_s * sr))
    t = 0.0
    for i, ((a, b), m, nb) in enumerate(zip(syl_spans, notes, beats)):
        seg = x[int(a * sr):int(b * sr)]
        if len(seg) < int(0.03 * sr):
            t += nb * step
            continue
        src, dst = os.path.join(work, f"s{i}.wav"), os.path.join(work, f"s{i}o.wav")
        fz = f0(seg, sr) or base
        ratio = min(max(midi_hz(m) / fz, 0.5), 2.0)
        want = nb * step * 0.92                      # leave a breath between notes
        # consonants stay at natural speed (stretching them smears the words): only the middle of the syllable, the vowel, is lengthened
        h, tl = int(len(seg) * 0.22), int(len(seg) * 0.18)
        head, body, tail = seg[:h], seg[h:len(seg) - tl], seg[len(seg) - tl:]
        keep = (len(head) + len(tail)) / sr
        body_want = max(0.08, want - keep)
        parts = []
        for j, (piece, w_len) in enumerate(((head, len(head) / sr), (body, body_want), (tail, len(tail) / sr))):
            if len(piece) < int(0.012 * sr):
                continue
            ps, pd = os.path.join(work, f"s{i}_{j}.wav"), os.path.join(work, f"s{i}_{j}o.wav")
            write(ps, piece)
            stretch_shift(ps, pd, tempo=max(0.25, min(8.0, (len(piece) / sr) / w_len)), pitch=ratio)
            parts.append(sing.read_wav(pd))
        if not parts:
            t += nb * step
            continue
        y = np.concatenate(parts)
        y = y[:int(want * sr)] if len(y) > int(want * sr) else y
        fade = min(len(y) // 4, int(0.02 * sr))
        if fade:
            y[:fade] *= np.linspace(0, 1, fade)
            y[-fade:] *= np.linspace(1, 0, fade)
        s0 = int(t * sr)
        out[s0:s0 + len(y)] += y[:max(0, len(out) - s0)]
        t += nb * step
    peak = np.abs(out).max() or 1.0
    return out / peak * 0.8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--melody", default="major")
    ap.add_argument("--bpm", type=float, default=84)
    ap.add_argument("--beat", help="a beat wav to sing over; the vocal enters after --skip-bars bars")
    ap.add_argument("--skip-bars", type=int, default=2)
    ap.add_argument("--notes", help="custom MIDI notes, comma separated (one per syllable), instead of --melody")
    ap.add_argument("--beats", help="custom note lengths in beats, comma separated")
    ap.add_argument("--transpose", type=float, default=0, help="semitones to move the melody (a higher character voice)")
    ap.add_argument("--fx", help="an ffmpeg audio filter applied to the vocal after singing (a character's filter)")
    ap.add_argument("--method", default="world", choices=["world", "rubber"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    notes, beats = MELODIES[a.melody]
    if a.notes:
        notes = [float(v) for v in a.notes.split(",")]
        beats = [float(v) for v in a.beats.split(",")]
    notes = [n + a.transpose for n in notes]
    with tempfile.TemporaryDirectory() as work:
        voc = sing_line(a.text, a.voice, notes, beats, a.bpm, work, a.method)
        vpath = a.out + "-vocal.wav"
        write(vpath, voc)
        if a.fx:
            fxp = os.path.join(work, 'fx.wav')
            sing.ffmpeg('-i', vpath, '-af', a.fx, '-ar', str(SR), '-ac', '1', fxp)
            voc = sing.read_wav(fxp)
            voc = voc / (np.abs(voc).max() or 1.0) * 0.8
            write(vpath, voc)
        if a.beat:
            bpath = os.path.join(work, "beat.wav")
            start = a.skip_bars * 4 * 60.0 / a.bpm
            sing.ffmpeg("-ss", f"{start:.3f}", "-t", f"{len(voc) / SR + 0.5:.3f}", "-i", a.beat, "-ar", str(SR), "-ac", "1", bpath)
            sing.ffmpeg("-i", vpath, "-i", bpath, "-filter_complex", "[1:a]volume=0.55[b];[0:a]volume=1.0[v];[v][b]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.92",
                        "-codec:a", "libmp3lame", "-q:a", "2", a.out + ".mp3")
        else:
            sing.ffmpeg("-i", vpath, "-codec:a", "libmp3lame", "-q:a", "2", a.out + ".mp3")
        os.remove(vpath)
    print("wrote", a.out + ".mp3")


if __name__ == "__main__":
    main()
