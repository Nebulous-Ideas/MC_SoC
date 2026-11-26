"""Lint a lyrics file against the template rules (2026-11-13, set from the real-reference gap report): syllables per line for its slot,
repetition, block length, the time the song will take, and (when reference-stats/rhyme_profile.py and cmudict load) the rhyme numbers.
python3 lint_lyrics.py lyrics.txt [bpm=100] [slot_beats=4]
Targets are read from reference-targets.json (real 5th-95th percentile ranges; numbers only). A "(slot 2)" section runs about 5-7 syllables
per line. After rendering, check_track.py is the gate. These are ranges to sit inside, not a recipe."""
import collections, json, os, re, sys
import sing
from flow_align import syllables
f = sys.argv[1]; bpm = float(sys.argv[2]) if len(sys.argv) > 2 else 100; slot = int(sys.argv[3]) if len(sys.argv) > 3 else 4
rows, total_beats, blocks = [], 4, []
auto = False
for voices, items in sing.stanzas(__import__("heteronym_lint").inline_say(open(f).read())):
    n_block = 0
    for adlib, t in items:
        if adlib:
            m = re.match(r"break\s*(\d+)?", t.lower()); s = re.fullmatch(r"slot\s+(\d+|auto)", t.lower())
            if s: auto = s.group(1) == "auto"; slot = slot if auto else int(s.group(1))
            else: total_beats += 4 * int(m.group(1) or 1) if m else 2
            continue
        n = sum(syllables(w) for w in re.findall(r"[A-Za-z']+", t))
        sl = (2 if n <= 5 else 4 if n <= 12 else 6) if auto else slot
        rows.append((n, sl, t)); total_beats += sl; n_block += 1
    if n_block: blocks.append(n_block)
    total_beats += 2
sy4 = sorted(n for n, s, _ in rows if s == 4) or sorted(n for n, _, _ in rows)
cn = collections.Counter(re.sub(r"[^a-z' ]", "", t.lower()).strip() for _, _, t in rows)
rep = sum(c for c in cn.values() if c > 1) / len(rows)
mins = total_beats * 60 / bpm / 60
try:                                              # real ranges written by reference-stats/crate-drafts/text_targets.py; without the file, no targets are shown
    TG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference-targets.json")))["measures"]
except Exception:
    TG = {}
def tg(k):
    m = TG.get(k)
    return f" (real {m['p5']:.3g} to {m['p95']:.3g}, median {m['p50']:.3g})" if m else ""
print(f"{len(rows)} spoken lines{tg('lines')}, estimated length {mins:.1f} min at {bpm:g} BPM, {len(rows) / mins:.1f} lines per minute{tg('lines_per_min')}")
print(f"syllables per 4-beat line: median {sy4[len(sy4) // 2]}{tg('syl_line')}, range {sy4[0]}-{sy4[-1]}; repeated-line share {rep:.2f}{tg('rep_line')}; "
      f"lines per block: median {sorted(blocks)[len(blocks) // 2]}{tg('lines_block')}")
for n, s, t in rows:
    per = n / s                                   # syllables per beat: 2.25-2.75 is the target, under 1.5 or over 3.5 is flagged
    if per > 3.5 or per < 1.5:
        print(f"  {'LONG ' if per > 3.5 else 'short'} {n:2d} in {s} beats  {t[:80]}")
try:
    import glob
    here = os.path.dirname(os.path.abspath(__file__))     # cmudict lives in venv-rhyme; this file runs under the system python (sing needs numpy)
    sys.path[:0] = [os.environ.get("MCSOC_REFERENCE_DIR", os.path.join(here, "reference-stats"))]; sys.path += glob.glob(os.path.join(here, "venv-rhyme/lib/python*/site-packages"))
    import rhyme_profile as R
    m = R.measure([t for _, _, t in rows], R.cmu_pron())
    print(f"end rhyme share {m['end_rhyme_share']:.2f}{tg('end_rhyme_share')}, multi-syllable rhyme share {m['multi2_share']:.2f}{tg('multi2_share')}, "
          f"rhyme density {m['rhyme_density']:.2f}{tg('rhyme_density')}")
except Exception as e:
    print(f"rhyme numbers not available ({type(e).__name__})")
