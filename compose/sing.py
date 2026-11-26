#!/usr/bin/env python3
"""Speak a lyrics file with the speech server (Kokoro via an OpenAI-compatible speech API such as Speaches), lock it to a beat, and play it.

Run it yourself:  python3 sing.py --lyrics lyrics-mtu.txt --beat beat-mtu.wav --bpm 104 --voice bm_george
Set SPEECH_URL and SPEECH_KEY first (the key is never printed or saved).

Rhythm mode (default): every line is spoken on its own, time-stretched (pitch kept) to fit a whole number of beats, and started on a bar
line, so it sits on the beat like a rap instead of a reading. Stanzas are separated by a bar of rest, and the beat is ducked under the voice.
  --plain       old behaviour: one request per stanza, laid over the beat as it comes
  --bpm N       tempo of the beat file (98 beat.wav, 78 beat-noir.wav, 104 beat-mtu.wav)
  --voice NAME  default voice; a stanza starting with "@voice NAME" uses another one (falls back to --voice if the server lacks it)
  --adlib-voice NAME   voice for (parenthesised) ad-lib lines, default af_bella
  --self-test   no server call: mixes test tones, to check the timing and mixing
Layered voices: "@voice bm_george+af_heart" makes two voices speak the same stanza together (panned a little apart).
Robot voice (the deadpan synthetic-speech sound of nerdcore): "@voice bm_george:robot" runs that voice through a vocoder-style filter;
it can be layered with a human voice, e.g. "@voice bm_george:robot+af_heart". It is an effect, not an impression of anyone.
Ad-libs: a line written as (like this) is spoken by the ad-lib voice, left of centre, in a two-beat gap right after the line before it
(an answer, never over its words). (+like this) lays it over the last two beats of that line instead.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave

import numpy as np

HOST = os.environ.get("SPEECH_URL", "http://localhost:8000")
HERE = os.path.dirname(os.path.abspath(__file__))
SR = 44100


def api_key() -> str:
    """The speech server's API key, from the SPEECH_KEY environment variable. Set it yourself before running; this code never reads it from anywhere else and never prints it."""
    key = os.environ.get("SPEECH_KEY", "").strip()
    if not key:
        sys.exit("set SPEECH_KEY (and SPEECH_URL) to your speech server's API key and address; see compose/README.md")
    return key


def call(path, key, payload=None):
    req = urllib.request.Request(f"{HOST}{path}", data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"speech server said {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")


def stanzas(text):
    """Yield (voices or None, [(is_adlib, text)]). "@voice A" or "@voice A+B" (layered) sets the voices for the lines after it, and may
    appear again inside a stanza to hand the next line to another voice."""
    for block in re.split(r"\n\s*\n", text.strip()):
        voices, items = None, []
        for l in (x.strip() for x in block.splitlines()):
            if not l or re.match(r"^\[.*\]$", l):
                continue
            if l.startswith("@voice "):
                if items:
                    yield voices, items
                voices, items = [v.strip() for v in l.split(None, 1)[1].split("+")], []
            else:
                items.append((True, l[1:-1].strip()) if re.fullmatch(r"\(.*\)", l) else (False, l))
        if items:
            yield voices, items


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, check=True).stdout)


def read_wav(path):
    with wave.open(path) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        return raw.reshape(-1, w.getnchannels()).mean(axis=1)


CACHE = os.path.join(HERE, "cache")
_SERVER = {}


def server():
    """(api key, model id): looked up on first use, so a run whose speech is all cached never needs the key."""
    if not _SERVER:
        key = api_key()
        models = json.loads(call("/v1/models", key))["data"]
        model = next((m["id"] for m in models if "kokoro" in m["id"].lower()), None)
        if not model:
            sys.exit("no Kokoro model on the speech server; models there: " + ", ".join(m["id"] for m in models))
        os.makedirs(CACHE, exist_ok=True)
        open(os.path.join(CACHE, "model.txt"), "w").write(model)
        _SERVER.update(key=key, model=model)
    return _SERVER["key"], _SERVER["model"]


def model_id():
    f = os.path.join(CACHE, "model.txt")
    return open(f).read().strip() if os.path.exists(f) else server()[1]


