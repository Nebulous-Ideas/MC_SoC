# LOCAL ONLY. Rhyme check for a lyric sheet, against the hip-hop text reference (2026-11-18).
# Uses the one measure that passed its check (rhyme_entropy.entropy_density: entropy-weighted over blocks of 8 lines) and reports where
# each section of the sheet sits in the hip-hop distribution from the matched library (text only, 598 tracks).
# Numbers and section names only: never prints a line, a word or a title.
#   venv-rhyme/bin/python rhyme_check.py lyrics-foo.txt
import re, statistics as st, sys
import os
REF_DIR = os.environ.get("MCSOC_REFERENCE_DIR", "reference-stats")   # your own reference tables; none ship with the repo
sys.path.insert(0, REF_DIR)
import rhyme_profile as rp
import rhyme_entropy as re_

REF_FILE = os.path.join(REF_DIR, "hiphop_text_hip-hop_family.tsv")
SKIP = re.compile(r"^\s*(@voice|\(slot|\(break|\(be still|\(you feel|\(retry)", re.I)
HEAD = re.compile(r"^\s*\[(.+)\]\s*$")


def reference():
    rows = [l.split("\t") for l in open(REF_FILE).read().splitlines()[1:]]
    weighted = sorted(float(r[1]) for r in rows)
    n = len(weighted)
    return weighted, weighted[n // 4], st.median(weighted), weighted[(3 * n) // 4]


def sections(text):
    out, name, cur = [], "(top)", []
    for raw in text.splitlines():
        h = HEAD.match(raw)
        if h:
            if cur: out.append((name, cur))
            name, cur = h.group(1).strip(), []
            continue
        if not raw.strip() or SKIP.match(raw):
            continue
        cur.append(raw.strip())
    if cur: out.append((name, cur))
    return out


def position(x, ref):
    """Share of the hip-hop reference below x (0 = lowest, 1 = highest)."""
    return sum(v < x for v in ref) / len(ref)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    pron = rp.cmu_pron()
    ref, q1, med, q3 = reference()
    text = open(sys.argv[1]).read()
    secs = sections(text)
    whole = [l for _, lines in secs for l in lines]
    w = re_.entropy_density(whole, pron)
    p = position(w, ref)
    tag = "below the middle half" if w < q1 else ("above the middle half" if w > q3 else "within the middle half")
    print("reference, hip-hop songs (weighted density): q1 %.3f median %.3f q3 %.3f" % (q1, med, q3))
    print("whole sheet: lines %d | weighted density %.3f | %d%% of reference below | %s" % (len(whole), w, round(100 * p), tag))
    print("per section (diagnostic only; the reference is whole songs, so short sections are not comparable):")
    for name, lines in secs:
        n = sum(1 for l in lines if rp._words(l))
        if n < 4:
            print("  %-26s lines %2d | too few to score" % (name, n)); continue
        sw = re_.entropy_density(lines, pron)
        note = "short: not comparable" if n < 30 else "comparable"
        print("  %-26s lines %2d | weighted density %.3f | %s" % (name, n, sw, note))
