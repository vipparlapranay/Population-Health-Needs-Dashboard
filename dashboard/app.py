from pathlib import Path
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "health_needs.sqlite"

st.set_page_config(
    page_title="Population Health Needs | Australian PHNs",
    page_icon="📊",
    layout="wide",
)

st.title("Population Health Needs across Australian PHNs")
st.caption(
    "Potentially preventable hospitalisations (PPH) and area-level disadvantage. "
    "2023–24 AIHW rates linked to 2021 ABS SEIFA using the official PHN-SA2 concordance."
)

if not DATABASE_PATH.is_file():
    st.error(
        "Dashboard data is missing. From the project root, run "
        "`python -m health_needs.pipeline` after installing the project dependencies."
    )
    st.stop()

with sqlite3.connect(DATABASE_PATH) as connection:
    phn = pd.read_sql_query("SELECT * FROM phn_summary ORDER BY pph_rank", connection)
    metadata = pd.read_sql_query("SELECT * FROM source_metadata", connection)

if phn.empty:
    st.error("The PHN summary table is empty. Rebuild the dataset before continuing.")
    st.stop()

national_rate = float(phn["national_pph_rate_per_100k"].iloc[0])
top = phn.iloc[0]
correlation = phn[
    ["age_standardised_pph_rate_per_100k", "population_weighted_irsd_score"]
].corr(method="pearson").iloc[0, 1]

metric_columns = st.columns(4)
metric_columns[0].metric("PHN areas", f"{phn['phn_code'].nunique():,}")
metric_columns[1].metric("Australia PPH rate", f"{national_rate:,.0f} / 100k")
metric_columns[2].metric(
    "Highest-rate PHN",
    str(top["phn_name"]),
    f"{top['age_standardised_pph_rate_per_100k']:,.0f} / 100k",
)
metric_columns[3].metric("PPH / IRSD Pearson r", f"{correlation:.2f}")

st.info(
    "IRSD is an area-level index: lower scores indicate greater relative disadvantage. "
    "The PHN score is a population-weighted mean of SA2 scores, not an ABS-published "
    "PHN index. The correlation is descriptive and is not evidence of causation."
)

left, right = st.columns(2)
with left:
    st.subheader("PPH rates by PHN")
    display_count = st.slider(
        "Number of PHNs to display", min_value=5, max_value=len(phn), value=15
    )
    bar_data = phn.nsmallest(display_count, "pph_rank").sort_values(
        "age_standardised_pph_rate_per_100k"
    )
    chart = px.bar(
        bar_data,
        x="age_standardised_pph_rate_per_100k",
        y="phn_name",
        orientation="h",
        color="rate_vs_national_pct",
        color_continuous_scale="YlOrRd",
        labels={
            "age_standardised_pph_rate_per_100k": "Age-standardised PPH / 100,000",
            "phn_name": "PHN",
            "rate_vs_national_pct": "Above national (%)",
        },
        hover_data=["population_weighted_irsd_score", "seifa_sa2_count"],
    )
    chart.add_vline(x=national_rate, line_dash="dash", line_color="#263238")
    st.plotly_chart(chart, use_container_width=True)

with right:
    st.subheader("PPH and area-level disadvantage")
    scatter = px.scatter(
        phn,
        x="population_weighted_irsd_score",
        y="age_standardised_pph_rate_per_100k",
        color="rate_vs_national_pct",
        size="allocated_population",
        hover_name="phn_name",
        color_continuous_scale="YlOrRd",
        labels={
            "population_weighted_irsd_score": "Population-weighted SA2 IRSD score",
            "age_standardised_pph_rate_per_100k": "Age-standardised PPH / 100,000",
            "rate_vs_national_pct": "Above national (%)",
            "allocated_population": "Allocated SA2 population",
        },
    )
    scatter.add_hline(y=national_rate, line_dash="dash", line_color="#263238")
    st.plotly_chart(scatter, use_container_width=True)

st.subheader("PHN comparison table")
st.dataframe(
    phn[
        [
            "pph_rank",
            "phn_name",
            "age_standardised_pph_rate_per_100k",
            "rate_vs_national_pct",
            "population_weighted_irsd_score",
            "disadvantage_rank",
            "seifa_sa2_count",
            "seifa_population_coverage_pct",
        ]
    ],
    hide_index=True,
    use_container_width=True,
    column_config={
        "pph_rank": st.column_config.NumberColumn("PPH rank"),
        "age_standardised_pph_rate_per_100k": st.column_config.NumberColumn(
            "PPH per 100k", format="%.0f"
        ),
        "rate_vs_national_pct": st.column_config.NumberColumn(
            "Vs Australia (%)", format="%+.1f"
        ),
        "population_weighted_irsd_score": st.column_config.NumberColumn(
            "Weighted IRSD score", format="%.1f"
        ),
        "disadvantage_rank": st.column_config.NumberColumn("Disadvantage rank"),
        "seifa_population_coverage_pct": st.column_config.NumberColumn(
            "SEIFA population coverage (%)", format="%.1f"
        ),
    },
)

with st.expander("Sources and definitions"):
    st.dataframe(metadata, hide_index=True, use_container_width=True)
    st.markdown(
        """
        - **PPH:** AIHW's published age-standardised rate for all persons and total PPH.
        - **IRSD:** 2021 SA2 scores weighted by usual-resident population and the official
          SA2-to-PHN allocation ratio.
        - **Coverage:** share of concordance-allocated population with a usable ABS SA2
          score and population value.
        - **Interpretation:** PPH is a system-level indicator and is not a direct measure
          of service quality. Differences may reflect health needs and other factors.
        """
    )
