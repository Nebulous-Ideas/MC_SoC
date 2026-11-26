# LOCAL ONLY. Step 3: entropy-weighted rhyme density, for repetitive hooks (2026-11-18). Numbers only; prints no lyric text.
# Why: the density in rhyme_profile.py counts a rhymed syllable whenever a partner word in the window differs. A hook that repeats
# its lines therefore inflates the share. Weighting each block of lines by how varied its words are should reduce that.
#
# Rules fixed BEFORE the first run (2026-11-18):
#   Blocks: consecutive runs of 8 published or heard lines (fixed, not tuned).
#   Block weight: normalised word entropy of the block, H / ln(N), N = words in the block (0 when one word repeats; 1 when all differ).
#   Weighted density = sum(w_b * rhymed_b) / sum(w_b * syllables_b), with rhymed_b = density_b * syllables_b from rhyme_profile._rhyme_density.
#   Baseline (unweighted) = rhyme_profile._rhyme_density over the whole text.
#   Truth = the baseline on the PUBLISHED lines. Compared on the same 64 tracks as rhyme_near_eval.py, heard words only.
#   PASS: weighted wins if |bias| against truth is smaller than the baseline's AND its Spearman rank against truth is at least as high.
#   Known limits, written first: the heard lines are cut by a 0.6 s gap, so they are not the published lines; repeated hooks in the
#   published text are the same words, so the truth itself contains them; one block size only.
import glob, json, math, re, statistics as st, sys
import os
REF_DIR = os.environ.get("MCSOC_REFERENCE_DIR", "reference-stats")   # your own reference tables; none ship with the repo
sys.path.insert(0, REF_DIR)
import rhyme_profile as rp
from scipy.stats import spearmanr

BLOCK = 8


def blocks(lines):
    return [lines[i:i + BLOCK] for i in range(0, len(lines), BLOCK)]


def block_weight(block_lines):
    words = [w for l in block_lines for w in rp._words(l)]
    n = len(words)
    if n < 2:
        return 0.0
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    h = -sum((c / n) * math.log(c / n) for c in counts.values())
    return h / math.log(n)


def syllables(block_lines, pron):
    return sum(sum(rp._is_vowel(p) for p in (pron(w) or [])) for l in block_lines for w in rp._words(l))


def entropy_density(lines, pron):
    """Entropy-weighted rhyme density over blocks of BLOCK lines. 0.0 when no block has syllables."""
    num = den = 0.0
    for b in blocks(lines):
        s = syllables(b, pron)
        if s == 0:
            continue
        w = block_weight(b)
        d = rp._rhyme_density(b, pron)
        num += w * d * s
        den += w * s
    return num / den if den else 0.0


def synced_lines(d):
    out = []
    for l in (d.get("synced") or "").splitlines():
        m = re.match(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$", l.strip())
        if m and not re.fullmatch(r"\[.*\]", m[3].strip()) and rp._words(m[3]):
            out.append(m[3])
    return out


def heard_lines(H, gap=0.6):
    ws = sorted((a, x) for a, b, w, p in H["a"] for x in rp._words(w))
    lines, cur, prev = [], [], None
    for t, x in ws:
        if prev is not None and t - prev > gap and cur:
            lines.append(" ".join(cur)); cur = []
        cur.append(x); prev = t
    if cur: lines.append(" ".join(cur))
    return lines


if __name__ == "__main__":
    import glob as _g
    pron = rp.cmu_pron()
    rows = []
    for W in (os.path.join(REF_DIR, "crate-drafts/lyrics-work"), os.path.join(REF_DIR, "crate-drafts/holdout-work")):
        for f in sorted(_g.glob(f"{W}/*.json")):
            d = json.load(open(f))
            if not d.get("synced"): continue
            try: H = json.load(open(f.replace(".json", ".heard2")))
            except OSError: continue
            pub = synced_lines(d); hd = heard_lines(H)
            if len(pub) < 8 or len(hd) < 8: continue
            truth = rp._rhyme_density(pub, pron)
            base = rp._rhyme_density(hd, pron)
            wtd = entropy_density(hd, pron)
            rows.append((truth, base, wtd))
    print("tracks usable", len(rows))
    T = [r[0] for r in rows]; B = [r[1] for r in rows]; W = [r[2] for r in rows]
    print("truth (published, baseline rule):  median %.3f" % st.median(T))
    for name, X in (("heard baseline", B), ("heard entropy-weighted", W)):
        bias = st.mean(x - t for x, t in zip(X, T))
        rho = float(spearmanr(X, T)[0])
        print("%-24s median %.3f  bias %+.3f  rank vs truth %.2f" % (name, st.median(X), bias, rho))
