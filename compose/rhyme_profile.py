#!/usr/bin/env python3
"""Rhyme profile: how a track rhymes, as numbers only. Run with ../venv-rhyme/bin/python (needs cmudict).

The words are heard and counted INSIDE measure()/analyze() and nothing textual is returned or written: no
transcript, no word, no line, no rhyme key. The result is a dict of scalars that goes into a feature table
(../mc-soc/features.py: finite numbers, opaque ids, hashed artist group, local gitignored tables).
Enforced by test_rhyme_profile.py through the text-free contract (../mc-soc/tests/textfree.py).

  rhyme_profile.py analyze FILE [FILE ...] --artist NAME [--out ../mc-soc/tables/rhyme.json]
        transcribe each file in memory (speech server; audio piped from ffmpeg, never stored), add rows
  rhyme_profile.py calibrate FILE LYRICS
        OUR OWN tracks only: print the numbers from the transcript next to the numbers from the true lyrics

Measures (per track; omitted, never invented, when there are fewer than 4 usable lines):
  n_phrases, n_syllables       size
  oov_share                  words missing from the pronunciation dictionary
  end_rhyme_share            lines whose last word rhymes (last stressed vowel to the end) with one of the 3 lines either side
  multi_mean                 mean trailing-vowel match length against the best of the 3 lines either side (vowels only, consonants ignored)
  multi2_share, multi3_share lines whose best match is at least 2 / 3 vowels long
  internal_share             lines with two different words inside the line that rhyme
  density                    share of syllables inside a vowel pair that repeats within 4 lines (NOT the published rhyme density; kept for continuity)
  rhyme_density              rhymed syllables over all syllables, the published definition (Hirjee and Brown) with a simple matcher: a word
                             is rhymed when another, different word within 3 phrases either side (or in its own phrase) has the same sound from
                             its last STRESSED vowel to the end; it counts the syllables of that matching tail. Uncalibrated.
  vowel_chain2_density,      share of syllables inside a run of 2 (3) vowel sounds that repeats in another phrase within 3 phrases either side,
  vowel_chain3_density       consonants ignored: the engine's own multi-syllable rule (multi_rhyme.py). Reduced AH0 never anchors; same words do not
                             count. Uncalibrated.
  longest_chain_share        lines sharing the most common end-rhyme sound, over all lines

Measures that need no line ends (stream_*; given whenever there are 40 syllables, whatever the phrase count). Heard phrases are a poor stand-in
for written lines (about half the line ends are found), so these count on the word stream inside 24 syllables either side:
  stream_rhyme_density       rhymed syllables over all syllables, as rhyme_density, the window in syllables instead of phrases
  stream_multi2_share        stressed words whose ending matches another word's on at least 2 vowels counted back, consonants ignored
  stream_chain2_density      syllables inside a run of 2 vowel sounds that returns in other words; no reduced AH0
  stream_far_share           stressed words whose NEAREST same-vowel partner is 7 to 24 syllables away
  stream_near_share          stressed words whose NEAREST same-vowel partner is within 6 syllables (inside the line); added after the within-line plant
Checked against published text on real recordings (rank agreement 0.68 to 0.88 where most words are heard) and against planted change (direction
right about 8 times in 10, size about half). They are their own constructs, NOT the written end-rhyme or internal-rhyme share. RHYME-NOTES.md.

Gate (analyze only): heard_agreement is how far two hearings agree when the second shifts its 12 s windows by 6 s. Under 0.70 the track keeps
only its size measures and that number. It costs a second hearing and needs no lyrics.
"""
import re, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "mc-soc"))
# Calibration against the true lyrics of 7 of our own tracks (2026-11-12, see RHYME-NOTES.md): vocals separated, 12 s windows,
# 0.25 s pauses. Rank agreement is Spearman (n=7, weak evidence); bias is the direction of the level error.
CALIBRATION = {"status": "own-tracks", "n_tracks": 7,
               "rank_agreement": {"end_rhyme_share": 0.80, "multi_mean": 0.61, "internal_share": 0.43, "density": 0.56, "longest_chain_share": 0.45},
               "bias": {"end_rhyme_share": "low", "multi_mean": "low", "multi2_share": "low", "multi3_share": "low",
                        "internal_share": "none", "density": "none", "longest_chain_share": "none"}}