def pronounce(text):
    """Respell words the speech model says wrongly (pronounce.txt): the node called Lead is the metal, 'led', not 'leed'."""
    f = os.path.join(HERE, "pronounce.txt")
    if os.path.exists(f):
        for line in open(f):
            if "=" in line and not line.lstrip().startswith("#"):
                a, b = line.rstrip("\n").split("=", 1)
                text = re.sub(rf"\b{re.escape(a)}(?![\w'])" if not a.endswith("'s") else rf"\b{re.escape(a)}\b", b, text)
    return text


def speak(_key, _model, voice, fallback, text, path):
    os.makedirs(CACHE, exist_ok=True)
    text = pronounce(text)
    model = model_id()
    for v in dict.fromkeys([voice or fallback, fallback]):
        cached = os.path.join(CACHE, hashlib.sha1(f"{model}|{v}|{text}".encode()).hexdigest() + ".wav")
        if os.path.exists(cached):
            open(path, "wb").write(open(cached, "rb").read())
            return v
        try:
            data = call("/v1/audio/speech", server()[0], {"model": model, "voice": v, "input": text, "response_format": "wav"})
            open(cached, "wb").write(data)
            open(path, "wb").write(data)
            return v
        except RuntimeError as e:
            print(f"  voice {v!r} failed ({e}); trying the default")
    sys.exit(f"the speech server refused every voice for: {text[:40]!r}")


ROBOT = "afftfilt=real='hypot(re,im)*cos(0)':imag='hypot(re,im)*sin(0)':win_size=512:overlap=0.75,volume=1.6"


def split_voice(v):
    """"name:robot" -> ("name", True)"""
    if v and v.endswith(":low"):
        return v[:-4], "low"
    return (v[:-6], True) if v and v.endswith(":robot") else (v, False)


FLATTEN = 1.0
TAIL_SOFTEN = 0.0


def tail_soften(path, ms):
    """Low-pass the last `ms` of a 16-bit mono clip at 3 kHz, crossfaded in over that span, so a word's end does not carry a
    sibilant hiss (the 'loan' end read as 'loans' in the 2026-11-18 Shoulders take). Off unless --tail-soften is given."""
    import wave as _w
    from scipy.signal import butter, sosfiltfilt
    with _w.open(path, "rb") as w:
        sr, raw = w.getframerate(), w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    k = min(len(x), int(sr * ms / 1000.0))
    if k < 8: return
    y = sosfiltfilt(butter(4, 3000.0, btype="low", fs=sr, output="sos"), x)
    ramp = np.zeros(len(x)); ramp[-k:] = np.linspace(0.0, 1.0, k)
    out = x * (1 - ramp) + y * ramp
    f = min(len(x), int(sr * 0.04))                 # the last 40 ms fade to silence: the hiss sits at the very end of the clip
    out[-f:] *= np.linspace(1.0, 0.0, f)
    out = np.clip(np.round(out), -32768, 32767).astype("<i2")
    with _w.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(out.tobytes())


