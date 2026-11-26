# MC SOC

![A hand-sewn striped sock puppet raps into a spool-and-cork microphone under a desk lamp at night, with index cards, a stamp and a mug on the desk](docs/img/sock-puppet-banner.jpg)

Master of Ceremonies + SOC. A closed loop that turns two streams into content:

1. **Incidents** from our own systems (Graylog, Kuma, Sentry, Grafana, GitLab, Outline postmortems).
2. **News** the organisation chooses to read (the OpenClaw agent stories behind Larry are the existing example).

Both are normalised into a **lesson record**. The loop then senses, decides, acts (lyrics and the singing pipeline), verifies, and learns from the result.

Status: the loop runs end to end with a person in it. Built and tested offline: lesson records, verify, review and sign-off, derived works, the publish gate and a static-site publisher, the analysis side (feature tables, crates, persona cards, exchange bundles) and the Act seam. Generation exists: the composition tools in `compose/` turn a lyric sheet into a rendered track and measure it. They were used for real on the maintainer's setup; here they are fake-tested only and need your own speech server. Unattended runs only generate drafts, and nothing is published without a recorded human approval. `docs/pipeline.md` gives every stage's status (built, run, planned, manual).

The core is source-agnostic: sources and memory systems (Outline first) are adapters. Records live in the memory system and are cached in `records/` for the Python side.

```bash
python3 verify.py                    # check every record in records/
python3 verify.py --require-approved # publish gate: fails until signed off
```

## Guardrails (fixed, from the idea page)
- Measure, don't sample.
- No voice cloning and no sound-alikes of real people.
- No copied content: lessons are restated, never reproduced.
- Redact by value, not by field name.
- A human approves before anything is published.

## Worked example
One incident, one derived work, one page, end to end: [docs/EXAMPLE.md](docs/EXAMPLE.md), with the built page in [docs/example/](docs/example/index.html).

## Layout
- `docs/design.md` the loop, stage by stage
- `docs/art-prompts.md` prompts for the project art (the sock puppet rapper)
- `docs/pipeline.md` the three loops (lessons, analysis, composition) with each stage's tool and status
- `docs/signing-off-works.md` how a person signs off a derived work, with a practice work to try it on
- `docs/milestones.md` what to build first
- `schema/lesson-record.schema.json` the one record every stream becomes
- `records/` local cache of lesson records (canonical copy lives in the memory system)
- `verify.py` the verify stage and publish gate
- `memory.py`, `sync.py` memory adapters (files, Outline) and pull/push; token from env only
- `review.py` review surface: show, approve, reject (a named person must confirm)
- `openmole_tool.py` Open WebUI (OpenMOLE) Tools stub over the same code; untried
- `gate.py`, `publish.py`, `publishers/` the shared publish gate and publisher plug-ins (`static-site` first)
- `schema/derived-work.schema.json`, `schema/feedback.schema.json`, `feedback.py` reuse and feedback flows (derived works link back to approved lessons; feedback is data, summarised as counts)
- `ops_check.py`, `ops.example.json` read-only pre-run check (LLM, Outline, GitLab, disk, verify), config-driven
- `release.py`, `releases/` named, fixed sets of approved records (manifest with hashes); publishers can render a release
- `.github/workflows/ci.yml` one way to run the checks; not required (the same three commands run anywhere)
- `features.py`, `analyzers/` the feature-table contract (numbers only, opaque ids, no embeddings) and read-only analyzers for the existing TSVs (per track, and per voice inside a track)
- `persona.py`, `personas/` persona cards (voice and beat kinds) built from any feature table of tracks or of voices (traits only, no names)
- `discord_card.py` Discord review surface logic (card plus button handling); fake-tested, no transport yet
- `decide.py` Decide stage: read-only brief per approved lesson (candidate forms, fitting voice cards, unranked beat cards); a person chooses
- `compose/` the composition tools (lint, render, measure, QA, rhyme) and the Act engine adapter over them; not stdlib-only, see `compose/README.md`
- `act.py` Act seam: checks a person's pick against the brief, asks an engine adapter for numbers, reports inside/below/above the voice card's bands; generate-only, fake-tested
- `exchange.py`, `exchange/` numbers-only bundles contributed by pull request (crates of 2 to 8 sides, cards, prescriptions) and their checker; `crate_builder.py` computes a crate from a feature table; see `CONTRIBUTING.md`
- `tests/` offline tests (`python3 -I -m unittest discover -s tests`)

## Home and licence
Source: https://github.com/Nebulous-Ideas/MC_SoC. Contributions are by pull request; see `CONTRIBUTING.md`.
Licensed under the GNU Affero General Public License v3.0 (`LICENSE`). The art in `docs/img/` is generated, with the notes in `docs/img/README.md`.