WINDOW = 3
MIN_LINES = 4


def _strip(p):
    return re.sub(r"\d", "", p)


def _is_vowel(p):
    return p[-1:].isdigit()


def _words(line):
    return re.findall(r"[a-z']+", line.lower())


def _key(phones):
    """Rhyme sound of one word: from its last stressed vowel (else last vowel) to the end, stress removed."""
    idx = [i for i, p in enumerate(phones) if _is_vowel(p)]
    if not idx:
        return None
    strong = [i for i in idx if phones[i][-1] in "12"]
    start = (strong or idx)[-1]
    return tuple(_strip(p) for p in phones[start:])


def _prep(lines, pron):
    """Per line: (vowel list, end key or None, [keys of non-final words]). Also counts words and OOV words."""
    out, n_words, n_oov = [], 0, 0
    for line in lines:
        ws = _words(line)
        phs = []
        for w in ws:
            n_words += 1
            ph = pron(w)
            if ph is None:
                n_oov += 1
            phs.append(ph)
        known = [ph for ph in phs if ph]
        vowels = [_strip(p) for ph in known for p in ph if _is_vowel(p)]
        end = _key(phs[-1]) if phs and phs[-1] else None
        inner = [(_key(ph), w) for ph, w in zip(phs[:-1], ws[:-1]) if ph]
        out.append((vowels, end, inner))
    return out, n_words, n_oov


def _trail(a, b, cap=4):
    n = 0
    while n < cap and n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _stressed_key(phones):
    """(rhyme sound, number of vowels in it) from the last stressed (1 or 2) vowel, or None when the word has no stressed vowel."""
    strong = [i for i, p in enumerate(phones) if _is_vowel(p) and p[-1] in "12"]
    if not strong:
        return None
    tail = phones[strong[-1]:]
    return tuple(_strip(p) for p in tail), sum(_is_vowel(p) for p in tail)


def _rhyme_density(lines, pron):
    """Rhymed syllables / all syllables over the phrases that have a known vowel. See the module docstring."""
    per = []
    for line in lines:
        ws = []
        for w in _words(line):
            ph = pron(w)
            if ph:
                ws.append((w, sum(_is_vowel(p) for p in ph), _stressed_key(ph)))
        if sum(nv for _, nv, _ in ws):
            per.append(ws)
    total = sum(nv for ws in per for _, nv, _ in ws)
    rhymed = 0
    for i, ws in enumerate(per):
        for x, (w, _, k) in enumerate(ws):
            if k is None:
                continue
            hit = any(k[0] == k2[0] and w != w2 for j in range(max(0, i - WINDOW), min(len(per), i + WINDOW + 1))
                      for y, (w2, _, k2) in enumerate(per[j]) if k2 is not None and (j, y) != (i, x))
            if hit:
                rhymed += k[1]
    return rhymed / total if total else 0.0


