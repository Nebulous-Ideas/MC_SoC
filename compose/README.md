# compose/: the composition tools

The tools that turn a lyric sheet into a checked render. They were developed outside this repo; this is the code, cleaned
of local paths, addresses and keys. **No audio, models, reference tables or lyrics ship here.** They are the Act-side
counterpart of `act.py`: `act_engine_sing.py` is the engine adapter that calls `sing.py`.

Status: **fake-tested only** in this repo (`tests/test_compose.py` runs the offline tests: heteronym lint and the engine adapter
with a fake runner). `sing.py`, the heard-words count and the measurers were used for real on the maintainer's machine with a
real speech server; they have not been run against yours.

Unlike the core, these are **not stdlib-only**. The core never imports them.

| File | What it does | Needs |
|---|---|---|
| `heteronym_lint.py` | flags words the speech engine may read the wrong way (past-tense read, and others) | stdlib |
| `lint_lyrics.py` | lines too long for their slot (LONG), repetition, length, rhyme numbers when available | `numpy` (through `sing`); optional `cmudict` |
| `sing.py` | speaks a sheet line by line, fits each line to the beat, mixes | `numpy`, `ffmpeg`, a speech server (OpenAI-compatible, Kokoro voices); optional `scipy`, `pyworld` |
| `flow_align.py`, `words.py`, `stt.py`, `melody.py` | syllable counting, heard words, transcription, sung lines | as `sing.py` |
| `qa_render.py` | word mismatches, line-end hiss, backing against voice, clipping; flags only | `numpy`, `soundfile`, speech server |
| `measure_voice_act.py`, `flow_profile.py` | pace, spread and span of a voice stem | `numpy`, `scipy`, `pyworld`, `torch` + RMVPE weights for the neural pitch |
| `rhyme_profile.py`, `rhyme_entropy.py`, `rhyme_check.py` | rhyme density of a sheet against a reference table you build yourself | `cmudict`, speech server for heard words |
| `rap_voice.py` | an OpenAI-style speech endpoint that raps on a beat for the voice names you list and forwards everything else, so a bot can rap without changing its voice code | stdlib for the service; `sing.py`'s needs to render |
| `act_engine_sing.py` | the Act engine adapter over `sing.py`; refuses sheets the linter flags LONG unless a reason is logged | the above |

## Configuration (environment variables only)

| Variable | Meaning |
|---|---|
| `SPEECH_URL` | speech server address (default `http://localhost:8000`) |
| `SPEECH_KEY` | its API key. **You create and set this; nothing here reads it from anywhere else or prints it.** |
| `MCSOC_REFERENCE_DIR` | folder holding your own reference tables and the three `rhyme_*`/`flow_profile` modules' data (default `reference-stats`) |
| `MCSOC_MEASURER_PY` | a Python with the pitch tracker installed, for `act_engine_sing.py` (default: the current one) |
| `MCSOC_ARTIST_PREFIXES` | comma-separated multi-word folder prefixes for `flow_profile.py` keys |
| `FLOW_RMVPE_DIR` | folder holding the RMVPE module and weights |

## Rap voice for a bot (fake-tested only)
`rap_voice.py` sits between a bot and your speech server. Point the bot's speech base URL at it, and use a voice name from your config (for example `talkie-rap`) when you want a rap. The text is checked first (no sheet directives, length and syllable caps), fitted to your beat by `sing.py`, and returned as one clip. Any other voice, or a rap that fails a check or a render, is forwarded as plain speech.

```bash
cat > rap.json <<'J'
{"talkie-rap": {"voice": "bm_george:robot", "beat": "/path/to/beat.wav", "bpm": 98, "slot_beats": 4, "fallback_voice": "bm_george"}}
J
RAP_VOICE_CONFIG=rap.json SPEECH_URL=http://your-speech-server:8000 python3 rap_voice.py
```
The caller's API key travels in its own `Authorization` header; this service never stores it. It listens on `127.0.0.1:8010` unless you set `RAP_HOST` and `RAP_PORT`. Not tried against a real speech server or a real bot.

## Try it without a server

```bash
python3 -I -m unittest discover -s tests          # includes compose/ tests
python3 compose/heteronym_lint.py your-sheet.txt
cd compose
ffmpeg -f lavfi -i "sine=frequency=60:duration=30" -ar 44100 beat.wav   # any beat file; this one is only a test tone
python3 sing.py --self-test --lyrics lyrics-example.txt --bpm 98       # mixes test tones, no server call
python3 lint_lyrics.py lyrics-example.txt
```

## Rules these tools keep

- Voices are the engine's stock voices; the "robot" voice is an effect, not an impression. No voice cloning, no sound-alikes of real people.
- Measures are numbers; QA and rhyme tools print counts and flags, never a line, a word or a title from a reference.
- Reference tables are yours to build from material you may use; they are not committed.
- Stems and scratch audio stay out of git (`*.wav`, `*.mp3` are ignored).
