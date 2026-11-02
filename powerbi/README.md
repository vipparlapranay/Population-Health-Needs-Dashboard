# Power BI hand-off

The reproducible model writes `data/processed/phn_summary.csv` and
`data/processed/sa2_phn_seifa.csv`. Import both from **Get data → Text/CSV**.
The PHN summary is the report's one-row-per-PHN fact table; the SA2 table is
the drill-through detail. `data/processed/health_needs.sqlite` is also available
for direct SQL import.

## Suggested report page

1. **Cards:** PHN count, Australian PPH rate, highest-rate PHN and the Pearson
   correlation between PPH rate and weighted IRSD score.
2. **Bar chart:** PHN name by age-standardised PPH rate, descending; add the
   national rate as a constant line.
3. **Scatter chart:** weighted IRSD score (X) against PPH rate (Y), with PHN
   name as the tooltip and allocated population as bubble size.
4. **Detail table:** PPH rank, PHN, rate, difference from national, weighted
   IRSD score, disadvantage rank and SEIFA population coverage.
5. **Drill-through:** SA2 name, SA2 code, allocation ratio, IRSD score,
   population and allocated population.

## Measures

```DAX
PHN Count = DISTINCTCOUNT(phn_summary[phn_code])

Australia PPH Rate =
MAX(phn_summary[national_pph_rate_per_100k])

PPH Rate Difference =
AVERAGE(phn_summary[age_standardised_pph_rate_per_100k])
    - [Australia PPH Rate]

PPH Rate Difference (%) =
DIVIDE([PPH Rate Difference], [Australia PPH Rate])
```

## Data caveats

- Lower IRSD scores mean greater relative disadvantage.
- The PHN-level score is a population-weighted average of SA2 scores, not an
  ABS-published PHN IRSD value.
- The PPH period is 2023–24 and the SEIFA reference year is 2021. These
  ecological data describe association only; they do not establish causality
  or measure the quality of an individual service.
- Respect the source attribution and definitions in the project README.