def _vowel_chain_density(lines, pron, n):
    """The engine's own rule (multi_rhyme.py, rhyme_find.py): n consecutive vowel sounds repeat in another phrase within WINDOW either side
    (or twice in one phrase without overlapping), consonants ignored. Share of syllables inside such a chain. A reduced AH0 never takes part
    and a chain made of the same words is not a chain (a looped hook adds nothing)."""
    per = []                                    # per phrase: [(vowel, word index in the phrase, word)]
    for line in lines:
        seq = []
        for x, w in enumerate(_words(line)):
            ph = pron(w)
            if ph:
                seq += [(p, x, w) for p in ph if _is_vowel(p)]
        if seq:
            per.append(seq)
    total = sum(len(v) for v in per)
    grams = []                                  # per phrase: {gram: [(start, words)]}; None-anchored grams (containing AH0) are skipped
    for seq in per:
        g = {}
        for a in range(len(seq) - n + 1):
            win = seq[a:a + n]
            if any(p == "AH0" for p, _, _ in win):
                continue
            g.setdefault(tuple(_strip(p) for p, _, _ in win), []).append((a, tuple(sorted({w for _, _, w in win}))))
        grams.append(g)
    covered = 0
    for i, g in enumerate(grams):
        mark = set()
        for gram, occ in g.items():
            for a, words in occ:
                hit = any(o_words != words for j in range(max(0, i - WINDOW), min(len(grams), i + WINDOW + 1)) if j != i
                          for _, o_words in grams[j].get(gram, ()))
                hit = hit or any(b != a and abs(b - a) >= n and b_words != words for b, b_words in occ)
                if hit:
                    mark.update(range(a, a + n))
        covered += len(mark)
    return covered / total if total else 0.0


STREAM_SYL = 24    # window either side, in syllables: about two published lines. Fixed before looking (2026-11-13); 12 and 36 give the same picture
STREAM_NEAR = 6    # a nearest partner within this many syllables is "inside the line"; 7..STREAM_SYL is line to line
STREAM_MIN = 40    # fewer syllables than this: no stream measures
STREAM = ["stream_rhyme_density", "stream_multi2_share", "stream_chain2_density", "stream_far_share", "stream_near_share"]


def _stream(words, pron):
    """words -> (syl, wd). syl: [(vowel, is reduced AH0, word index)]. wd: [(word, index of its last syllable, perfect key, vowel key)];
    both keys start at the last stressed vowel and are None for a word with no stressed vowel. Words missing from the dictionary are skipped."""
    syl, wd = [], []
    for w in words:
        ph = pron(w)
        if not ph:
            continue
        vi = [i for i, p in enumerate(ph) if _is_vowel(p)]
        if not vi:
            continue
        strong = [i for i in vi if ph[i][-1] in "12"]
        syl += [(_strip(ph[i]), ph[i] == "AH0", len(wd)) for i in vi]
        pk = tuple(_strip(p) for p in ph[strong[-1]:]) if strong else None
        ak = tuple(_strip(ph[i]) for i in vi if i >= strong[-1]) if strong else None
        wd.append((w, len(syl) - 1, pk, ak))
    return syl, wd


def stream_measure(words, pron, S=STREAM_SYL, min_syl=STREAM_MIN):
    """Rhyme measures that need no line ends (a heard track has none worth trusting). Everything is counted on the word stream, a partner being
    a DIFFERENT word whose last syllable lies within S syllables. Returns {} under min_syl syllables. See RHYME-NOTES.md for what was checked."""
    syl, wd = _stream(words, pron)
    n = len(syl)
    strong = [i for i, x in enumerate(wd) if x[2] is not None]
    if n < min_syl or not strong:
        return {}

    def near(i):
        e, j = wd[i][1], i - 1
        while j >= 0 and e - wd[j][1] <= S:
            yield j
            j -= 1
        j = i + 1
        while j < len(wd) and wd[j][1] - e <= S:
            yield j
            j += 1

    rhymed = far = close = multi2 = 0
    for i in strong:
        w, e, pk, ak = wd[i]
        if any(wd[j][2] == pk and wd[j][0] != w for j in near(i)):
            rhymed += len(ak)                                   # the syllables of the matching tail
        dist = [abs(wd[j][1] - e) for j in near(i) if wd[j][3] == ak and wd[j][0] != w]
        far += bool(dist) and min(dist) > STREAM_NEAR
        close += bool(dist) and min(dist) <= STREAM_NEAR
        best = 0                                                # equal vowels counted back from the two word ends; runs may not overlap
        for j in near(i):
            if wd[j][0] != w and not syl[e][1]:
                f, t = wd[j][1], 0
                while t < 4 and t < abs(f - e) and min(e, f) - t >= 0 and syl[e - t][0] == syl[f - t][0]:
                    t += 1
                best = max(best, t)
        multi2 += best >= 2
    pos = {}                                                    # 2 vowels in a row that come back within S syllables in other words
    for a in range(n - 1):
        win = syl[a:a + 2]
        if not any(r for _, r, _ in win):
            pos.setdefault(tuple(v for v, _, _ in win), []).append((a, tuple(sorted({wd[k][0] for _, _, k in win}))))
    mark = set()
    for occ in pos.values():
        for a, wa in occ:
            if any(2 <= abs(b - a) <= S and wb != wa for b, wb in occ):
                mark.update((a, a + 1))
    return {"stream_rhyme_density": rhymed / n, "stream_multi2_share": multi2 / len(strong),
            "stream_chain2_density": len(mark) / n, "stream_far_share": far / len(strong), "stream_near_share": close / len(strong)}


