# Retry Amplification

Paper, analysis code, and data for *Retry Amplification: When Resilience Policies
Trigger Cascading Failures* — a study of how retry policies compound across
microservice tiers, submitted to ICE2CPT 2026.

Rishabh Mehan · Jasmit Kaur Saluja

## What's here

```
paper/         Submission (.tex + .pdf), bibliography, cover letter
analysis/      Static-analysis and simulation code
results/       Collected data, simulation output, manual validation records
blog/          Long-form write-up of the same material
```

## Which results the paper uses

This matters, because there is more than one run in `results/`:

| Path | Contents | Used in paper? |
|---|---|---|
| `results/simulation/n100-reported/` | 100 trials per configuration | **Yes** — Tables V and VI |
| `results/simulation/n10-pilot/` | 10-trial pilot, different values | No |
| `results/repositories/analysis_200_clean.json` | Cleaned configuration set (113) | **Yes** — Table II |
| `results/repositories/analysis_200.json` | Raw detections (162), pre-cleaning | Superseded |
| `results/repositories/analysis_50_pilot.json` | 50-repo pilot | No |
| `results/repositories/proof-of-concept/` | Early 9-repo methodology check | No |

## Reproducing

```bash
python -m venv venv && source venv/bin/activate
pip install -r analysis/requirements.txt
```

Simulation (writes to `results/simulation/latest/`):

```bash
python analysis/experiments/run_simulation.py
```

Repository analysis. Collection needs a GitHub token with `public_repo` scope:

```bash
export GITHUB_TOKEN=...
python analysis/experiments/collect_repositories.py
python analysis/experiments/analyze_collected_repos.py --max-repos 200
```

Cleaning and correction — this is the step that produces the numbers in the
paper, and it documents three defects found in the original detection pass:

```bash
python analysis/experiments/reanalyze_clean.py
```

Detection validation — draws a seeded sample for manual review, then scores it:

```bash
python analysis/experiments/validate_detection.py generate
# hand-check each item, replacing "verdict: ?" with y or n
python analysis/experiments/validate_detection.py score
```

Manuscript audit — recomputes every figure the paper reports from the files in
`results/` and asserts the manuscript contains that value. Run it before
submitting and after any change to the analysis; it exits non-zero on a
mismatch, and also fails if the built PDF is older than the `.tex`:

```bash
python analysis/experiments/verify_paper_claims.py
```

## Known limitations

Recorded here because they bound what the data supports, and are stated in the
paper as well:

- **The analyzed sample is entirely Python.** The 200 repositories are the first
  200 entries in collection order, and the collector enumerates languages in
  sequence, so all 200 are Python — as are all 23 in which retry logic was found.
  The 1,000-repository candidate pool is Go-dominated (47.6% Go, 31.2% Python,
  21.2% Java); those Go and Java repositories are collected but unanalyzed.
- **Jitter detection was originally wrong.** The first pass credited jitter when
  `jitter` *or* `random` appeared near a configuration. Of its 8 positives, only
  3 distinct constructs actually randomize a delay. `reanalyze_clean.py` uses the
  manually verified set; see `results/validation/ai_prescreen.md`.
- **25.3% of raw detections were non-production code** — 41 of 162, from
  `examples/`, `docs/`, integration-test roots, `playground/` and `benchmarks/`
  — and are excluded from the cleaned set, leaving 121. Collapsing near-duplicate
  detections then leaves the 113 configurations the paper reports.
- **Detections are concentrated.** One project supplies 23 of 113 configurations
  and the top three supply 44%, so configuration-level percentages are
  descriptive rather than a random sample of production code.
- **No false-negative rate is reported.** Establishing that retry logic is absent
  from a repository requires reading it in full, which was not done.

## Building the paper

```bash
cd paper
pdflatex retry-amplification-ice2cpt && bibtex retry-amplification-ice2cpt \
  && pdflatex retry-amplification-ice2cpt && pdflatex retry-amplification-ice2cpt
```

Six pages, matching the ICE2CPT limit.

## License

MIT for the code. The manuscript and blog post are © the authors.
