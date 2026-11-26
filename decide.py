#!/usr/bin/env python3
"""Decide: propose how an approved lesson could become content. Read-only, stdlib only.

Input: approved, verify-clean lesson records (the shared gate), persona cards, and feedback counts.
Output: a brief per lesson listing candidate forms, voice cards whose form mapping fits, and beat
cards as unranked options. It proposes; a person chooses. It generates nothing and writes nothing
except stdout. Mapping is by trait and form only (never by name). Feedback is counts, not text.
"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # python3 -I drops the script dir
import gate, feedback

def load_cards(cards_dir):
    cards = [json.loads(p.read_text()) for p in sorted(Path(cards_dir).glob("*.json"))]
    return [c for c in cards if c.get("kind") == "voice"], [c for c in cards if c.get("kind") == "beat"]

def brief(rec, voices, beats, by_form):
    forms = rec.get("form_hint") or ["spoken-rhyme", "sung-hook", "skit"]
    options = []
    for form in forms:
        fits = [c["card"] for c in voices if form in c.get("form_hint", [])]
        options.append({"form": form, "voice_cards": fits, "feedback_score": by_form.get(form, 0)})
    # a form with a fitting voice card and a better feedback score comes first; ties keep record order
    options.sort(key=lambda o: (-(1 if o["voice_cards"] else 0), -o["feedback_score"]))
    return {"lesson": rec["id"], "tags": rec.get("tags", []), "options": options,
            "beat_cards": [c["card"] for c in beats],
            "note": "beat cards are not mapped to forms (no measured link yet); pick by ear",
            "next": "a person picks one option; Act drafts lyrics, then verify and sign-off as usual"}

def propose(root):
    root = Path(root)
    ok, errors, _ = gate.publishable(root / "records")
    if errors:
        raise ValueError("records failed verify: " + ", ".join(sorted(errors)))
    voices, beats = load_cards(root / "personas")
    by_form = feedback.summarize(root)["by_form"]
    return [brief(r, voices, beats, by_form) for r in ok]

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args()
    try:
        out = propose(a.root)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr); return 1
    print(json.dumps(out, indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