def measure(lines, pron):
    """lines: iterable of strings. pron: word -> list of ARPAbet phones or None. Returns a dict of floats."""
    lines = [l for l in lines if _words(l)]
    prepped, n_words, n_oov = _prep(lines, pron)
    usable = [p for p in prepped if p[0]]
    n = len(usable)
    out = {"n_phrases": float(n), "n_syllables": float(sum(len(p[0]) for p in usable)),
           "oov_share": (n_oov / n_words) if n_words else 0.0}
    out.update(stream_measure([w for l in lines for w in _words(l)], pron))
    if n < MIN_LINES:
        return out
    end_hit = best = 0
    bests = []
    for i, (v, k, _) in enumerate(usable):
        later = usable[max(0, i - WINDOW):i] + usable[i + 1:i + 1 + WINDOW]
        if k is not None and any(k == o[1] for o in later):
            end_hit += 1
        bests.append(max([_trail(v, o[0]) for o in later] or [0]))
    internal = 0
    for _, _, inner in usable:
        keys = [(k, w) for k, w in inner if k]
        if any(a[0] == b[0] and a[1] != b[1] for x, a in enumerate(keys) for b in keys[x + 1:]):
            internal += 1
    covered = total = 0
    grams = [Counter(zip(v, v[1:])) for v, _, _ in usable]
    for i, (v, _, _) in enumerate(usable):
        near = Counter()
        for j in range(max(0, i - 4), min(n, i + 5)):
            if j != i:
                near.update(grams[j])
        mark = [False] * len(v)
        for x in range(len(v) - 1):
            if near[(v[x], v[x + 1])]:
                mark[x] = mark[x + 1] = True
        covered += sum(mark); total += len(v)
    ends = Counter(p[1] for p in usable if p[1] is not None)
    out.update({"end_rhyme_share": end_hit / n, "multi_mean": sum(bests) / n,
                "multi2_share": sum(b >= 2 for b in bests) / n, "multi3_share": sum(b >= 3 for b in bests) / n,
                "internal_share": internal / n, "density": covered / total if total else 0.0,
                "rhyme_density": _rhyme_density(lines, pron),
                "vowel_chain2_density": _vowel_chain_density(lines, pron, 2), "vowel_chain3_density": _vowel_chain_density(lines, pron, 3), "longest_chain_share": (max(ends.values()) / n) if ends else 0.0})
    return out


def clean_lyrics(text):
    """Our own lyrics files -> plain spoken lines: drop section tags, @voice, ad-libs and clip/break directives."""
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l or l.startswith("@") or re.fullmatch(r"\[.*\]", l):
            continue
        m = re.fullmatch(r"\(sing [^:]*:\s*(.*)\)", l)
        if m:
            l = m.group(1)
        elif re.fullmatch(r"\(.*\)", l):
            continue
        out.append(l)
    return out


