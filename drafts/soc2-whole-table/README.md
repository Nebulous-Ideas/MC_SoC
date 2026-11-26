# soc2-whole-table (draft, not signed off)

Companion to `../soc2-two-hats/`: who else has to play along for a SOC 2 report to mean something. Six seats: leaders (the claim and the funding),
the people team (hiring, training, removing access), vendors (carve-out, read their report), customers (their own controls), and the engineer and
auditor from the first song. About 90 seconds, three stock voices.

**Checked so far, needs a person before sign-off:** the vendor carve-out versus inclusive method and customer controls points rest on two
secondary explainers; the people and vendor criteria rest on a third-party-hosted copy of the 2017 Trust Services Criteria; "leaders write the claim"
matches management's assertion (see the first song's sources). Legal and insurers are not in the song because no source was checked for them; they
are a reasonable next verse. A practitioner should check the wording.

QA pass (`compose/qa_render.py`), rendered with `--beat-gain 7 --hook-lift 5 --tail-soften 80`: 15 flags after rewording lines whose first word the
recognizer dropped; the ones left are "work" heard as "worked" in the hook and "six" in the outro, plus beat-level and line-end notes. Not listened to by a
person.

Same release steps as `../README.md`. The `SONG:` signal can sing it by id once approved and moved to `works/`.
