# Atom analysis for rap and singing: a focused literature pass (2026-11-12)

Question: has the idea of fitting time-frequency atoms by gradient descent, with split and prune steps (a splatting-style loop), or its modern descendants, been applied to the analysis of rapped and sung vocals, and what should we borrow? Method: six web searches, snippets and abstracts read, no paper read in full. Treat as a map of where to look, not a finished review. Anything not found may exist under other terms.

## 1. Direct prior art: thin
- **AudioGS** ([arXiv 2604.08967](https://arxiv.org/abs/2604.08967)) is the nearest splatting-for-audio work, but it models spatial sound fields: one Gaussian per spectrogram bin carrying directional coefficients. It does not fit free-position atoms to a signal and is not about voices.
- Nothing found that fits 2D Gaussians or chirplets to a spectrogram with a differentiable rasteriser and densify/prune, for voice or rap analysis. Implicit-representation work ([Neural Amplitude Fields](https://arxiv.org/html/2601.06406), [Siamese SIREN](https://arxiv.org/pdf/2306.12957)) targets compression and is not a decomposition we can read parameters from. The 3D-splatting compression literature ([EAGLES](https://arxiv.org/pdf/2312.04564)) has pruning and codebook ideas that could be borrowed, nothing audio-specific.
- Reading: the combination is probably open, which is both the opportunity and the risk.

## 2. The known obstacle: frequency gradients
- **"Multi-Scale Spectral Loss Revisited"** (Schwär and Müller, IEEE SPL 2023, [PDF](https://www.audiolabs-erlangen.de/content/05_fau/professor/00_mueller/03_publications/2023_SchwaerM_MultiScaleSpecLoss_IEEE-SPL.pdf)): with parameters that control sinusoid frequency, the multi-scale spectral loss often gives uninformative gradients; window and hop configuration matters; spectral leakage explains part of it.
- **DDSP review** (Hayes et al., [arXiv 2308.15422](https://arxiv.org/pdf/2308.15422)): sinusoidal oscillators are non-convex under plain gradient descent on an audio loss; remedies include a sinusoidal consistency loss (permutation-invariant, inspired by two-way mismatch) and adding an f0 loss; in one singing case the audio loss alone could not learn reconstruction while also learning f0.
- **GOLF** ([arXiv 2306.17252](https://arxiv.org/pdf/2306.17252), ISMIR 2023): multi-resolution STFT loss plus an f0 loss plus a voiced/unvoiced term; and it demonstrates analysis by optimisation (Adam, lr 0.001, 1000 steps against the target) for singing.
- **Consequence for our design:** do not trust a pure STFT loss to find frequencies. Initialise from peak-picking and a pitch track, keep an f0 or consistency term, and choose window sizes deliberately.

## 3. The classical lineage: this is matching pursuit with gradient refinement
- Matching pursuit with a Gabor dictionary ([Mallat and Zhang](https://www.researchgate.net/profile/Stephane-Mallat/publication/234136428_Matching_pursuit_with_time-frequency_dictionary/links/56bb56fc08ae2d6f2013a9b8/Matching-pursuit-with-time-frequency-dictionary.pdf)) already gives an adaptive time-frequency picture, shows pitch pulses in speech, and is the ancestor of the "peak-pick, subtract, repeat" step.
- **Chirplets** add a chirp rate, which is exactly the parameter that captures pitch glides and vibrato. Matching pursuit over a chirplet dictionary ([multicomponent chirp estimation](https://www.researchgate.net/publication/224244610_Parameter_Estimation_of_Multicomponent_Chirp_Signals_via_Sparse_Representation), [adaptive chirplet transform](https://arxiv.org/pdf/1709.08328)) gives more compact and precise representations than Gabor-then-refine, which is less robust to strong noise. A [fast multi-Gabor pursuit](https://arxiv.org/pdf/2202.12380) addresses cost.
- Missing: no singing-voice vibrato or glide paper turned up directly; ridge pursuit and Gaussian-chirp pursuit are the terms to search next.
- **Reading:** the modern version is a hybrid: pursuit or peak-picking for initialisation, gradient descent to refine, split/prune to control the atom budget. Use chirplets, not plain Gabor atoms.

## 4. Swing and microtiming: use the robust published methods on top
- Autocorrelation of the onset-energy function ([Marchand and Peeters, DAFx-15](https://www.ntnu.edu/documents/1001201110/1266017954/DAFx-15_submission_59.pdf)) reached 91% mean recall on swing detection and estimation; a log-lag autocorrelation representation is preferred to picking individual onsets, which is sensitive to onset errors at fast tempi ([Dittmar et al., ISMIR 2015](https://audiolabs-erlangen.de/content/05_fau/professor/00_mueller/03_publications/2015_DittmarPM_SwingRatio_ISMIR.pdf); [swingogram](https://www.tandfonline.com/doi/full/10.1080/09298215.2017.1367405)).
- Joint beat and microtiming tracking ([Fuentes et al., ISMIR 2019](https://archives.ismir.net/ismir2019/paper/000029.pdf)) normalises microtiming by the beat interval.
- **Hip hop swing is a sixteenth-note, low-magnitude effect.** [Frane (2017)](https://shamslab.psych.ucla.edu/wp-content/uploads/sites/57/2017/01/Frane_SwingInBreakbeats_2017.pdf) on 30 classic breakbeats: median swing ratio about 1.2:1, so jazz-style eighth-note triplet assumptions do not fit.
- **Reading:** an atom fit is a good source of a clean onset-energy envelope; then apply the published autocorrelation methods to it, so our swing numbers are comparable with the literature.

## 5. Rap flow from audio: annotated data exists, a dedicated detector does not
- Ohriner, *Flow* ([Duke](https://read.dukeupress.edu/journal-of-music-theory/article/66/2/303/318019/Flow-The-Rhythmic-Voice-in-Rap-Music)): about 200 verses; the author's repository (mohriner/flowBook) is said to hold isolated vocals, timings, segmentations and annotations, with R code. A candidate ground truth for syllable onsets. **Check its licence and what audio it actually contains before using anything.**
- **"The Vocal Eras Tour"** ([TISMIR](https://transactions.ismir.net/articles/10.5334/tismir.278)): vocal microtiming over 88,357 songs (1965-2010) using onset, meter and beat tracking and the carat Microtiming Toolbox; onset detection was evaluated on 90 hand-annotated 10-second vocal stems, with the annotations published (elenatheodora/MSD_Annotated_Onsets); rap showed a significantly higher vocal onset-to-beat ratio than other genres. Gives both a baseline pipeline and a published number to compare with.
- [Gilbers et al. (2020)](https://journals.sagepub.com/doi/10.1177/0023830919881479) measure rhythm and microtiming of rap on a MIDI grid so songs at different tempi compare; a Canterbury thesis uses the pairwise variability index ([PVI](https://ir.canterbury.ac.nz/server/api/core/bitstreams/97c78a65-ff98-4de8-ac27-9407328da68a/content)) for rap rhythm.
- No dedicated automatic rap syllable-onset detector found; existing work is mostly manual annotation or general onset detectors. An atom-based syllable-onset estimator evaluated on those annotations would fill a visible gap.

## What this changes in the plan
1. **Baseline first.** Build the carat-style and autocorrelation baselines on our own ground-truth clips (known tempo and swing from the beat maker, known notes from the melody scores). If atoms do not beat the baselines on onsets and swing, do not build the engine.
2. **Hybrid, chirplet atoms, f0 term.** Peak-pick and pitch-track initialisation; gradient refinement; a consistency or f0 loss; deliberately chosen STFT sizes; atom budget with split and prune.
3. **Atoms as a mid-level representation.** Derive the onset-energy envelope, glide and vibrato statistics, tonal versus transient share, and reconstruction quality; then apply published methods (autocorrelation swing, PVI, onset-to-beat ratio) so numbers are comparable.
4. **Evaluate on public annotations** (licences unchecked) as well as our own material.
5. **Guardrail unchanged:** atoms are a compressed copy of the audio, stay ephemeral on the measuring side, and only aggregates cross the boundary.

## Not covered
Perceptual-loss choices; 2D-Gaussian fitting on spectrograms under other names (try "Gaussian atoms", "parametric spectrogram fitting", "1D Gaussian splatting audio"); source-separation interplay; licences of the datasets named above.