FEATURE_ROWS = [("n_phrases", "phrases", "usable phrases"), ("n_syllables", "syllables", "syllables in usable phrases"),
                ("oov_share", "share", "words missing from the pronunciation dictionary"),
                ("end_rhyme_share", "share", "phrases end-rhyming with one of the 3 either side"), ("multi_mean", "vowels", "mean trailing-vowel match length"),
                ("multi2_share", "share", "phrases whose best vowel match is at least 2"), ("multi3_share", "share", "phrases whose best vowel match is at least 3"),
                ("internal_share", "share", "phrases with an internal rhyme"), ("density", "share", "syllables inside a repeated vowel pair (not the published rhyme density)"),
                ("rhyme_density", "share", "rhymed syllables over all syllables (published definition, simple matcher, uncalibrated)"),
                ("vowel_chain2_density", "share", "syllables inside a repeated run of 2 vowel sounds, consonants ignored (the engine's rule; uncalibrated)"),
                ("vowel_chain3_density", "share", "syllables inside a repeated run of 3 vowel sounds, consonants ignored (the engine's rule; uncalibrated)"),
                ("longest_chain_share", "share", "phrases in the largest end-rhyme group")]
STREAM_ROWS = [("stream_rhyme_density", "share", "rhymed syllables over all syllables; partner within 24 syllables, no line ends used"),
               ("stream_multi2_share", "share", "stressed words whose ending matches another within 24 syllables on 2 or more vowels, consonants ignored"),
               ("stream_chain2_density", "share", "syllables inside a run of 2 vowel sounds that returns within 24 syllables in other words"),
               ("stream_far_share", "share", "stressed words whose nearest same-vowel partner is 7 to 24 syllables away (line to line, not inside the line)"),
               ("stream_near_share", "share", "stressed words whose nearest same-vowel partner is within 6 syllables (inside the line)")]
FEATURE_ROWS += STREAM_ROWS
GATE_ROW = ("heard_agreement", "share", "agreement of two hearings with shifted windows; under 0.70 the rhyme measures are withheld")


def table_from_lyrics(files, pron, owner="own"):
    """Feature table from lyrics files that are OUR OWN (known text, so no transcription error). Rows are opaque hashes of the file stem;
    the group is a hash of the primary @voice cast, the stand-in for an artist on single-author material. Files with identical
    cleaned text count once (re-renders of one song are not independent tracks). Needs ../mc-soc on the path (features)."""
    import features as F
    rows, seen = [], set()
    for f in sorted(files):
        text = Path(f).read_text()
        lines = clean_lyrics(text)
        key = hash("\n".join(lines))
        if key in seen:
            continue
        seen.add(key)
        m = measure(lines, pron)
        voices = Counter(re.findall(r"^@voice\s+(\S+)", text, re.M))
        cast = voices.most_common(1)[0][0] if voices else "unspecified"
        if len(m) > 3:      # fewer than 4 usable phrases gives only size measures: no rhyme to profile
            rows.append({"id": F.opaque(owner, Path(f).stem), "group": F.opaque(owner, cast, n=8), "values": m})
    names = {k for r in rows for k in r["values"]}
    feats = [{"name": n, "unit": u, "description": d} for n, u, d in FEATURE_ROWS if n in names]
    return F.make_table("rhyme-profile-lyrics", "1", feats, rows, F.provenance("rhyme-profile-lyrics", "own", len(rows)))


HEARD_SHIFT_S = 6       # the second hearing starts its 12 s windows this much later
HEARD_AGREE_MIN = 0.70  # below this the rhyme measures are withheld. Set on 34 reference tracks with published lyrics (2026-11-13, RHYME-NOTES.md)


def heard_agreement(first, second, shift=HEARD_SHIFT_S):
    """How far two hearings of one track agree, 0..1: words matched in order, twice over, by the words in both ([(start, end, word)] each; the
    first hearing counted from `shift` seconds on, where the second begins). Needs no lyrics. A number only: no word leaves."""
    import difflib
    a = [x for st, _, w in first if st >= shift for x in _words(w)]
    b = [x for _, _, w in second for x in _words(w)]
    if not a or not b:
        return 0.0
    return 2 * sum(m.size for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()) / (len(a) + len(b))