def flatten_pitch(path, f):
    """Compress the clip's pitch movement toward its own median (WORLD analysis/synthesis; f=1 untouched, 0.6 = 60% of the swing).
    Needs pyworld, so run with venv-speaker. Reference flow measurements: one human rapper measured moves ~2.9 st per 2 s window, flat TTS ~4.4."""
    import pyworld as pw
    x = read_wav(path).astype(np.float64)
    f0, t = pw.harvest(x, SR, f0_floor=70.0, f0_ceil=500.0, frame_period=5.0)
    v = f0 > 0
    if v.sum() < 20: return
    sp = pw.cheaptrick(x, f0, t, SR); ap = pw.d4c(x, f0, t, SR)
    med = np.median(np.log2(f0[v]))
    f0n = f0.copy(); f0n[v] = 2 ** (med + (np.log2(f0[v]) - med) * f)
    y = pw.synthesize(f0n, sp, ap, SR, 5.0)
    y = y[:len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))
    y *= (np.abs(x).max() / (np.abs(y).max() or 1.0))
    import wave as _w
    with _w.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def clean_clip(src, dst, robot=False):
    """Trim leading/trailing silence (so every voice's first sound lands exactly on the beat), cut sub-70 Hz rumble and DC, and
    fade the edges (8 ms in, 40 ms out) so a clip never starts or stops with a click."""
    trim = "silenceremove=start_periods=1:start_threshold=-42dB:start_duration=0.01:detection=peak"
    ffmpeg("-i", src, "-af", f"highpass=f=70,{trim},areverse,{trim},afade=t=in:d=0.04,areverse,afade=t=in:d=0.008", "-ar", str(SR), "-ac", "1", dst)
    if duration(dst) < 0.15:                      # nothing but silence was found: keep the original rather than lose the line
        ffmpeg("-i", src, "-af", "afade=t=in:d=0.008,areverse,afade=t=in:d=0.04,areverse", "-ar", str(SR), "-ac", "1", dst)
    if robot == "low":                            # same speaker, ~15% lower pitch (resample down, then restore the speed)
        tmp_out = dst + ".l.wav"
        ffmpeg("-i", dst, "-af", f"asetrate={SR * 0.85:.0f},aresample={SR},atempo={1 / 0.85:.4f}", "-ar", str(SR), "-ac", "1", tmp_out)
        os.replace(tmp_out, dst)
    elif robot:                                   # zero every phase: the voice keeps its words and loses its pitch movement
        tmp_out = dst + ".r.wav"
        ffmpeg("-i", dst, "-af", ROBOT.split(",volume")[0], "-ar", str(SR), "-ac", "1", tmp_out)
        peak = float(np.abs(read_wav(tmp_out)).max()) or 1.0      # the vocoder loses level: bring the clip back to a 0.6 peak
        ffmpeg("-i", tmp_out, "-af", f"volume={0.6 / peak:.3f},alimiter=limit=0.9", "-ar", str(SR), "-ac", "1", dst)
    if FLATTEN < 1.0 and not robot:
        flatten_pitch(dst, FLATTEN)
    if TAIL_SOFTEN > 0:
        tail_soften(dst, TAIL_SOFTEN)


def onset_offset(audio, maxms=90):
    """Seconds from the start of a clip to where it first reaches 30% of its peak. A word that begins with a soft consonant (s, f, th) feels
    late if that consonant sits on the beat; the loud part (the vowel) is what the ear lines up, so the clip is started that much earlier."""
    env = np.convolve(np.abs(audio), np.ones(int(0.004 * SR)) / int(0.004 * SR), mode="same")
    if env.max() <= 0:
        return 0.0
    return min(int(np.argmax(env > env.max() * 0.30)) / SR, maxms / 1000)


MAXF = 1.45
FLOWSTATS = []
LINELOG = []          # (start s, slot s, text) of every spoken line as placed: written next to the song as NAME.lines.json for check_track.py
LASTF = 1.0
TARGETF = None


