# Population Health Needs Dashboard

An evidence-led comparison of potentially preventable hospitalisations (PPH)
and area-level socioeconomic disadvantage across Australia's 31 Primary Health
Networks (PHNs). The pipeline joins AIHW 2023–24 PHN rates to ABS 2021 SA2
IRSD scores using the Department of Health's PHN 2023–SA2 2021 concordance.

## Verified snapshot

The figures below were calculated from the linked source files using the
reproducible pipeline in this repository:

- **31 PHNs** analysed.
- **Australia:** 2,617 age-standardised PPH hospitalisations per 100,000 people
  in 2023–24.
- **SEIFA population coverage:** 99.90%–100.00% across the 31 PHNs.
- **Highest-rate PHNs:** Northern Territory (5,913), Western Queensland
  (5,380), Darling Downs and West Moreton (3,582), Central Queensland, Wide
  Bay and Sunshine Coast (3,550), and Northern Queensland (3,474) per 100,000.
- **Exploratory association:** Pearson `r = -0.58` between the PHN PPH rate and
  the population-weighted SA2 IRSD score. Lower IRSD scores represent greater
  disadvantage, so the negative direction indicates higher rates tend to
  coincide with greater area-level disadvantage.

These are descriptive ecological results, not causal findings. PPH is an
indicator of potentially avoidable hospitalisations, not a direct measure of
primary-care quality. The 2021 SEIFA baseline and 2023–24 hospitalisation
periods are also different reference years.

## Dashboard

The repository includes a runnable Streamlit dashboard and Power BI-ready CSV
exports with a report design hand-off. Power BI Desktop was not available in
the build environment, so this repository does not claim to include a native
`.pbix` report.

## Run locally

Requires Python 3.10 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m health_needs.pipeline
streamlit run dashboard\app.py
```

The first pipeline run downloads the official source files into
`data/raw/` (ignored by Git), then writes:

- `data/processed/phn_summary.csv` — one row per PHN, ready for Power BI.
- `data/processed/sa2_phn_seifa.csv` — SA2-level inputs and allocation weights.
- `data/processed/metrics.json` — headline metrics and top-five ranking.
- `data/processed/health_needs.sqlite` — `phn_summary`, `sa2_phn_seifa` and
  `source_metadata` tables for SQL and dashboard use.

To run tests:

```powershell
python -m pytest
```

## Data and method

1. Stream the AIHW CSV inside its ZIP and retain the 2023–24, PHN, all-person,
   total-PPH, age-standardised rate rows. The Australian national rate is read
   from the same AIHW table.
2. Read each SA2's IRSD score and usual-resident population from ABS SEIFA
   2021, Table 1.
3. Join SA2 codes to the official PHN concordance. For an SA2 allocated across
   PHNs, multiply its population by `RATIO_FROM_TO`. The published ratios are
   preserved rather than renormalised; some single-PHN mappings leave a small
   unallocated residual.
4. Calculate each PHN's population-weighted mean SA2 IRSD score. This is a
   project-derived summary, **not an official PHN SEIFA score**. The output
   includes SA2 counts and population coverage so the aggregation can be
   audited.
5. Rank PHNs by the published AIHW rate and calculate a descriptive Pearson
   correlation across PHNs.

The reported SEIFA population coverage is the share of concordance-allocated
population with both an ABS population value and an IRSD score; SA2 areas with
no usual-resident population do not contribute to the weighted score.

## Official sources

- AIHW, [Potentially preventable hospitalisations by small geographic areas,
  2017–18 to 2023–24](https://www.aihw.gov.au/reports/primary-health-care/potentially-preventable-hospitalisations-2017-18-to-2023-24)
  and [machine-readable data ZIP](https://www.aihw.gov.au/getmedia/653b7f52-75bb-4fb6-81ca-7b809e67bc95/AIHW-HPF-76_potentially-preventable-hospitalisations-by-small-geographic-areas-2017-18-to-2023-24-csv.zip).
- ABS, [Socio-Economic Indexes for Areas (SEIFA), 2021](https://www.abs.gov.au/statistics/people/people-and-communities/socio-economic-indexes-areas-seifa-australia/2021), SA2 Table 1.
- Australian Department of Health, [PHN 2023 to SA2 2021 concordance](https://www.health.gov.au/sites/default/files/2024-03/primary-health-networks-phn-2023-statistical-area-level-2-2021.xlsx).

Use the dashboard with `streamlit run dashboard\app.py`. Power BI import,
visual and measure guidance is in [`powerbi/README.md`](powerbi/README.md).