def analyze_gated(audio, hear, pron):
    """Hear one track twice and return numbers. hear(audio, offset) -> [(start, end, word)], kept in memory only. When the two hearings agree
    on less than HEARD_AGREE_MIN the recogniser was guessing: only the size measures and the agreement itself are returned, nothing is invented."""
    first = hear(audio, 0)
    agree = heard_agreement(first, hear(audio, HEARD_SHIFT_S))
    m = measure(lines_from_words(first), pron)
    if agree < HEARD_AGREE_MIN:
        m = {k: m[k] for k in ("n_phrases", "n_syllables", "oov_share")}
    m["heard_agreement"] = agree
    return m


def analyze(audio, transcribe, pron):
    """Hear one track and return numbers. transcribe(audio) -> newline-separated lines, kept in memory only."""
    return measure(transcribe(audio).splitlines(), pron)


# ---- real engines (not used by the tests) -------------------------------------------------------------
def cmu_pron():
    import cmudict
    d = cmudict.dict()
    return lambda w: (d.get(w) or d.get(w.strip("'")) or [None])[0]


CHUNK_S = 12   # whole tracks lose their second half in one request; 12 s windows recover the words (214 heard of 209 true, one test track)
GAP_S = 0.15   # a pause at least this long between words ends a phrase. 0.15 and 0.25 tied on own tracks (calibrate-many); against published line ends on 26 reference tracks 0.15 agreed slightly better (2026-11-13), and no pause or beat-grid rule did better than about half the line ends


