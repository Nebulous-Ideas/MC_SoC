# Analysis outputs, as examples

Numbers and labels only. Each file is what one step of the analysis process produced, so a reader can see the
shape of the output without the audio. Nothing here carries an artist, track or person's name.

| File | Step | What it shows |
|---|---|---|
| `feature-table-summary.json` | Measure: `features.py build flow-tsv` on the reference delivery table | 50 rows in 8 artist groups, 18 features, with p10/median/p90 for each, and the provenance block: no calibration yet (`calibration.status: none`), `measured_on: unspecified`. |
| `cards/*.json` | Persona cards: `persona.py` on the same table | Two voice cards after the fix (`rapid-melodic`, `slow-melodic`); `slow-deadpan` no longer meets its threshold without our tracks with their traits, measured ranges and the form each one maps to. Built from the reference rows only (our own tracks are left out). |
| `act-comparison-egress-r2.json` | Act: a render measured against the `rapid-melodic` card | Target bands, measured values, and inside / above / below for each measure. The render is the approved work's sheet (`lyrics-act-egress-r2.txt`). |
| `../crate-example.json` | Crate: `crate_builder.py` on the same table | Two sides, a per-feature relationship, and the evidence tier (exploratory: no carrier). A plumbing example, not a finding. |

## Open items these outputs show

- **Our own tracks are now left out** of the reference table and the persona builder (`OWN_ARTIST` in `analyzers/flow_tsv.py` and `persona.py`), with tests. The summary and cards here were rebuilt after the fix: 41 reference rows in 7 groups. Before the fix there were three cards; the `slow-deadpan` card was built partly from our own tracks and falls out, which is the intended effect of the rule.
- **No calibration yet** on the delivery table (`calibration.status: none`). The rhyme analyzer has a calibration on seven of our own tracks; the delivery table does not.
- **Two cards differ in size** from the ones in `personas/` (`voice` cards there count voices, these count tracks). The `personas/` cards are the tracked versions.
