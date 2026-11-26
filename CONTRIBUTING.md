# Contributing

Thanks for helping. This project turns incidents and chosen news into reviewed content. The core is small on purpose: one record, a verify stage, and adapters at the edges. Most contributions are one new adapter or one exchange bundle.

## Ways to contribute
- **An adapter.** A memory system, a review surface, a publisher, a source, an analyzer, or a tag sink. Read the nearest existing one, copy its shape, and write the test first against a fake of the platform (no network, no token). See `AGENTS.md` ("Adding an adapter").
- **An exchange bundle.** A crate (two to eight sides and the measured relationship between them), a persona card or a trial prescription: numbers only. `crate_builder.py` computes a crate from a feature table. See `exchange/README.md`.
- **A fix or an improvement** to the docs, the checks or the tests.

## Before you open a pull request
```bash
python3 -I -m unittest discover -s tests     # offline; fakes only; no installs
python3 -I verify.py --all                   # records, works and feedback
python3 -I exchange.py check                 # exchange bundles
```
The core is standard library only. An adapter that needs a client library keeps it in its own file and says so in its docstring.

## Rules that every contribution follows
- **A model never approves.** Sign-off is written only through `review.decide`. A new review surface must pass the shared contract in `tests/conformance.py`.
- **Numbers only about other people's work.** No transcripts, lyrics, audio or per-track rows. An analyzer that hears words proves it with `tests/textfree.py`.
- **Nothing real in the repository.** Examples and tests use placeholders. No real tokens, hostnames, serials or personal names. Credentials come from the environment, never from files in the repo.
- **Redact by value.** Mask anything shaped like a secret, whatever its field is called.
- **No voice cloning or sound-alikes of real people, and no copied content.** Lessons are restated, not reproduced.
- **Say how much was tried.** "Fake-tested only" is a fine status. Do not describe a planned adapter as working.

## Review
A maintainer reviews every pull request, and exchange bundles get an extra look for names. Pipelines may not be running on a given install, so please run the checks above yourself and say so in the description. Agent-assisted commits end with a `Co-Authored-By:` trailer naming the agent.
