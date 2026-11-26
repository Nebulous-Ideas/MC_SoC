# Drafts

Work that is not yet signed off lives here, outside `records/` and `works/`, so `verify.py --all` and CI only see approved material and
material in the review queue. Nothing in `drafts/` can be published. To release a draft:

1. A person checks the facts (the lesson says what needs a practitioner's check) and the text.
2. Move the record to `records/`, check redaction, set `redaction.status` to `passed`, then approve it:
   `python3 review.py approve <lesson-id> --as "Your Name"`.
3. Move the work to `works/`, check redaction, set it to `passed`, and approve it with `--works`.
4. Open a pull request. Only then can anything (the static site, or the rap voice's `SONG:` signal) use it.
