# soc2-two-hats (draft, not signed off)

A spoken-rhyme song on how security engineers and CPAs mean different things in a SOC 2 effort (build and run the controls, versus
independently attest to them). Files: `history-soc2-two-hats.json` (the lesson, pending), `song-soc2-two-hats.json` (the work, draft; its
`content` is the sheet), `lyrics-soc2-two-hats.txt` (the same sheet, for rendering).

**Needs a person before sign-off:** the lesson's claims about report types, management's assertion and auditor independence are general
professional practice written from memory, not quoted from a standard; the two linked AICPA pages support only the framing (CPAs provide SOC
reports; five criteria categories). Please have a practitioner check them.

Render a draft (needs your own speech server and a beat):

```bash
cd compose && SPEECH_URL=... SPEECH_KEY=... python3 sing.py --lyrics ../drafts/soc2-two-hats/lyrics-soc2-two-hats.txt --beat beat.wav --bpm 98 --voice af_heart --no-play
```
Local test render: 124 s, three voices (stock voices only), no LONG lines, heteronym lint clean. Not listened to by a person yet.
