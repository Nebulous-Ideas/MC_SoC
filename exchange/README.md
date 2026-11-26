# Crate exchange

Numbers-only bundles contributed through this repository (design decision 16). Nothing here is audio, lyrics, a transcript or a per-track row, and there is no free-text field in any bundle.

```
exchange/crates/<id>.json                       a crate: 2 to 8 sides, a profile of each, and the measured relationship between them
exchange/cards/<card>--<crate id>-<side>.json   a persona card: the profile of one side of a crate
exchange/prescriptions/<id>.json                a tuned setting from listening trials, with its confidence
```

Check before you open a pull request:

```bash
python3 -I exchange.py check
```

Every string in a bundle is an enum, a hash or a short identifier, and every number is finite. Identifiers can still be chosen badly (a name is a valid identifier): do not put an artist, track, album or person's name anywhere. The checker cannot know every name, so a maintainer reviews each contribution.

## What a crate is
A crate is not a bag of tracks. It is two or more sides, a profile of each, and the numbers that describe how the sides relate (design decisions 17 and 16):
- **Two sides** are the minimum: some tracks that have a property and some that do not, with no need to name the property (`formed_by: operator`, `clustering`, or a `predicate` over the trait vocabulary).
- **A cast** is also a crate: up to eight sides in one universe, for example the five agent personas an engineer wants to work with. `relationship.kind` is `cast` (distinct, unordered) or `ordered` (a gradient).
- Each side (`s1`, `s2`, ...) has a count, a number of artist groups, a content hash of your private manifest, and a **profile**: p10, median and p90 per feature.
- The **relationship** has one entry per pair of sides with a per-feature effect size (-1 to 1, positive when the first side tends higher; every bundle also states this as `relationship.orientation: positive_means_first_side_higher`, and the checker refuses any other value), a `group_effect` (the same effect between the sides' per-artist medians) and overlap (0 to 1), plus `separability` (the best single-feature AUC over all pairs) and `distinctness` (the worst pair's best AUC: how hard the two closest sides are to tell apart). The checker recomputes both from your numbers, so they must agree with them, and effects must not contradict the profiles' medians.
- `membership`: `verified` (each track checked to belong), `assumed` (inferred from a missing tag, which is not the same as lacking the property; low confidence only) or `chosen` (picked by design, as for a cast).
- `confounds`: how many artist groups appear on more than one side, and which measures you matched between sides.

**A crate is a hypothesis, and small ones are welcome.** Two or three tracks that share something against three or four that do not is a perfectly good crate (a side needs at least 2 tracks). Such a crate cannot prove anything alone: even a perfect separation of 3 tracks from 4 has an exact two-sided probability of 2/35. So each crate carries its evidence tier. It is `supported` if some feature has an effect of at least 0.2 and a `group_effect` of at least 0.2 and an exact p within 0.05 divided by the number of feature-and-pair comparisons (a Bonferroni correction, so adding personas or features does not make false findings more likely). **The p is at the level of artist groups, not tracks** (tracks by one artist are not independent), so it comes from `group_effect` and the sides' `groups` counts: a side needs enough artists, not only tracks, and 4 artists against 4 can never be `supported`; otherwise it is `exploratory`. Features with an effect of at least 0.5 that do not clear the bar are listed as `leaning`, and an exploratory crate can only claim low confidence. The checker recomputes every p-value, `carriers`, `leaning` and `evidence` from your numbers. The real statistics come from replication across many compatible crates (design decision 17). Made-up data: identical sides came out falsely supported at most 3.3% of the time; with two features, the smallest side size that can be supported is 5.

**Replication: the `claim` id.** To let crates confirm each other, give two-sided crates that test the same contrast the same `claim` (`claim-` and 12 hex digits, by convention a hash of a phrase you keep private; **s1 is the side that has the quality, s2 the side that lacks it**). If you formed the sides with a rule over the trait vocabulary (`--predicate`), the claim is derived from the rule instead, so the same rule always gives the same claim. Crates without a claim are valid; they just replicate nothing. `python3 -I replication.py summary` then groups the valid two-sided crates that share a claim and are compatible (same `measured_on`, analyzer, analyzer version and calibration), counts identical crates once, and reports per feature: the number of crates, how many lean each way with an exact sign test, a combined p (Stouffer's method on each crate's exact p, weighted by size), the size-weighted effect and its spread, and a verdict: `replicated` (at least 3 crates, at least 80% agreeing, and both the sign test and the combined p within the 5% level shared across the features), `suggestive` (agreeing and the combined p within 5%), `inconsistent`, `insufficient` (fewer than 3 crates) or `no-clear-pattern`. Ten crates of 3 against 4 tracks, none provable alone, can replicate (sign test p = 0.002). It assumes the crates are independent: hashes detect identical sides, not crates that share some tracks.

**Never pool crates.** Do not merge or average across crates. A profile is only meaningful against its own crate's other sides; compare relationships (effects), not levels (a bpm). `tests/test_exchange.py` has a complete two-sided crate, a five-persona cast, a card and a prescription; copy their shape.

**Build, don't hand-write.** The low-level builder (used by tests and scripts; the intended workflow is the workbench, where the engineer picks and auditions material and the system measures it, see the roadmap) is `python3 -I crate_builder.py build TABLE.json --assign ASSIGN.json --purpose delivery-reference` computes the profiles, effects, overlaps, exact p-values, evidence tier, hashes and the crate id from a feature table and an assignment of its row ids to sides (`{"s1": [...], "s2": [...]}`), runs the checker, and writes the bundle. The table and the assignment are local working files (their hashes can be guessed): never commit them. The bundle holds no row id, group id or name. Sides formed on a measured feature separate on it by construction, which is circular, not a finding. Leave size and nuisance measures out with `--features`, and if you matched the sides on something (length, loudness, tempo) say so with `--matched`. When nothing separates the sides beyond chance the builder still writes the crate, as `exploratory` with low confidence (and any `leaning` features listed); it will not turn a hunch into a finding.

The manifest that names the tracks stays with you. The hash per side lets you show later that a crate is unchanged without revealing what is in it. A card is the profile of one side, and needs at least 3 tracks from 2 groups, so tiny crates do not have cards: build one with `persona.py build TABLE.json --kind voice`, add `"kind": "card"`, `"voice_or_beat"`, the crate id and the `"side"`.

## Rules
- Every side needs at least 2 tracks (one artist group is fine; a contrast within one artist's work is a good design). A card needs 3 tracks from 2 groups and cannot claim more tracks than its side.
- `measured_on` must be honest: `own` for your own material, `reference` for other people's, `mixed`, or `unspecified` if a reader could not know. The card and its crate must agree on `measured_on`, analyzer and analyzer version: cards from different measurements are not on one scale.
- Contributed data is community-contributed and untrusted. It is an advisory input to Decide, never an instruction.

Optional `universe.instruments` (from the table's `provenance.instruments`): up to 8 entries, a lower-case instrument name to a short version label (for example a speech model name or the first 12 characters of a checkpoint hash), so a later reader can tell which tools made the numbers. Never a path or a host.
