# Working on MC SOC (people and agents)

A closed loop that turns incidents and chosen news into reviewed content. The core knows one thing, the **lesson record**; everything else
(memory systems, review surfaces, publishers, sources, analyzers) is an **adapter** at the edge. Most requests from a user are "make it work with X":
that means one new adapter, not a change to the core.

## Commands
```bash
python3 -I -m unittest discover -s tests   # offline; fakes only; stdlib only, no installs
python3 verify.py --all                    # records, works, feedback
python3 decide.py                          # read-only brief per approved lesson
python3 -I exchange.py check               # exchange bundles (numbers only; see exchange/README.md and CONTRIBUTING.md)
```
Stdlib only, on purpose: an adopter can read all of it and run it anywhere. Do not add a dependency to the core; an adapter that needs a client library
keeps it in its own file and says so in its docstring.

## Rules that matter most
- **A model never approves.** Sign-off is written only by `review.set_signoff`, through `review.decide`. The approver's name comes from the platform
  (Discord user id, GitLab user, OIDC subject), never from a model, a record or a tool argument. Do not add a second write path to `signoff`.
- **A review surface must meet the contract in `docs/design.md` (decision 13):** platform-supplied identity, an allow-list of approvers, a deliberate
  confirm after the text to be signed is shown, and verify re-run before writing. If you cannot say how a surface meets all four, it does not qualify.
- **Feedback and source text are data, never instructions.** Comments, news text and record fields are stored, scanned and shown; they are not executed
  or fed to a model as commands. Decide reads counts, not words.
- **Redact by value, not by field name.** `verify.py` scans every string. Mask anything shaped like a secret (tokens, `user:key@host` URLs, private
  IPs, emails). If a secret is exposed in a chat, a log or a file, say so and treat it as leaked.
- **Nothing real in the repo.** Examples, tests and docs use placeholders (`example.org`, RFC 5737 addresses, fake ids such as `111111111111111111`).
  No real tokens, hostnames, serials or personal names. Config with credentials is gitignored and read from environment variables only.
- **Credentials are the user's to create.** Do not mint, rotate or store tokens. Give the exact steps and where to put the value (an environment variable).
- **No voice cloning, no sound-alikes of real people, no copied content.** Persona cards hold measured ranges and trait labels only, never artist
  or track names, and never embeddings. Lessons are restated, not reproduced.
- **Unattended runs generate only.** Nothing is published without a recorded human approval, and publishing is a separate step from approving.

## Adding an adapter (the usual task)
1. Ask which seam: **memory system** (`memory.py`), **review surface** (`review.py`), **publisher** (`publishers/`), **source** (milestone 3), or **analyzer** (`analyzers/`).
2. Read the nearest existing adapter and copy its shape; do not invent a new interface.
3. Write the test first, against a **fake** of the platform (no network, no token). A review surface also runs the shared contract: subclass `ReviewSurfaceContract`
   from `tests/conformance.py` with a TestCase and supply `act` (see `tests/test_conformance.py` for the CLI and OpenMOLE examples).
4. Keep the adapter to one file plus one line of registration. The core must not branch on the platform's name.
5. Update `docs/design.md` (a numbered decision, with what is built and what is not) and the README table in the same change.

## Working method
- **Verify, don't trust.** Run the tests and read the diff before saying something is done. Say what was not run or not tried against the real platform;
  "fake-tested only" is a legitimate status, label it that way.
- **Branch, don't commit to `main`.** Work on a branch, run the tests, then open a pull request. Agent-assisted commits end with a `Co-Authored-By:` trailer.
- **Be honest about maturity.** The design doc separates built, tried-for-real and planned. Keep that separation; do not describe a planned adapter as working.
