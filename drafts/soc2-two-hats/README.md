# soc2-two-hats (draft, not signed off)

A spoken-rhyme song on how security engineers and CPAs mean different things in a SOC 2 effort (build and run the controls, versus
independently attest to them). Files: `history-soc2-two-hats.json` (the lesson, pending), `song-soc2-two-hats.json` (the work, draft; its
`content` is the sheet), `lyrics-soc2-two-hats.txt` (the same sheet, for rendering).

**Checked so far, still needs a person before sign-off:** the AICPA pages support the framing (CPAs provide SOC reports; five criteria categories), and the AICPA plain-English independence guide supports that a CPA firm may not assume management responsibilities or run an attest client's operations. The Type 1 / Type 2 and management-assertion points rest on a CPA firm's public explainer, not on the standard itself (AT-C 205), which was not read. A practitioner should check those, and that "designing what they will test" is stated fairly (auditors may give some advice and assessments within the independence rules; the lyric says only that designing it creates a self-review problem).

Render a draft (needs your own speech server and a beat):

```bash
cd compose && SPEECH_URL=... SPEECH_KEY=... python3 sing.py --lyrics ../drafts/soc2-two-hats/lyrics-soc2-two-hats.txt --beat beat.wav --bpm 98 --voice af_heart --no-play
```
Local test render: 124 s, three voices (stock voices only), no LONG lines, heteronym lint clean. Not listened to by a person yet.

QA pass (`compose/qa_render.py`, numbers and flags only, not a verdict) on draft 2, rendered with `--beat-gain 7 --hook-lift 5 --tail-soften 80`: 22 flags, down from 26 on the first render. First-render problems were fixed by rewording that line only: dropped lead words ("Same words, but" in the hook, "Blend", "Do", "Writing"), and a beat 6 to 17 dB under the voice (now about -5 to +8 dB, the reference sits near +3.7). Still flagged for a listen: the number words in "type one" and "type two" (the recognizer drops them), "skipped", a few sibilant line ends (-s, -ed) in the hooks and verse 3, and a beat stem with about 1,100 full-scale samples before the master chain.
