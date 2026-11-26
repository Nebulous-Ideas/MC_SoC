#!/usr/bin/env python3
"""Summarise feedback for Decide. Stdlib only.

Counts coarse signals by tag and by content form. The free text is NEVER included: feedback
is data, and what Decide reads is counts, not words (so a comment cannot carry instructions
into a later step). Only feedback that passes verify is counted; the rest is reported.
"""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I drops the script dir
import verify as V

WEIGHT = {"keep": 1, "more-like-this": 1, "drop": -1, "less-like-this": -1, "change": 0}

def summarize(root):
    root = Path(root)
    res = V.verify_all(root)
    works = V.load_dir(root / "works")
    lessons = V.load_dir(root / "records")
    by_tag, by_form, rejected = Counter(), Counter(), []
    for path, errs in res.items():
        if not path.startswith("feedback/"):
            continue
        if errs:
            rejected.append(path); continue
        fb = json.loads((root / path).read_text())
        w = WEIGHT.get(fb.get("signal", ""), 0)
        if not w:
            continue
        for t in fb.get("tags", []):
            by_tag[t] += w
        target = works.get(fb["target"]) or {}
        if target.get("form"):
            by_form[target["form"]] += w
        elif fb["target"] in lessons:
            for form in lessons[fb["target"]].get("form_hint", []):
                by_form[form] += w
    return {"by_tag": dict(by_tag), "by_form": dict(by_form), "rejected": rejected}

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent)
    print(json.dumps(summarize(root), indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
