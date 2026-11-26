#!/usr/bin/env python3
"""Act: the seam between a chosen brief and an engine, plus the target-versus-achieved comparison. Stdlib only.

A person picks one option from `decide.py` (lesson, form, voice card). `run` checks the pick against the same brief, asks an **engine** to make
the piece, and compares what the measuring side read from it with the card's bands (p10 to p90 of the reference rows the card was cut from).
It is generate-only: it never writes sign-off, never publishes, and the report says `status: generated`.

An engine is an adapter (like a memory system or a review surface): `render(target)` returns `{"values": {measure: number}, "seconds": number}`.
The engine, or the measuring tool beside it, does the audio and the measuring; the core sees numbers only. A result with any other key,
a string, a list or a non-finite number is refused, so text or audio descriptions cannot ride along. The only engine here is `FakeEngine`;
real engines live outside this repository (design decision 21).

Bands are what the reference rows spanned, not a promise about taste. Inside a band means "like the reference"; it says nothing about quality.
A render under MIN_SECONDS of material is not scored (short pieces wobble; see the roadmap's planted-change checks).
"""
import argparse, json, math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # python3 -I drops the script dir
import decide

MIN_SECONDS = 60.0
RESULT_KEYS = {"values", "seconds"}


def _num(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"{what} must be a finite number")
    return float(x)


def target(card, form):
    """Numeric bands for one voice card and form. Refuses a card with no measured bands."""
    if card.get("kind") != "voice":
        raise ValueError("targets come from voice cards (no measured link from beat to form exists)")
    bands = {}
    for name, b in (card.get("measured") or {}).items():
        try:
            bands[name] = {"low": _num(b["p10"], name), "mid": _num(b["median"], name), "high": _num(b["p90"], name)}
        except (KeyError, TypeError):
            raise ValueError(f"card {card.get('card')}: measure {name} lacks p10, median and p90")
    if not bands:
        raise ValueError(f"card {card.get('card')} has no measured bands to aim at")
    return {"card": card["card"], "form": form, "n_tracks": card.get("n_tracks"), "bands": bands}


def compare(tgt, values, seconds=None):
    """Where each measured value sits against its band. `gap` is 0 inside, else the signed distance to the nearest edge."""
    for k, v in values.items():
        _num(v, k)
    if seconds is not None and _num(seconds, "seconds") < MIN_SECONDS:
        return {"scored": 0, "inside": 0, "measures": {}, "unscored": sorted(values),
                "missing": sorted(tgt["bands"]),
                "reason": f"under {MIN_SECONDS:g} s of material; not scored"}
    out, unscored = {}, []
    for name, v in values.items():
        b = tgt["bands"].get(name)
        if b is None:
            unscored.append(name); continue
        v = float(v)
        where, gap = ("below", v - b["low"]) if v < b["low"] else ("above", v - b["high"]) if v > b["high"] else ("inside", 0.0)
        out[name] = {"value": round(v, 3), "where": where, "gap": round(gap, 3), "from_median": round(v - b["mid"], 3)}
    # card measures the engine did not return: named, so a partial measurement cannot look complete
    missing = sorted(set(tgt["bands"]) - set(values))
    return {"scored": len(out), "inside": sum(1 for m in out.values() if m["where"] == "inside"),
            "measures": out, "unscored": sorted(unscored), "missing": missing}


class Engine:
    """Adapter seam. Subclass, set `name`, implement `render`. Copy the shape of FakeEngine."""
    name = "engine"

    def render(self, tgt):
        raise NotImplementedError


class FakeEngine(Engine):
    """Returns fixed numbers, as if the measuring side had read a render. For tests and for showing the loop with no GPU."""
    name = "fake"

    def __init__(self, values, seconds):
        self.values, self.seconds = dict(values), seconds

    def render(self, tgt):
        return {"values": dict(self.values), "seconds": self.seconds}


def _clean(result):
    if not isinstance(result, dict) or set(result) != RESULT_KEYS or not isinstance(result["values"], dict):
        raise ValueError("engine result must be exactly {values, seconds}, numbers only")
    for k, v in result["values"].items():
        if not isinstance(k, str): raise ValueError("measure names must be strings")
        _num(v, k)
    _num(result["seconds"], "seconds")
    return result


