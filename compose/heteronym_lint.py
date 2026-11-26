"""Catch words a speech engine says wrongly because the spelling does not say which word it is (heteronyms), before a render. Stdlib only.
    python3 heteronym_lint.py FILE [FILE ...] [--no-review]      exit 1 if any ERROR, 0 otherwise

Why: the engine picks ONE pronunciation per spelling. The worst case in our scripts is the past tense of "read" (said "red"): it comes out "reed", so "I have read enough" is spoken
as "I have reed enough". It was heard at about 49 s of a render, and a text check is the only reliable one (a speech-to-text pass writes the same letters for either sound).
  ERROR   "read" in the past tense, or where the tense cannot be told from the sentence. Fix by rewording (looked at, went through, studied, opened), not by respelling.
          "read" is safe after to / will / would / can / could / should / must / may / might / do / does / did (+ not), after please and let, and as the first word of a sentence
          (an order). Everything else is flagged.
  INLINE  word{say} in a line says that one use as "say" (read{red}): for deliberate wordplay where rewording would lose the point. It is not reported.
  REVIEW  other words with two pronunciations (record, lead, live, wind, tear, bass, close, present, object, minute, wound, ...). Listen to the render, or respell the word in
          pronounce.txt (whole words, case-sensitive, as sing.pronounce does). A word whose exact spelling is already a key in pronounce.txt is not reported.
Reads script files (Name: line), lyrics files (@voice, [Section] headers, stage directions in parentheses) and plain text; skips comments (#), cast lines, [directions] and @voice lines."""
import os, re, sys
from collections import namedtuple

Finding = namedtuple("Finding", "line word level reading text hint")
HERE = os.path.dirname(os.path.abspath(__file__))

REVIEW_WORDS = {
    "record": "noun REH-kerd / verb rih-KORD", "lead": "metal led / verb leed", "live": "adjective lyve / verb liv", "wind": "air wind / verb wynd",
    "tear": "rip tair / eye tear", "bass": "fish bas / music bayss", "close": "near klohs / shut klohz", "present": "gift PREZ-ent / verb prih-ZENT",
    "object": "thing OB-jekt / verb ob-JEKT", "minute": "time MIN-it / tiny my-NOOT", "wound": "injury woond / past of wind wownd", "row": "line roh / argument rau",
    "bow": "ribbon boh / bend bau", "sow": "plant soh / pig sau", "refuse": "trash REF-yoos / verb rih-FYOOZ", "content": "noun KON-tent / adjective kon-TENT",
    "console": "noun KON-sohl / verb kon-SOHL", "project": "noun PROJ-ekt / verb pro-JEKT", "produce": "noun PROH-doos / verb pro-DOOS", "permit": "noun PER-mit / verb per-MIT", "address": "noun AD-res / verb uh-DRES", "use": "noun yoos / verb yooz", "progress": "noun PROG-res / verb pro-GRES",
    "contract": "noun KON-trakt / verb kon-TRAKT", "digest": "noun DY-jest / verb dy-JEST", "separate": "adjective SEP-rit / verb SEP-uh-rayt",
    "alternate": "adjective AWL-ter-nit / verb AWL-ter-nayt", "desert": "dry DEZ-ert / leave dih-ZERT", "resume": "noun REZ-oo-may / verb rih-ZOOM",
    "subject": "noun SUB-jekt / verb sub-JEKT", "invalid": "ill IN-vuh-lid / not valid in-VAL-id", "entrance": "door EN-trans / verb en-TRANS",
}
READ_PRESENT_BEFORE = {"to", "will", "would", "can", "could", "should", "shall", "must", "may", "might", "please", "let", "lets", "do", "does", "did", "cannot",
                       "dont", "doesnt", "didnt", "wont", "cant", "couldnt", "shouldnt", "wouldnt"}
