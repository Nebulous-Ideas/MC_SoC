"""Put the stressed words of a spoken line on the beats (the basic move of rap flow: rhymed, stressed syllables on accented beats).
A line spoken at its natural pace is time-warped piece by piece so that: the first word starts on beat 1, a content word starts on each of
beats 2 and 3, and the last (rhyme) word starts on beat 4 and finishes inside the slot. Pieces are cut in the quiet just before a word and
stretched with ffmpeg atempo (pitch kept)."""
import os
import re

import numpy as np

import sing
import words

SR = sing.SR
STOP = set("a an the and or but if so to of in on at for with from by as is are was were be been am i you he she we they it its my your our me us "
           "this that these those do does did have has had not no there here what who how when where why than then just can will would could should "
           "into out up over".split())


def syllables(w):
    w = re.sub(r"[^a-z]", "", w.lower())
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(1, n)


def stress_score(w):
    lw = re.sub(r"[^a-z']", "", w.lower())
    if lw in STOP:
        return 0.0
    return 1.0 + 0.4 * syllables(lw) + (0.3 if len(lw) > 5 else 0.0)


def spans_for(src, text):
    """STT word times matched to the written words (same count -> trust; else estimate from character position)."""
    tw = re.findall(r"[A-Za-z0-9']+", text)
    x = sing.read_wav(src)
    dur = len(x) / SR
    sp = words.word_spans(src)
    if len(sp) == len(tw):
        return [(w, s, e) for w, (_, s, e) in zip(tw, sp)], dur, True
    total = sum(len(w) + 1 for w in tw)
    out, acc = [], 0
    for w in tw:
        s = dur * acc / total
        acc += len(w) + 1
        out.append((w, s, dur * acc / total))
    return out, dur, False


def choose_anchors(spans, dur, beat, slot_beats):
    """Return [(word_index, target_time_s)] with strictly increasing word indices."""
    L = slot_beats * beat * 0.95
    scale = L / dur
    n = len(spans)
    anchors = [(0, 0.0)]
    last = n - 1
    # beat targets 1 and 2 (the middle beats): best-scoring content word near the target time, in order
    mids = []
    prev = 0
    for j in range(1, slot_beats - 1):
        tau = j * beat
        best, best_cost = None, 1e9
        for i in range(prev + 1, last):
            sc = stress_score(spans[i][0])
            if sc <= 0:
                continue
            cost = abs(spans[i][1] * scale - tau) - 0.08 * sc
            if cost < best_cost and abs(spans[i][1] * scale - tau) <= 0.6 * beat:
                best, best_cost = i, cost
        if best is not None:
            mids.append((best, tau))
            prev = best
    anchors += mids
    if last > 0 and last > anchors[-1][0]:
        w_len = (spans[last][2] - spans[last][1]) * scale
        tau = min((slot_beats - 1) * beat, L - w_len - 0.05)       # the rhyme word starts on the last beat, or earlier if it is long
        if tau > anchors[-1][1] + 0.15:
            anchors.append((last, tau))
    return anchors, L


def _write(path, arr):
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(arr, -1, 1) * 32767).astype("<i2").tobytes())


def _tempo(arr, f, tmp, tag):
    if abs(f - 1.0) < 0.005:
        return arr
    a, b = os.path.join(tmp, f"fa-{tag}-in.wav"), os.path.join(tmp, f"fa-{tag}-out.wav")
    _write(a, arr)
    sing.ffmpeg("-i", a, "-filter:a", f"atempo={f:.4f}", "-ar", str(SR), "-ac", "1", b)
    return sing.read_wav(b)


def align(src, text, beat, slot_beats, tmp, out, cache_key="a", gmin=0.92, gmax=1.2, fmin=0.93, fmax=1.12, pad_max=0.4):
    """Gentle version: one even tempo for the whole line (what the ear accepts), then put the stressed words on the beats by changing the GAPS
    between words, never by stretching words: each stretch of speech between two anchors is sped or slowed by at most about 10%; the rest of
    the timing difference becomes a slightly longer or shorter breath before the stressed word."""
    spans, dur, trusted = spans_for(src, text)
    x = sing.read_wav(src)
    L = slot_beats * beat * 0.95
    g = min(gmax, max(gmin, dur / L))                               # even whole-line tempo
    x = _tempo(x, g, tmp, f"{cache_key}g")
    spans = [(w, s / g, e / g) for w, s, e in spans]
    dur = len(x) / SR
    anchors, _ = choose_anchors(spans, dur, beat, slot_beats)
    e = np.convolve(x ** 2, np.ones(int(0.005 * SR)) / int(0.005 * SR), mode="same")
    cuts = []                                                       # (cut sample just before the anchor word, target time of the WORD start, offset word-start minus cut)
    for wi, tau in anchors:
        t = spans[wi][1]
        i0, i1 = int(max(0, t - 0.05) * SR), int(min(dur, t + 0.01) * SR)
        c = i0 + int(np.argmin(e[i0:i1])) if i1 > i0 else int(t * SR)
        cuts.append((c, tau, t - c / SR))
    cuts[0] = (0, 0.0, spans[0][1])                                 # the first word starts at the line start (leading silence already trimmed)
    bounds = [c for c, _, _ in cuts] + [len(x)]
    pieces, cur, factors, pads = [], 0.0, [], []
    for k in range(len(cuts)):
        c0, tau, off = cuts[k]
        word_start_out = cur + off                                  # where the anchor word would start if we change nothing
        pad = min(pad_max, max(0.0, tau - word_start_out))
        if pad > 0.01:
            pieces.append(np.random.default_rng(k).standard_normal(int(pad * SR)).astype(np.float32) * 1e-4)
            cur += pad
            pads.append(round(pad, 2))
        seg = x[bounds[k]:bounds[k + 1]]
        if len(seg) < int(0.03 * SR):
            continue
        D = len(seg) / SR
        if k + 1 < len(cuts):
            T = cuts[k + 1][1] - cuts[k + 1][2] - cur               # time available until the next anchor word's cut point
        else:
            T = L - cur
        f = min(fmax, max(fmin, D / max(0.05, T)))
        y = _tempo(seg, f, tmp, f"{cache_key}s")
        kf = min(len(y) // 2, int(0.006 * SR))
        if kf:
            y[:kf] *= np.linspace(0, 1, kf); y[-kf:] *= np.linspace(1, 0, kf)
        pieces.append(y)
        cur += len(y) / SR
        factors.append(round(f, 2))
    y = np.concatenate(pieces)
    _write(out, y)
    scale = 1.0
    before = [abs(spans[wi][1] * scale - tau) * 1000 for wi, tau in anchors]
    return dict(anchors=[(spans[wi][0], round(tau, 2)) for wi, tau in anchors], factors=factors, trusted=trusted, before_ms=before, pads=pads, global_tempo=round(g, 2))
