"""Persona links: a persona points at a measured card and holds the production values that card calls for.

One shape for every origin (canon character, crate side, analysed table): the card records its own basis, so the link
only names it. Stdlib only. Numbers and labels only; no names from the reference data.

A link file (personas/links/<id>.json):
  {"schema_version": 1, "id": "rapid-melodic-lead", "voice": "af_heart", "card": "rapid-melodic",
   "beat": null, "settings": {"bpm": 98, "beat_style": "boombap", "sing": ["--beat-gain", "5.75"]} | null, "note": "..."}

Checks: id matches the file name; voice is a Kokoro voice name; the card exists in personas/ and is a voice card;
beat is null or an existing beat card; settings is null or uses only the allowed keys with the allowed types.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINKS = HERE / "personas" / "links"
CARDS = HERE / "personas"
VOICE = re.compile(r"^[a-z]{2}_[a-z]+$")
BEAT_STYLES = {"boombap", "noir", "dusty", "lofi", "chiptune", "darkchip", "trap"}
KEYS = {"bpm": (int, float), "beat_style": str, "sing": list}


def card_names(cards_dir=CARDS):
    out = {}
    for f in Path(cards_dir).glob("*.json"):
        try:
            out[f.stem] = json.loads(f.read_text()).get("kind")
        except (OSError, ValueError):
            pass
    return out


def check(link, file_stem, cards):
    errs = []
    if link.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    if link.get("id") != file_stem:
        errs.append(f"id {link.get('id')!r} does not match file name {file_stem!r}")
    if not isinstance(link.get("voice"), str) or not VOICE.match(link["voice"]):
        errs.append("voice must be a Kokoro voice name such as af_heart")
    card = link.get("card")
    if card not in cards:
        errs.append(f"card {card!r} is not in personas/")
    elif cards[card] != "voice":
        errs.append(f"card {card!r} is not a voice card")
    beat = link.get("beat")
    if beat is not None and beat not in cards:
        errs.append(f"beat {beat!r} is not in personas/")
    s = link.get("settings")
    if s is not None:
        if not isinstance(s, dict):
            errs.append("settings must be null or an object")
        else:
            for k, v in s.items():
                if k not in KEYS:
                    errs.append(f"settings.{k}: not an allowed key")
                elif not isinstance(v, KEYS[k]) or isinstance(v, bool):
                    errs.append(f"settings.{k}: wrong type")
            if "beat_style" in s and s["beat_style"] not in BEAT_STYLES:
                errs.append(f"settings.beat_style {s['beat_style']!r} is not a beat style")
            if "sing" in s and not all(isinstance(x, str) for x in s["sing"]):
                errs.append("settings.sing: only strings (flags and their values)")
    if set(link) - {"schema_version", "id", "voice", "card", "beat", "settings", "note"}:
        errs.append("unexpected fields: " + ", ".join(sorted(set(link) - {"schema_version", "id", "voice", "card", "beat", "settings", "note"})))
    return errs


def load_all(links_dir=LINKS, cards_dir=CARDS):
    cards = card_names(cards_dir)
    out, errors = {}, {}
    for f in sorted(Path(links_dir).glob("*.json")):
        link = json.loads(f.read_text())
        e = check(link, f.stem, cards)
        if e:
            errors[f.name] = e
        else:
            out[f.stem] = link
    return out, errors


def main(argv):
    links, errors = load_all()
    for f, e in errors.items():
        print(f"ERROR {f}:", *e, sep="\n  - ")
    print(f"{len(links)} persona link(s) ok, {len(errors)} with errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
