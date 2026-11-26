# Crate maker: build a crate from a library you already have

A crate is two or more sides of a library and the measured relationship between them (decisions 16 and 17). This folder
is the path for building one from your own library. The example in `example/` is fake data and runs end to end.

## What stays local, what can be shared

| Local only (never commit) | Shared through the exchange |
|---|---|
| your library listing (artists, titles, tags) | the crate bundle: counts, hashes, profiles and effect sizes |
| `sample.json`, `assign.json`, your feature tables | nothing else. No ids, names or per-track rows |
| your audio and any stems | nothing |

The bundle checker (`exchange.py check`) refuses anything that isn't a number, an enum or a short hash.

## The steps

1. **Declare the rules before you look at any audio.** Write `rules.json`: a seed, a duration window, a per-artist cap,
   the minimum number of artists per side, and the sides. The sides are defined by tags you already have (genre, a label,
   a mood tag). Do not define a side by a measure you will then compare: that is circular, and the crate will separate on
   it by construction.
2. **Sample.** `python3 -I crate_maker/sample.py LIBRARY.tsv RULES.json --out DIR` applies the rules in a fixed order (eligibility,
   a seeded shuffle of a sorted pool, the per-artist cap) and writes `sample.json` and `assign.json`. It refuses a side with
   fewer than `min_artists` artists. It prints counts only.
3. **Measure the sample.** This happens on the measuring side, with your analyzers, on the audio of the selected tracks only.
   The row id must be the analyzer's row id; the flow analyzer uses `features.opaque(artist, title)`, which is what
   `assign.json` uses. Record the analyzer, its version and its calibration in the table's provenance.
4. **Build the table** with `features.py build`, which validates it.
5. **Build the crate:**
   ```bash
   python3 -I crate_builder.py build TABLE.json --assign DIR/assign.json --purpose delivery-reference \
       --kind contrast --membership chosen --confidence low --out DIR/crates
   ```
6. **Check the bundle** before anything goes anywhere: `python3 -I exchange.py check DIR`. Copy only the bundle into the
   exchange (`exchange/crates/`) and open a pull request.

## What the example shows

Run it:

```bash
python3 -I crate_maker/sample.py crate_maker/example/library.tsv crate_maker/example/rules.json --out /tmp/crate-example
python3 -I crate_builder.py build crate_maker/example/features.json --assign /tmp/crate-example/assign.json \
    --purpose delivery-reference --kind contrast --membership chosen --confidence low --out /tmp/crate-example/crates
```

- Three artists per side, three tracks each: 9 and 9 tracks. One track is outside the duration window, one is excluded by tag,
  and the cap takes three of each artist's four.
- The sides separate completely (separability 1.0), and the crate has **no carrier**. That is correct, not a bug: with three
  artists per side, the smallest two-sided p-value is above the 5% bar after the correction, so nothing can be supported.
  A supported crate needs about four artists per side. Plan the library for that before sampling.
- The feature numbers in `example/features.json` are invented to match the tags. They are for the demonstration only.

## Limits to write down with every crate

- Sides are defined by tags, so the result is a relationship to those tags, not a fact about the music.
- Tracks by one artist are not independent: the group effect (per artist) is the one that counts for evidence.
- A small crate is a hypothesis and an observation, not a proof. Its evidence tier says which.
