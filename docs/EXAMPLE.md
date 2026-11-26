# Worked example: one lesson, one song, one page

This walks one incident through the whole loop, as it ran on 2026-11-15 and 2026-11-16. Hosts, addresses and tokens are
left out; `<outline>` stands for the wiki's address. The example page is [example/index.html](example/index.html).

## The stages, in order (decision 22)

1. **Idea selection.** A person picks an approved lesson and checks it fits the universe built so far. No redaction check here.
2. **Production.** The redaction check is a production step, done before any lyrics, script or audio are made from the record.
   A person checks the text, then sets `redaction.status` to `passed` with a note on what was checked.
3. **Sign-off and publication.** Approval is a separate human step, through the review tool, and it is confirmed in a dialog.
   Publishing comes last and goes through the gate, which lists anything it refuses.

## What the example used

| Step | Where it lives | Result |
|---|---|---|
| Lesson | `records/incident-squid-acl-shared-egress-denial.json`, mirrored in Outline's lesson-records collection | approved; redaction passed for the JSON text |
| Derived work | `works/song-egress-shared-path.json`, mirrored in Outline's derived-works collection | approved; redaction passed; both checked by a person |
| Lyric sheet | `song/lyrics-act-egress-r2.txt` (words as approved; three lines split at existing commas; slots 4 for verse 2 and the outro) | 0 LONG lines |
| Beat | `song/beat-act-egress-r1.wav`, boombap, 98 BPM, 40 bars | +5.75 dB beat gain (template value, not tuned) |
| Render | `song/song-act-egress-r2.wav` (87 s), with stems and a timing file | heard syllables 5.09/s (inside); pitch span 17.0 st (inside); pitch spread 3.44 st (above the card by 0.67) |
| Review copy | MP3 attached to the work's Outline document | listened to by the owner; not yet by a second person |
| Page | `docs/example/index.html`, built by `publish.py static-site --works outline` | nine lessons, then the approved work as text |

## A crate, as a plumbing example (not a finding)

`docs/example/crate-example.json` is a crate built from the reference feature table with `crate_builder.py`. Side s1 is the
two reference artists the owner's role list calls core; side s2 is the other reference artists, without our own tracks.
Membership is chosen, confidence is low, and the checker accepts it. It has no carrier, so its evidence tier is
exploratory: the two sides do not separate on any feature with the required group evidence. It shows the bundle format and
the checker working end to end. It does not show a real difference in delivery, and it should not drive a choice of form
or card until a split with a hypothesis, and enough artists per side, is built.

## Commands

```bash
python3 -I verify.py --all                          # schema, redaction scan, evidence, sign-off rules
python3 lint_lyrics.py lyrics-act-egress-r2.txt     # writing-stage check; LONG lines must be fixed or justified
python3 review.py --works show song-egress-shared-path
python3 publish.py static-site --works outline --out public   # needs OUTLINE_URL and OUTLINE_API_TOKEN in the environment
```

## What went wrong, and what changed because of it

- **The first render talked over itself at about 56 s.** The timing file showed no overlap, but six lines were 1.22 s long
  with 11 to 17 syllables, so the speech was squeezed. The linter had flagged them and nothing stopped the render. The
  adapter now refuses a sheet with LONG lines unless a reason is given (PRE-SHIP-CHECKLIST 14a).
- **Approval came before redaction was recorded.** The record was approved, then verify refused it. Decision 22 puts
  redaction in production, and the works path refuses approval while redaction is pending.
- **The review tool could not see works.** Works now have their own store, in Outline, with the same sign-off routine
  as records (decision 23).
- **The host ran old code.** Its checkout was behind `main`, and the container reads the code from the host. Pull, then restart.

## Still open

- The Handover album sheet has eight LONG lines and is already released; that needs an owner decision.
- A second person should listen to the render before anything is treated as checked.
- The site can't hold audio yet. The review copy lives on the work's Outline page.
- Works are on `works-publisher`, not merged to `main`.
