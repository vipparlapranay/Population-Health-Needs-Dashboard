import csv
import io
import zipfile

import pandas as pd
import pytest

from health_needs.pipeline import (
    AIHW_COLUMNS,
    AIHW_MEASURE,
    aggregate_seifa,
    build_phn_summary,
    load_pph_rates,
)


def test_load_pph_rates_deduplicates_identical_national_rows(tmp_path):
    source_rows = []
    for geographic_unit, code, name, rate in [
        ("PHN", "PHN101", "North", "3000"),
        ("NAT", "001NAT", "National", "1000"),
        ("NAT", "001NAT", "National", "1000"),
    ]:
        source_rows.append(
            {
                "Year": "2023-24",
                "GeographicUnit": geographic_unit,
                "GeographicCode": code,
                "GeographicAreaName": name,
                "DemographicGroup": "All persons",
                "PPHGroup": "Total PPH",
                "PPHCondition": "Total PPH",
                "MeasureName": AIHW_MEASURE,
                "MeasureValue": rate,
                "Flag": "",
            }
        )

    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=AIHW_COLUMNS)
    writer.writeheader()
    writer.writerows(source_rows)
    source_path = tmp_path / "aihw.zip"
    with zipfile.ZipFile(source_path, "w") as archive:
        archive.writestr("data.csv", text.getvalue())

    rates, national_rate = load_pph_rates(source_path)

    assert rates["phn_code"].tolist() == ["PHN101"]
    assert rates["age_standardised_pph_rate_per_100k"].tolist() == [3000]
    assert national_rate == 1000


def test_aggregate_seifa_applies_concordance_and_population_weights():
    concordance = pd.DataFrame(
        [
            ["101000001", "Area 1", "PHN101", "North", 0.25, "Good"],
            ["101000001", "Area 1", "PHN102", "South", 0.75, "Good"],
            ["101000002", "Area 2", "PHN101", "North", 1.0, "Good"],
            ["101000003", "Area 3", "PHN101", "North", 1.0, "Good"],
        ],
        columns=[
            "sa2_code",
            "sa2_name",
            "phn_code",
            "phn_name",
            "allocation_ratio",
            "concordance_quality",
        ],
    )
    seifa = pd.DataFrame(
        [
            ["101000001", 1000.0, 100.0],
            ["101000002", 900.0, 300.0],
            ["101000003", None, 100.0],
        ],
        columns=["sa2_code", "irsd_score", "usual_resident_population"],
    )

    summary, detail = aggregate_seifa(concordance, seifa)

    north = summary.set_index("phn_code").loc["PHN101"]
    south = summary.set_index("phn_code").loc["PHN102"]
    assert north["population_weighted_irsd_score"] == pytest.approx(
        (1000 * 25 + 900 * 300) / 325
    )
    assert north["allocated_population"] == pytest.approx(425)
    assert north["scored_population"] == pytest.approx(325)
    assert north["seifa_population_coverage_pct"] == pytest.approx(325 / 425 * 100)
    assert south["population_weighted_irsd_score"] == pytest.approx(1000)
    assert len(detail) == 3


def test_build_phn_summary_ranks_rates_and_disadvantage():
    pph = pd.DataFrame(
        [
            ["PHN101", "North", 3000.0, ""],
            ["PHN102", "South", 2000.0, ""],
        ],
        columns=[
            "phn_code",
            "phn_name",
            "age_standardised_pph_rate_per_100k",
            "aihw_flag",
        ],
    )
    seifa = pd.DataFrame(
        [
            ["PHN101", "North", 900.0, 100, 100, 2],
            ["PHN102", "South", 1100.0, 100, 100, 2],
        ],
        columns=[
            "phn_code",
            "phn_name",
            "population_weighted_irsd_score",
            "allocated_population",
            "scored_population",
            "seifa_sa2_count",
        ],
    )

    summary = build_phn_summary(pph, 2500.0, seifa)
    assert summary["phn_code"].tolist() == ["PHN101", "PHN102"]
    assert summary["pph_rank"].tolist() == [1, 2]
    assert summary["disadvantage_rank"].tolist() == [1, 2]
    assert summary["rate_vs_national_pct"].tolist() == pytest.approx([20, -20])