def timed_words(audio, offset=0):
    """Hear audio in 12 s windows (the first starting at `offset` seconds) straight from ffmpeg's pipe. Returns [(start_s, end_s, word)] in memory only."""
    import json, os, subprocess, urllib.request, uuid
    host = os.environ.get("SPEECH_URL", "http://localhost:8000")
    key = os.environ.get("SPEECH_KEY", "").strip()   # set by the owner at launch; never printed
    if not key:
        raise SystemExit("set SPEECH_KEY (and SPEECH_URL) for the speech server; see compose/README.md")
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
                                 capture_output=True, text=True, check=True).stdout.strip())
    out = []
    for start in range(offset, int(total) + 1, CHUNK_S):
        wav = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(CHUNK_S), "-i", str(audio), "-ac", "1", "-ar", "16000", "-f", "wav", "-"],
                             capture_output=True, check=True).stdout
        if len(wav) < 16000:   # under half a second of audio
            continue
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in (("model", "Systran/faster-distil-whisper-small.en"), ("response_format", "verbose_json"), ("language", "en"),
                              ("timestamp_granularities[]", "word"))]
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + wav + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        req = urllib.request.Request(f"{host}/v1/audio/transcriptions", data=b"".join(parts),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
        words = data.get("words") or [w for sg in (data.get("segments") or []) for w in (sg.get("words") or [])]
        out += [(start + w["start"], start + w["end"], str(w.get("word", "")).strip()) for w in words if str(w.get("word", "")).strip()]
    return out


def lines_from_words(words, gap=GAP_S):
    """Cut a phrase wherever the pause between two words is at least `gap` seconds."""
    lines, cur, last_end = [], [], None
    for st, en, w in words:
        if cur and last_end is not None and st - last_end >= gap:
            lines.append(" ".join(cur)); cur = []
        cur.append(w); last_end = en
    if cur:
        lines.append(" ".join(cur))
    return lines


def speech_transcribe(audio):
    """Lines of what was heard, as one string; kept in memory only."""
    return "\n".join(lines_from_words(timed_words(audio)))


def main(argv):
    import argparse, json
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze"); a.add_argument("files", nargs="+"); a.add_argument("--artist", required=True)
    a.add_argument("--out", default=str(HERE.parent / "mc-soc" / "tables" / "rhyme.json"))
    a.add_argument("--measured-on", choices=list(F.MEASURED_ON) if False else ["own", "reference", "mixed", "unspecified"], default="unspecified")
    l = sub.add_parser("lyrics"); l.add_argument("files", nargs="+"); l.add_argument("--owner", default="own")
    l.add_argument("--out", default=str(HERE.parent / "mc-soc" / "tables" / "own-lyrics.json"))
    c = sub.add_parser("calibrate"); c.add_argument("audio"); c.add_argument("lyrics")
    args = ap.parse_args(argv)
    pron = cmu_pron()
    if args.cmd == "lyrics":
        import features as F
        t = table_from_lyrics(args.files, pron, args.owner)
        errs = F.validate(t)
        if errs:
            print("table invalid:", *errs, sep="\n  "); return 1
        Path(args.out).parent.mkdir(parents=True, exist_ok=True); Path(args.out).write_text(json.dumps(t, indent=1))
        print(f"{len(t['rows'])} distinct songs, {len({r['group'] for r in t['rows']})} cast groups -> {args.out}")
        return 0
    if args.cmd == "calibrate":
        truth = measure(clean_lyrics(Path(args.lyrics).read_text()), pron)
        heard = analyze(args.audio, speech_transcribe, pron)
        print(f"{'measure':22}{'from lyrics':>13}{'from audio':>13}")
        for k in truth:
            print(f"{k:22}{truth[k]:13.3f}{heard.get(k, float('nan')):13.3f}")
        return 0
    import features as F
    out = Path(args.out)
    feats = [("n_phrases", "lines", "usable lines heard"), ("n_syllables", "syllables", "syllables in usable lines"),
             ("oov_share", "share", "words missing from the pronunciation dictionary"),
             ("end_rhyme_share", "share", "lines end-rhyming with one of the 3 either side"), ("multi_mean", "vowels", "mean trailing-vowel match length"),
             ("multi2_share", "share", "lines whose best vowel match is at least 2"), ("multi3_share", "share", "lines whose best vowel match is at least 3"),
             ("internal_share", "share", "lines with an internal rhyme"), ("density", "share", "syllables inside a repeated vowel pair (not the published rhyme density)"),
                ("rhyme_density", "share", "rhymed syllables over all syllables (published definition, simple matcher, uncalibrated)"),
                ("vowel_chain2_density", "share", "syllables inside a repeated run of 2 vowel sounds, consonants ignored (the engine's rule; uncalibrated)"),
                ("vowel_chain3_density", "share", "syllables inside a repeated run of 3 vowel sounds, consonants ignored (the engine's rule; uncalibrated)"),
             ("longest_chain_share", "share", "lines in the largest end-rhyme group")] + STREAM_ROWS + [GATE_ROW]
    table = json.loads(out.read_text()) if out.exists() else F.make_table(
        "rhyme-profile", "1", [{"name": n, "unit": u, "description": d} for n, u, d in feats], [])
    table["provenance"] = F.provenance("rhyme-profile-cmudict", args.measured_on, 0, CALIBRATION)
    for f in args.files:
        rid = F.opaque(args.artist, Path(f).stem)
        vals = analyze_gated(f, timed_words, pron)
        table["rows"] = [r for r in table["rows"] if r["id"] != rid] + [{"id": rid, "group": F.opaque(args.artist, n=8), "values": vals}]
        print(f"{rid}: {len(vals)} measures" + ("" if vals["heard_agreement"] >= HEARD_AGREE_MIN else "  (two hearings disagree: rhyme measures withheld)"))
    table["provenance"]["n_tracks"] = len(table["rows"])
    errs = F.validate(table)
    if errs:
        print("table invalid:", *errs, sep="\n  "); return 1
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(table, indent=1)); print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