def run(root, lesson, form, card, engine):
    """Check the pick against the brief, render, compare. Raises ValueError on anything the brief did not offer."""
    briefs = {b["lesson"]: b for b in decide.propose(root)}  # raises if verify fails; only approved lessons appear
    if lesson not in briefs:
        raise ValueError(f"lesson {lesson} is not approved and verify-clean")
    opt = {o["form"]: o for o in briefs[lesson]["options"]}.get(form)
    if opt is None:
        raise ValueError(f"form {form} is not offered for {lesson}")
    if card not in opt["voice_cards"]:
        raise ValueError(f"card {card} does not fit form {form} for {lesson}")
    cards, _ = decide.load_cards(Path(root) / "personas")
    tgt = target(next(c for c in cards if c["card"] == card), form)
    res = _clean(engine.render(tgt))
    return {"lesson": lesson, "form": form, "card": card, "engine": engine.name, "status": "generated",
            "target": tgt, "seconds": res["seconds"], "values": res["values"], "comparison": compare(tgt, res["values"], res["seconds"]),
            "next": "lyrics and audio still need verify and a person's sign-off; this report approves nothing"}


def summarize(reports):
    """Counts per measure over many reports: how many renders fell inside, below or above the band."""
    s = {}
    for r in reports:
        for name, m in r["comparison"]["measures"].items():
            row = s.setdefault(name, {"n": 0, "inside": 0, "below": 0, "above": 0})
            row["n"] += 1; row[m["where"]] += 1
    return s


def contrast_measures(con):
    """Measures a mood contrast may score, with the direction the reference showed. Measures that were not shown are left out."""
    return {m: v["expect"] for m, v in con["measures"].items() if v.get("status") in ("found", "replicated")}


def contrast(con, rep_a, rep_b):
    """Paired check: the same voice and lesson rendered for the two sides of a mood contrast (a minus b), against the direction real
    artists showed within their own catalogue. One pair is a reading, not a test: use `contrast_summary` over many pairs."""
    out = {"contrast": con["contrast"], "pairs": 1, "measures": {}, "not_scored": {},
           "note": "one pair is a reading, not a test; count agreement over many pairs"}
    for m, v in con["measures"].items():
        if m not in contrast_measures(con):
            out["not_scored"][m] = f"{v.get('status', 'untested')} in the reference"
    for r in (rep_a, rep_b):
        if _num(r["seconds"], "seconds") < MIN_SECONDS:
            out["reason"] = f"under {MIN_SECONDS:g} s of material on one side; not compared"; return out
    for m, way in contrast_measures(con).items():
        if m not in rep_a["values"] or m not in rep_b["values"]:
            continue
        d = _num(rep_a["values"][m], m) - _num(rep_b["values"][m], m)
        ref = sum(con["measures"][m]["diffs"]) / len(con["measures"][m]["diffs"])
        out["measures"][m] = {"diff": round(d, 3), "expect": way, "agrees": d > 0 if way == "higher" else d < 0,
                              "reference_diff": round(ref, 3), "vs_reference": round(d / ref, 3)}
    return out


def contrast_summary(pairs):
    s = {}
    for p in pairs:
        for m, v in p["measures"].items():
            row = s.setdefault(m, {"pairs": 0, "agree": 0}); row["pairs"] += 1; row["agree"] += bool(v["agrees"])
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--lesson", required=True); ap.add_argument("--form", required=True); ap.add_argument("--card", required=True)
    ap.add_argument("--measured", required=True, help='JSON file {"values": {measure: number}, "seconds": number} from the measuring side')
    a = ap.parse_args()
    try:
        res = json.loads(Path(a.measured).read_text())
        eng = FakeEngine(res.get("values", {}), res.get("seconds")) if set(res) == RESULT_KEYS else None
        if eng is None:
            raise ValueError("measured file must be exactly {values, seconds}")
        eng.name = "measured-file"
        print(json.dumps(run(a.root, a.lesson, a.form, a.card, eng), indent=2)); return 0
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
