"""Measure a voice-only WAV for the Act seam: prints {"values": {...}, "seconds": n} as JSON, numbers only.

Run with the measuring environment, which holds the pitch tracker and the heard-words helper:
  venv-speaker/bin/python measure_voice_act.py VOICE.wav MEASURE [MEASURE...]

It reuses reference-stats/flow_profile.py (profile with the heard rate and the neural pitch on). Words the speech server
hears are counted and dropped inside that module; nothing but the numbers printed here leaves this process. Anything that
is not a finite number, or whose name is not one of the requested measures, is dropped before printing.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def numbers_only(profile, wanted):
    """Keep only the requested measures whose values are finite numbers (not bools, not text)."""
    values = {}
    for name in wanted:
        v = profile.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if not math.isfinite(v):
            continue
        values[name] = float(v)
    return values


def main(argv):
    if len(argv) < 3:
        print("usage: measure_voice_act.py VOICE.wav MEASURE [MEASURE...]", file=sys.stderr)
        return 2
    wav, wanted = argv[1], argv[2:]
    sys.path.insert(0, os.path.join(HERE, "reference-stats"))
    import flow_profile  # heavy: pitch tracker, imported only when a measure is really asked for
    prof = flow_profile.profile("act", "voice", wav, wav + ".f0.npy", want_heard=True, want_neural=True)
    seconds = prof.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        print("error: no duration measured", file=sys.stderr)
        return 1
    print(json.dumps({"values": numbers_only(prof, wanted), "seconds": float(seconds)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
