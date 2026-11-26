## What this changes

## Kind
- [ ] adapter (memory, review surface, publisher, source, analyzer, tag sink)
- [ ] exchange bundle (crate, card, prescription)
- [ ] fix or docs

## Checks (run by hand; say if you could not)
- [ ] `python3 -I -m unittest discover -s tests`
- [ ] `python3 -I verify.py --all`
- [ ] `python3 -I exchange.py check`

## Rules
- [ ] numbers only about other people's work (no transcripts, lyrics, audio, per-track rows, names)
- [ ] nothing real in the diff (tokens, hostnames, personal names); placeholders only
- [ ] a new review surface passes `tests/conformance.py`; a new audio analyzer passes `tests/textfree.py`
- [ ] docs updated in the same change (`docs/design.md`, README table); status stated honestly (built, fake-tested only, planned)