def fit_to_beats(src, dst, beat, force=None, fill=0.92):
    """Time-stretch (pitch kept) so the line fills a whole number of beats; returns how many beats it takes."""
    d = duration(src)
    if force:
        target = force
        factor = min(max(d / (target * beat * fill), 0.8), 1.8)
    else:
        if TARGETF:                                   # steady pace: the slot whose stretch is closest to TARGETF
            target = min((2, 4, 6, 8, 12, 16), key=lambda t: abs(d / (t * beat * 0.92) - TARGETF))
            factor = d / (target * beat * 0.92)
        else:
          for target in (2, 4, 6, 8, 12, 16):
            factor = d / (target * beat * 0.92)       # >1 speeds up
            if factor <= MAXF:
                break
        factor = min(max(factor, 0.8), MAXF)          # never slower than 80% or faster than MAXF
    global LASTF
    LASTF = factor
    ffmpeg("-i", src, "-filter:a", f"atempo={factor:.4f}", "-ar", str(SR), "-ac", "1", dst)
    return target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--lyrics", default="lyrics.txt")
    ap.add_argument("--beat", default="beat.wav")
    ap.add_argument("--bpm", type=float, default=98)
    ap.add_argument("--adlib-voice", default="af_bella")
    ap.add_argument("--max-speed", type=float, default=1.45, help="fastest speech stretch")
    ap.add_argument("--target-speed", type=float, default=None, help="aim every line at this stretch for an even pace")
    ap.add_argument("--rest-beats", type=int, default=4, help="beats of rest between stanzas")
    ap.add_argument("--flow", type=float, default=None, help="staccato mode: split lines into short phrases and snap each to the 8th-note grid at this stretch (e.g. 1.2)")
    ap.add_argument("--slot-beats", type=int, default=None, help="every spoken line gets exactly this many beats (rap grid); warns when a line's stretch leaves 1.0-1.6")
    ap.add_argument("--lufs", type=float, default=-17.0, help="mix loudness target (the reference library sits near -9.5; -17 was the original)")
    ap.add_argument("--sub", type=float, default=0.0, help="dB boost of the beat's sub-bass (about 50 Hz) before mixing; the reference library has ~10 dB more than our beats")
    ap.add_argument("--stress-align", action="store_true", help="with --slot-beats: warp each line so its stressed words land on the beats and the rhyme word on the last beat")
    ap.add_argument("--presence", type=float, default=0.0, help="dB boost of the voice around 3.5 kHz (consonant clarity); the reference library has ~3 dB more 2-6 kHz energy than our mixes")
    ap.add_argument("--beat-gain", type=float, default=0.0, help="dB added to the beat before mixing (real hip hop: the voice sits a median 3.7 dB under the backing while it sounds; reference-targets-instruments.json)")
    ap.add_argument("--duck", type=float, default=6.0, help="ratio of the beat's ducking under the voice (6 = the original heavy duck; 1 = none)")
    ap.add_argument("--stems", action="store_true", help="also write NAME.voice.wav and NAME.beat.wav as they enter the mix (before the master chain), for measuring without separation")
    ap.add_argument("--body-cut", type=float, default=0.0, help="dB cut of the voice under about 250 Hz (low shelf; 0 = none). Our voice reads about 10 dB fuller at 100-300 Hz against 300-1000 Hz than real hip hop vocal stems (tone.py, 2026-11-14)")
    ap.add_argument("--hook-lift", type=float, default=0.0, help="dB added to the beat while a repeated line (a line whose text occurs more than once) is sung, with 0.3 s ramps (0 = none). Real hip hop: backing level at repeated lines against other lines, median +0.1 to +1.3 dB by stem; ours read -1 to -2 (2026-11-14)")
    ap.add_argument("--voice-comp", type=float, default=0.0, help="ratio of a compressor on the voice before the mix (0 = none; 4 brings the run lengths between quiet spots into the real hip hop range, where the dry voice dips 10 dB inside every line; breath.py)")
    ap.add_argument("--legato", action="store_true", help="longer runs: commas inside a line are not sent to the speech server (no pause there), and a line that ends with a comma fills its whole slot so it runs into the next line (real hip hop: 90th percentile run 1.6 to 5.8 s; breath.py)")
    ap.add_argument("--fade-out", type=float, default=0.0, help="seconds: fade the finished song out (the reference set's long fades run 6-8 bars)")
    ap.add_argument("--flatten", type=float, default=1.0, help="pitch-swing factor for plain voices (0.6 = 60%% of each line's pitch movement; needs venv-speaker/pyworld)")
    ap.add_argument("--tail-soften", type=float, default=0.0, help="ms: low-pass the last ms of every sung clip at 3 kHz with a crossfade, and fade the last 40 ms to silence, so a word's end does not carry a sibilant hiss (0 = off)")
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("--timeline", action="store_true", help="print who speaks when (start-end seconds, voice, pan, text)")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    global MAXF, TARGETF
    MAXF = a.max_speed
    TARGETF = a.target_speed
    global FLATTEN, TAIL_SOFTEN
    FLATTEN = a.flatten
    TAIL_SOFTEN = a.tail_soften
    tmp = tempfile.mkdtemp(prefix="song-")
    beat = 60.0 / a.bpm
    import heteronym_lint as _hl
    lyrics = _hl.inline_say(open(os.path.join(HERE, a.lyrics)).read())      # word{say}: one use of a word spoken another way

    key = model = None            # looked up lazily by speak()
    if not a.self_test:
        print("default voice:", a.voice, "| rhythm:", "off" if a.plain else f"{a.bpm:g} BPM")

    def line_audio(i, voice, text, k=0):
        p = os.path.join(tmp, f"l{i:03d}-{k}.wav")
        if a.self_test:
            ffmpeg("-f", "lavfi", "-i", f"sine=frequency={220 + 110 * k}:duration={1.2 + 0.15 * (len(text) % 9)},adelay={150 + 90 * k}|{150 + 90 * k}", "-ar", str(SR), p)
            return p, "tone"
        return p, speak(key, model, voice, a.voice, text, p)

    if a.plain:
        parts, n = [], 0
        for voices, items in stanzas(lyrics):
            p, v = line_audio(n, split_voice(voices[0])[0] if voices else None, " ".join(t for _, t in items))
            parts.append(p); n += 1
            print(f"  stanza {n} spoken" + (f" by {v}" if voices else ""))
        lst = os.path.join(tmp, "list.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        voice_wav = os.path.join(tmp, "voice.wav")
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-ar", str(SR), "-ac", "1", voice_wav)
    else:
        placed, cursor, i = [], 4 * beat, 0            # one bar of beat alone first; entries: (start, audio, pan, gain)
        last_start, last_beats = 4 * beat, 4
        slot_auto = False
        last_end = 0.0
        PANS = {1: [0.0], 2: [-0.25, 0.25], 3: [-0.4, 0.0, 0.4], 4: [-0.5, -0.17, 0.17, 0.5], 5: [-0.55, -0.28, 0.0, 0.28, 0.55]}
        for voices, items in stanzas(lyrics):
            vs = (voices or [a.voice])[:5]
            for adlib, text in items:
                if adlib and re.fullmatch(r"slot\s+(\d+|auto)", text.lower()):   # "(slot 2)": from here on every spoken line gets this many beats (pace change by section)
                    slot_auto = text.split()[1].lower() == "auto"              # "(slot auto)": by syllables, 5 or fewer -> 2 beats, 6-12 -> 4, 13+ -> 6 (line starts leave the 4-beat grid)
                    a.slot_beats = a.slot_beats if slot_auto else int(text.split()[1])
                    continue
                if adlib and re.match(r"break\b", text.lower()):       # "(break 2)": that many bars of beat alone (an instrumental break)
                    nb = re.findall(r"\d+", text)
                    cursor += (int(nb[0]) if nb else 1) * 4 * beat
                    continue
                if adlib and text.lower().startswith("sing "):      # "(sing MELODY VOICE: the words)": the line is sung, a note per syllable (melody.py; needs pyworld, run with venv-speaker)
                    import melody
                    head, _, sung_words = text[5:].partition(":")
                    mel, _, sv = head.strip().partition(" ")
                    notes, nbeats = melody.MELODIES[mel]
                    with tempfile.TemporaryDirectory() as sw:
                        vocal = melody.sing_line(sung_words.strip(), sv.strip() or a.voice, notes, nbeats, 60.0 / beat, sw, "world")
                    whole = int(np.ceil(sum(nbeats) - 1e-9))
                    placed.append((cursor, vocal.astype(np.float32), 0.0, 1.0, f"sung {mel}: {sung_words.strip()}"))
                    last_start, last_beats, last_end = cursor, whole, cursor + len(vocal) / SR
                    cursor += whole * beat
                    continue
                if adlib and text.lower().startswith("clip "):      # "(clip FILE: BEATS)": a ready-made sung phrase (acestep-work + yingsinger-work) placed on the beat; silence at both ends is trimmed, then BEATS beats pass
                    cpath, _, nb = text[5:].rpartition(":")
                    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", cpath.strip(), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
                    cl = np.frombuffer(raw, dtype=np.float32).copy()
                    env = np.convolve(np.abs(cl), np.ones(int(0.01 * SR)) / int(0.01 * SR), mode="same")
                    idx = np.where(env > env.max() * 0.05)[0]
                    cl = cl[max(0, idx[0] - int(0.03 * SR)): idx[-1] + int(0.1 * SR)]
                    whole = int(nb.strip())
                    placed.append((cursor, cl, 0.0, 1.0, f"clip {os.path.basename(cpath.strip())}"))
                    last_start, last_beats, last_end = cursor, whole, cursor + len(cl) / SR
                    cursor += whole * beat
                    continue
                if adlib and text.lower().startswith("sfx "):      # "(sfx phone)": the shared universe sound, placed on the beat, then a rest of whole beats
                    import universe_sfx
                    clip = universe_sfx.load(text.split(None, 1)[1].strip().lower())
                    placed.append((cursor, clip, 0.0, 0.9, f"sfx {text[4:].strip()}"))
                    cursor += max(2, int(np.ceil(len(clip) / SR / beat))) * beat
                    continue
                if adlib:                                  # "(text)" answers in a gap of its own; "(+text)" is laid over the end of the line before
                    overlay = text.startswith("+")
                    text = text.lstrip("+ ").strip()
                    name, robot = split_voice(a.adlib_voice)
                    raw, v = line_audio(i, name, text, 0)
                    clean_clip(raw, raw + ".c.wav", robot)
                    clip = read_wav(raw + ".c.wav")                # an interjection keeps its natural speed: no stretching to fill a slot
                    if overlay:
                        start = max(0.0, last_start + (last_beats - 2) * beat - onset_offset(clip))
                    else:
                        anchor = last_end if 0 < cursor - last_end < 1.5 * beat else cursor      # right after the line that just ended
                        start = max(0.0, anchor - 0.10 - onset_offset(clip))                   # overlaps the very end of the line it answers, as a natural interjection does
                        ad_end = start + len(clip) / SR
                        cursor = max(cursor, int(np.ceil((ad_end - 0.15) / beat - 1e-9)) * beat)     # the next line starts on the next beat, and may overlap the tail of the interjection by up to 0.15 s
                    placed.append((start, clip, -0.55, 0.85, f"ad-lib {a.adlib_voice}: {text}"))
                    i += 1
                    continue
                beats = a.slot_beats
                if slot_auto and beats:
                    from flow_align import syllables
                    n_syl = sum(syllables(w) for w in re.findall(r"[A-Za-z']+", text))
                    beats = 2 if n_syl <= 5 else 4 if n_syl <= 12 else 6
                if a.flow:
                    # phrase grid: each short phrase starts on an 8th note and is stretched only to the nearest 8th-note slot, so the consonants stay sharp
                    eighth = beat / 2
                    words = text.split()
                    BREAK_BEFORE = {"and", "but", "or", "so", "with", "while", "when", "because", "that", "where", "to", "in", "on", "for", "from", "through"}
                    clauses, cur = [], []
                    for w in words:                      # 1) split after punctuation
                        cur.append(w)
                        if w[-1] in ",;:—–.!?":
                            clauses.append(cur); cur = []
                    if cur:
                        clauses.append(cur)
                    phrases = []
                    for cl in clauses:                   # 2) a long clause is cut only before a conjunction/preposition near its middle
                        if len(cl) <= 6:
                            phrases.append(" ".join(cl)); continue
                        cands = [j for j in range(2, len(cl) - 2) if cl[j].lower().strip(",") in BREAK_BEFORE]
                        cut = min(cands, key=lambda j: abs(j - len(cl) / 2)) if cands else None
                        if cut is None:
                            phrases.append(" ".join(cl))
                        else:
                            phrases += [" ".join(cl[:cut]), " ".join(cl[cut:])]
                    slot = 0
                    for pi, ph in enumerate(phrases):
                        n_slots = None
                        for k, voice in enumerate(vs):
                            name, robot = split_voice(voice)
                            raw, v = line_audio(i, name, ph, k + 10 * pi)
                            clean_clip(raw, raw + ".c.wav", robot)
                            d = duration(raw + ".c.wav")
                            if n_slots is None:
                                n_slots = max(1, int(np.ceil(d / (eighth * a.flow * 0.97))))
                            factor = min(max(d / (n_slots * eighth * 0.92), 0.85), 1.9)
                            fitted = os.path.join(tmp, f"f{i:03d}-{pi}-{k}.wav")
                            ffmpeg("-i", raw + ".c.wav", "-filter:a", f"atempo={factor:.4f}", "-ar", str(SR), "-ac", "1", fitted)
                            clip = read_wav(fitted)
                            placed.append((cursor + slot * eighth - onset_offset(clip), clip, PANS[len(vs)][k], 1.0 / np.sqrt(len(vs)), f"{voice}: {ph}"))
                        slot += n_slots
                    beats = int(np.ceil(slot / 4.0)) * 2          # whole 2-beat units
                    last_start, last_beats = cursor, beats
                    LINELOG.append((round(cursor, 3), round(beats * beat, 3), text)); cursor += beats * beat
                    i += 1
                    continue
                for k, voice in enumerate(vs):
                    name, robot = split_voice(voice)
                    said = re.sub(r"\s*[,;:](?=\s+\S)", "", text) if a.legato else text      # legato: no pause at a comma inside the line
                    raw, v = line_audio(i, name, said, k)
                    fitted = os.path.join(tmp, f"f{i:03d}-{k}.wav")
                    clean_clip(raw, raw + ".c.wav", robot)
                    if a.stress_align and a.slot_beats:
                        import flow_align
                        info = flow_align.align(raw + ".c.wav", text, beat, a.slot_beats, tmp, fitted, cache_key=f"{i}-{k}")
                        FLOWSTATS.append(info)
                        beats = a.slot_beats
                    else:
                        beats = fit_to_beats(raw + ".c.wav", fitted, beat, force=beats, fill=0.995 if a.legato and text.rstrip().endswith(",") else 0.92)    # every layered voice gets the same slot
                    if a.slot_beats and k == 0 and not a.stress_align and not 1.0 <= LASTF <= 1.6:
                        print(f"  ! stretch {LASTF:.2f} ({'rushed' if LASTF > 1.6 else 'slow'}): {text[:60]}")
                    clip = read_wav(fitted)
                    placed.append((cursor - onset_offset(clip), clip, PANS[len(vs)][k], 1.0 / np.sqrt(len(vs)), f"{voice}: {text}"))
                    end_k = cursor - onset_offset(clip) + len(clip) / SR
                    last_end = max(last_end, end_k) if k else end_k
                last_start, last_beats = cursor, beats
                LINELOG.append((round(cursor, 3), round(beats * beat, 3), text)); cursor += beats * beat
                i += 1
            cursor += a.rest_beats * beat              # rest between stanzas
            print(f"  stanza done ({i} lines so far)" + (f", voices {'+'.join(vs)}" if voices else ""))
        total = int((cursor + 2 * beat) * SR)
        left = np.zeros(total, dtype=np.float32)
        right = np.zeros(total, dtype=np.float32)
        if a.timeline:
            for t, audio, pan, gain, label in sorted(placed, key=lambda x: x[0]):
                print(f"  {t:6.2f}-{t + len(audio) / SR:6.2f} s  pan {pan:+.2f}  {label[:70]}")
        for t, audio, pan, gain, label in placed:
            s0 = int(t * SR)
            seg = audio[: total - s0] * gain * np.sqrt(2)
            theta = (pan + 1) * np.pi / 4                  # constant-power pan
            left[s0:s0 + len(seg)] += seg * np.cos(theta)
            right[s0:s0 + len(seg)] += seg * np.sin(theta)
        voice_wav = os.path.join(tmp, "voice.wav" if not a.flow else "voice-raw.wav")
        with wave.open(voice_wav, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((np.clip(np.stack([left, right], axis=1), -1, 1) * 32767).astype("<i2").tobytes())

    if a.flow and not a.plain:     # vocal chain for clarity: presence lift, de-mud, consonant bite, compression
        chained = os.path.join(tmp, "voice.wav")
        ffmpeg("-i", voice_wav, "-af", "highpass=f=110,equalizer=f=250:t=q:w=1:g=-2.5,equalizer=f=3600:t=q:w=1.1:g=5,equalizer=f=7500:t=q:w=1:g=2.5,"
               "acompressor=threshold=0.08:ratio=4:attack=4:release=60:makeup=2.5,asoftclip=type=tanh:threshold=0.9", chained)
        voice_wav = chained
    name = os.path.splitext(a.lyrics)[0].replace("lyrics", "song") + ("-plain" if a.plain else "") + ".wav"
    out = os.path.join(HERE, "song-selftest.wav" if a.self_test else name)
    if LINELOG:
        import json
        json.dump(LINELOG, open(os.path.splitext(out)[0] + ".lines.json", "w"))
    # beat looped under the voice, ducked while the voice speaks, then limited
    lift = ""
    if a.hook_lift and LINELOG:
        import collections as _co, re as _re
        key = lambda t: _re.sub(r"[^a-z ]", "", t.lower()).strip(); cnt = _co.Counter(key(x[2]) for x in LINELOG); blocks = []
        for st, slot, text in LINELOG:
            if cnt[key(text)] > 1 and key(text):
                if blocks and st - blocks[-1][1] < 1.0: blocks[-1][1] = st + slot
                else: blocks.append([st, st + slot])
        if blocks:
            env = "+".join(f"clip((t-{x - .3:.2f})/.3,0,1)*clip(({y + .3:.2f}-t)/.3,0,1)" for x, y in blocks)
            lift = f",volume='1+{10 ** (a.hook_lift / 20) - 1:.4f}*min(1,{env})':eval=frame"
    pre = (f"[0:a]asplit=2[v0][sc];[v0]" + (f"equalizer=f=3500:t=q:w=1:g={a.presence},equalizer=f=250:t=q:w=1:g=-2" if a.presence else "anull")
           + (f",bass=g=-{a.body_cut}:f=250:t=s:w=0.7" if a.body_cut else "")
           + (f",acompressor=threshold=-32dB:ratio={a.voice_comp}:attack=3:release=60:makeup=4" if a.voice_comp else "")
           + f"[v];[1:a]volume={0.55 * 10 ** (a.beat_gain / 20):.4f}" + (f",equalizer=f=50:t=q:w=0.9:g={a.sub}" if a.sub else "") + lift + "[b];"
           + f"[b][sc]sidechaincompress=threshold=0.03:ratio={a.duck}:attack=15:release=250[bd];")
    if a.stems:
        ffmpeg("-i", voice_wav, "-stream_loop", "-1", "-i", os.path.join(HERE, a.beat), "-filter_complex", pre + "[bd]volume=0.9[bo]",
               "-map", "[v]", "-t", f"{duration(voice_wav):.3f}", os.path.splitext(out)[0] + ".voice.wav", "-map", "[bo]", "-t", f"{duration(voice_wav):.3f}", os.path.splitext(out)[0] + ".beat.wav")
    ffmpeg("-i", voice_wav, "-stream_loop", "-1", "-i", os.path.join(HERE, a.beat),
           "-filter_complex", pre +
           f"[v][bd]amix=inputs=2:duration=first:dropout_transition=0:weights='1.0 0.9',volume=1.9,"
           + ("loudnorm=I=-17:TP=-1.5:LRA=8,alimiter=limit=0.9" if a.lufs <= -16 else
              f"acompressor=threshold=0.15:ratio=3:attack=10:release=120:makeup=2,loudnorm=I={a.lufs}:TP=-1.0:LRA=5,alimiter=limit=0.95:level=false")
           + (f",areverse,afade=t=in:d={a.fade_out},areverse" if a.fade_out else ""), out)
    if FLOWSTATS:
        b = [m for st in FLOWSTATS for m in st["before_ms"][1:]]       # beat-0 anchors are exact by construction
        print(f"stress alignment: {len(FLOWSTATS)} lines, {sum(len(st['anchors']) for st in FLOWSTATS)} anchored words; "
              f"with plain stretching those words would sit a median {np.median(b):.0f} ms (mean {np.mean(b):.0f}) off their beat; now on the beat. "
              f"Estimated word times {'trusted' if all(st['trusted'] for st in FLOWSTATS) else 'estimated for some lines'}.")
    print("wrote", out, f"({duration(out):.0f} s)")
    if not a.no_play and not a.self_test:
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", out])


if __name__ == "__main__":
    main()
