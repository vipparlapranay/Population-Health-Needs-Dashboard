-- Highest age-standardised PPH rates
SELECT
    phn_name,
    age_standardised_pph_rate_per_100k,
    rate_vs_national_pct,
    population_weighted_irsd_score,
    disadvantage_rank
FROM phn_summary
ORDER BY age_standardised_pph_rate_per_100k DESC
LIMIT 5;

-- PHN-level SEIFA aggregation coverage
SELECT
    phn_code,
    phn_name,
    seifa_sa2_count,
    mapped_sa2_count,
    seifa_population_coverage_pct
FROM phn_summary
ORDER BY seifa_population_coverage_pct ASC;

-- SA2 inputs contributing to one PHN estimate
SELECT
    sa2_code,
    sa2_name,
    allocation_ratio,
    irsd_score,
    usual_resident_population,
    allocated_population
FROM sa2_phn_seifa
WHERE phn_code = 'PHN701'
ORDER BY allocated_population DESC;
