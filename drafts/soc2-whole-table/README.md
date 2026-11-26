# soc2-whole-table (draft, not signed off)

Companion to `../soc2-two-hats/`: who else has to play along for a SOC 2 report to mean something. Six seats, after a first verse on scoping (the business decides what is in scope; security is always in, the other four categories are chosen): leaders (the claim and the funding),
the people team (hiring, training, removing access), vendors (carve-out, read their report), customers (their own controls), and the engineer and
auditor from the first song. About 100 seconds, three stock voices.

**Checked so far, needs a person before sign-off:** the vendor carve-out versus inclusive method and customer controls points rest on two
secondary explainers; the people and vendor criteria rest on a third-party-hosted copy of the 2017 Trust Services Criteria; "leaders write the claim"
matches management's assertion (see the first song's sources). Legal and insurers are not in the song because no source was checked for them; they
are a reasonable next verse. A practitioner should check the wording.

QA pass (`compose/qa_render.py`), rendered with `--beat-gain 7 --hook-lift 5 --tail-soften 80`: 18 flags. Four of them ("heard nothing" for the last hook) are an artifact of the QA's fixed 12-second windows: transcribing the same stem from 74 s hears the whole hook correctly. A real problem found this way was "work to share" heard as "worked a share"; it was reworded to "a share to bear". Not listened to by a person.

The scoping verse rests on a CPA firm's explainer (Schellman); the record lists it as a secondary source.

Same release steps as `../README.md`. The `SONG:` signal can sing it by id once approved and moved to `works/`.