READ_NOT_AFTER = {"do", "does", "did", "will", "would", "can", "could", "should", "shall", "must", "may", "might"}
READ_PAST_BEFORE = {"have", "has", "had", "having", "was", "were", "been", "being", "ive", "hed", "shed", "weve", "theyve", "youve", "ive"}
READ_PAST_WORDS = {"yesterday", "ago", "earlier", "previously", "last"}
SKIP_PAREN = re.compile(r"\((sung|break|no music|slot|meaning|names|vocal|hold|from your|break in|break out)", re.I)
TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
SENT_END = re.compile(r"[.!?]")
HINT_READ = "reword it (looked at, went through, studied, opened): the engine says past-tense read as 'reed'"


def pron_keys(pron_file):
    f = pron_file if pron_file is not None else os.path.join(HERE, "pronounce.txt")
    keys = set()
    if os.path.exists(f):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if "=" in line and not line.lstrip().startswith("#"):
                    keys.add(line.split("=", 1)[0])
    return keys


def _norm(t):
    return t.lower().replace("'", "")


def classify_read(tokens, i, sentence_words):
    """'present' if the tense is certain to be present, 'past' if certain, else 'ambiguous'. tokens: words before this sentence-part, i: index of 'read'."""
    prev = [_norm(t) for t in tokens[:i]]
    if not prev:
        return "present"  # first word of a sentence: an order
    p1 = prev[-1]
    p2 = prev[-2] if len(prev) > 1 else ""
    if p1 == "not" and p2 in READ_NOT_AFTER:
        return "present"
    if p1 in READ_PRESENT_BEFORE:
        return "present"
    if p1 in READ_PAST_BEFORE or (p2 in READ_PAST_BEFORE and p1 in {"already", "just", "never", "only", "not", "also", "ever"}):
        return "past"
    if any(_norm(w) in READ_PAST_WORDS for w in sentence_words):
        return "past"
    return "ambiguous"


def check_line(lineno, text, keys):
    out = []
    # split into sentences so "first word of a sentence" is known
    pos = 0
    for part in re.split(r"(?<=[.!?])\s+", text):
        words = TOKEN.findall(part)
        for i, w in enumerate(words):
            lw = w.lower()
            if w in keys:
                continue
            if lw == "read":
                kind = classify_read(words, i, words)
                if kind != "present":
                    out.append(Finding(lineno, w, "error", kind, text.strip()[:110], HINT_READ))
            elif lw in REVIEW_WORDS:
                out.append(Finding(lineno, w, "review", "two sounds", text.strip()[:110], REVIEW_WORDS[lw]))
        pos += len(part)
    return out


def spoken(line):
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("@") or s.startswith("[") or s.lower().startswith("cast:"):
        return None
    if s.startswith("(") and SKIP_PAREN.match(s):
        return None
    m = re.match(r"^[A-Za-z][\w ]{0,20}:\s+(.*)$", s)  # a speaker prefix, but not a URL (no space after the colon in a URL)
    return m.group(1) if m else s


INLINE_SAY = re.compile(r"\b[\w']+\{([^{}\n]+)\}")


def inline_say(text):
    """word{say} -> say: one use of a word spoken another way (deliberate wordplay on a heteronym). sing.py, lint_lyrics.py and check_track.py
    apply this to a sheet before anything else, so the voice, the syllable counts and the rhyme measures all follow the sound."""
    return INLINE_SAY.sub(r"\1", text)


def check_text(text, pron_file=None):
    keys = pron_keys(pron_file)
    text = inline_say(text)
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        s = spoken(line)
        if s:
            found += check_line(n, s, keys)
    return found


def check_file(path, pron_file=None):
    with open(path, encoding="utf-8") as fh:
        return check_text(fh.read(), pron_file)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    review = "--no-review" not in argv
    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__.splitlines()[0]); return 2
    errors = 0
    for p in files:
        for f in check_file(p):
            if f.level == "review" and not review:
                continue
            print(f"{p}:{f.line}: {f.level.upper():6} {f.word} ({f.reading}): {f.hint}\n         {f.text}")
            errors += f.level == "error"
    print(f"{errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
