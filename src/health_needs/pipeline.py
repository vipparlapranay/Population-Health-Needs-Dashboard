from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

AIHW_URL = (
    "https://www.aihw.gov.au/getmedia/653b7f52-75bb-4fb6-81ca-7b809e67bc95/"
    "AIHW-HPF-76_potentially-preventable-hospitalisations-by-small-geographic-areas-"
    "2017-18-to-2023-24-csv.zip"
)
ABS_URL = (
    "https://www.abs.gov.au/statistics/people/people-and-communities/"
    "socio-economic-indexes-areas-seifa-australia/2021/"
    "Statistical%20Area%20Level%202%2C%20Indexes%2C%20SEIFA%202021.xlsx"
)
CONCORDANCE_URL = (
    "https://www.health.gov.au/sites/default/files/2024-03/"
    "primary-health-networks-phn-2023-statistical-area-level-2-2021.xlsx"
)

AIHW_COLUMNS = [
    "Year",
    "GeographicUnit",
    "GeographicCode",
    "GeographicAreaName",
    "DemographicGroup",
    "PPHGroup",
    "PPHCondition",
    "MeasureName",
    "MeasureValue",
    "Flag",
]
AIHW_MEASURE = "Hospitalisations per 100,000 people (age-standardised)"
AIHW_PERIOD_PREFIX = "2023"
CONCORDANCE_SHEET = "CG_SA2_2021_PHN_2017_All"
DATA_PERIOD = "2023-24"


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    try:
        with requests.get(
            url, headers=headers, stream=True, timeout=(30, 180)
        ) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
        temporary_path.replace(destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _ensure_sources(raw_dir: Path) -> dict[str, Path]:
    sources = {
        "aihw": (raw_dir / "aihw-pph-2017-18-to-2023-24.zip", AIHW_URL),
        "abs": (raw_dir / "abs-seifa-sa2-2021.xlsx", ABS_URL),
        "concordance": (raw_dir / "phn-2023-to-sa2-2021.xlsx", CONCORDANCE_URL),
    }
    for path, url in sources.values():
        if not path.is_file():
            _download(url, path)
    return {name: path for name, (path, _) in sources.items()}


def _normalize_sa2_codes(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.map(
        lambda value: f"{int(value):09d}" if pd.notna(value) else pd.NA
    ).astype("string")


def load_seifa(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name="Table 1", header=5, usecols=[0, 2, 10])
    if len(frame.columns) != 3:
        raise ValueError("ABS SEIFA Table 1 did not contain the expected code, score and population columns.")
    frame.columns = ["sa2_code", "irsd_score", "usual_resident_population"]
    frame["sa2_code"] = _normalize_sa2_codes(frame["sa2_code"])
    frame["irsd_score"] = pd.to_numeric(frame["irsd_score"], errors="coerce")
    frame["usual_resident_population"] = pd.to_numeric(
        frame["usual_resident_population"], errors="coerce"
    )
    frame = frame.dropna(subset=["sa2_code", "usual_resident_population"])
    frame = frame.loc[frame["usual_resident_population"] > 0].copy()
    if frame["sa2_code"].duplicated().any():
        duplicates = frame.loc[frame["sa2_code"].duplicated(), "sa2_code"].tolist()
        raise ValueError(f"ABS SEIFA data has duplicate SA2 codes: {duplicates[:5]}")
    return frame


def load_concordance(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(
        path,
        sheet_name=CONCORDANCE_SHEET,
        usecols=[0, 1, 2, 3, 4, 6],
    )
    frame.columns = [
        "sa2_code",
        "sa2_name",
        "phn_code",
        "phn_name",
        "allocation_ratio",
        "concordance_quality",
    ]
    frame["sa2_code"] = _normalize_sa2_codes(frame["sa2_code"])
    frame["allocation_ratio"] = pd.to_numeric(
        frame["allocation_ratio"], errors="coerce"
    )
    frame = frame.dropna(
        subset=["sa2_code", "phn_code", "phn_name", "allocation_ratio"]
    ).copy()
    if frame["allocation_ratio"].lt(0).any() or frame["allocation_ratio"].gt(1).any():
        raise ValueError("The PHN-SA2 concordance contains allocation ratios outside [0, 1].")
    if frame.duplicated(["sa2_code", "phn_code"]).any():
        raise ValueError("The PHN-SA2 concordance contains duplicate SA2-to-PHN mappings.")
    allocation_totals = frame.groupby("sa2_code")["allocation_ratio"].sum()
    overallocated = allocation_totals[allocation_totals > 1.001]
    if not overallocated.empty:
        raise ValueError(
            "The PHN-SA2 concordance allocates more than 100% of these SA2s: "
            f"{overallocated.index.tolist()[:5]}"
        )
    return frame


def load_pph_rates(path: Path) -> tuple[pd.DataFrame, float]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise ValueError(f"AIHW source is not a valid ZIP file: {path}") from error

    with archive:
        csv_files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(csv_files) != 1:
            raise ValueError(
                f"Expected one AIHW CSV in {path}, found {len(csv_files)}."
            )
        selected_chunks: list[pd.DataFrame] = []
        national_rates: list[float] = []
        with archive.open(csv_files[0]) as source:
            for chunk in pd.read_csv(
                source,
                encoding="cp1252",
                usecols=AIHW_COLUMNS,
                chunksize=100_000,
                dtype={"Year": "string", "GeographicCode": "string"},
            ):
                mask = (
                    chunk["Year"].str.startswith(AIHW_PERIOD_PREFIX, na=False)
                    & chunk["DemographicGroup"].eq("All persons")
                    & chunk["PPHGroup"].eq("Total PPH")
                    & chunk["PPHCondition"].eq("Total PPH")
                    & chunk["MeasureName"].eq(AIHW_MEASURE)
                )
                rows = chunk.loc[mask].copy()
                phn_mask = rows["GeographicUnit"].eq("PHN") & rows[
                    "GeographicCode"
                ].str.startswith("PHN", na=False)
                selected_chunks.append(rows.loc[phn_mask])
                national_mask = rows["GeographicUnit"].eq("NAT") & rows[
                    "GeographicCode"
                ].eq("001NAT")
                national_rates.extend(
                    pd.to_numeric(
                        rows.loc[national_mask, "MeasureValue"], errors="coerce"
                    )
                    .dropna()
                    .tolist()
                )

    if not selected_chunks:
        raise ValueError("No AIHW PHN rows matched the configured 2023-24 PPH measure.")
    pph = pd.concat(selected_chunks, ignore_index=True)
    pph["age_standardised_pph_rate_per_100k"] = pd.to_numeric(
        pph["MeasureValue"], errors="coerce"
    )
    if pph["age_standardised_pph_rate_per_100k"].isna().any():
        missing_codes = pph.loc[
            pph["age_standardised_pph_rate_per_100k"].isna(), "GeographicCode"
        ].tolist()
        raise ValueError(f"AIHW PPH rates are missing for PHN codes: {missing_codes}")
    if pph["GeographicCode"].duplicated().any():
        raise ValueError("AIHW contains duplicate rows for the selected PHN PPH measure.")
    unique_national_rates = sorted(set(national_rates))
    if len(unique_national_rates) != 1:
        raise ValueError(
            "Expected one unique Australian national PPH rate; "
            f"found {unique_national_rates}."
        )

    pph = pph.rename(
        columns={
            "GeographicCode": "phn_code",
            "GeographicAreaName": "phn_name",
            "Flag": "aihw_flag",
        }
    )
    return (
        pph[
            [
                "phn_code",
                "phn_name",
                "age_standardised_pph_rate_per_100k",
                "aihw_flag",
            ]
        ].copy(),
        unique_national_rates[0],
    )


def aggregate_seifa(
    concordance: pd.DataFrame, seifa: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mappings = concordance.merge(
        seifa, on="sa2_code", how="left", validate="many_to_one"
    )
    mappings["allocated_population"] = (
        mappings["usual_resident_population"] * mappings["allocation_ratio"]
    )
    mappings["scored_population"] = mappings["allocated_population"].where(
        mappings["irsd_score"].notna(), 0
    ).fillna(0)
    mappings["score_weighted_population"] = (
        mappings["irsd_score"] * mappings["allocated_population"]
    ).fillna(0)
    mappings["has_seifa_score"] = mappings["irsd_score"].notna()
    mappings["scored_sa2_code"] = mappings["sa2_code"].where(
        mappings["has_seifa_score"]
    )

    summary = (
        mappings.groupby(["phn_code", "phn_name"], as_index=False)
        .agg(
            allocated_population=("allocated_population", "sum"),
            scored_population=("scored_population", "sum"),
            weighted_score_total=("score_weighted_population", "sum"),
            seifa_sa2_count=("scored_sa2_code", "nunique"),
            mapped_sa2_count=("sa2_code", "nunique"),
        )
    )
    summary["population_weighted_irsd_score"] = (
        summary["weighted_score_total"] / summary["scored_population"]
    )
    if summary["allocated_population"].le(0).any():
        missing = summary.loc[
            summary["allocated_population"].le(0), "phn_code"
        ].tolist()
        raise ValueError(f"No usable ABS population values were available for PHNs: {missing}")
    summary["seifa_population_coverage_pct"] = (
        summary["scored_population"] / summary["allocated_population"] * 100
    )
    summary = summary.drop(columns=["weighted_score_total"])
    if summary["population_weighted_irsd_score"].isna().any():
        missing = summary.loc[
            summary["population_weighted_irsd_score"].isna(), "phn_code"
        ].tolist()
        raise ValueError(f"No usable ABS SEIFA scores were available for PHNs: {missing}")

    detail = mappings.loc[
        mappings["has_seifa_score"],
        [
            "phn_code",
            "phn_name",
            "sa2_code",
            "sa2_name",
            "allocation_ratio",
            "irsd_score",
            "usual_resident_population",
            "allocated_population",
            "concordance_quality",
        ],
    ].copy()
    return summary, detail


def build_phn_summary(
    pph: pd.DataFrame, national_rate: float, seifa_summary: pd.DataFrame
) -> pd.DataFrame:
    if national_rate <= 0:
        raise ValueError("The Australian national PPH rate must be greater than zero.")
    name_check = pph[["phn_code", "phn_name"]].merge(
        seifa_summary[["phn_code", "phn_name"]],
        on="phn_code",
        how="left",
        validate="one_to_one",
        suffixes=("_aihw", "_concordance"),
    )
    mismatched_names = name_check.loc[
        name_check["phn_name_concordance"].notna()
        & name_check["phn_name_aihw"].ne(name_check["phn_name_concordance"]),
        "phn_code",
    ].tolist()
    if mismatched_names:
        raise ValueError(
            f"AIHW and concordance PHN names do not match for: {mismatched_names}"
        )
    seifa_metrics = seifa_summary.drop(columns=["phn_name"], errors="ignore")
    summary = pph.merge(
        seifa_metrics,
        on="phn_code",
        how="left",
        validate="one_to_one",
        suffixes=("", "_seifa"),
    )
    if summary["population_weighted_irsd_score"].isna().any():
        missing = summary.loc[
            summary["population_weighted_irsd_score"].isna(), "phn_code"
        ].tolist()
        raise ValueError(f"ABS SEIFA summary is missing AIHW PHNs: {missing}")
    summary["national_pph_rate_per_100k"] = national_rate
    summary["rate_vs_national_pct"] = (
        summary["age_standardised_pph_rate_per_100k"] / national_rate - 1
    ) * 100
    summary["pph_rank"] = summary[
        "age_standardised_pph_rate_per_100k"
    ].rank(method="min", ascending=False).astype(int)
    summary["disadvantage_rank"] = summary[
        "population_weighted_irsd_score"
    ].rank(method="min", ascending=True).astype(int)
    return summary.sort_values("pph_rank").reset_index(drop=True)


def _build_metrics(summary: pd.DataFrame, national_rate: float) -> dict[str, Any]:
    top_phns = summary.nsmallest(5, "pph_rank")
    correlation = summary[
        [
            "age_standardised_pph_rate_per_100k",
            "population_weighted_irsd_score",
        ]
    ].corr(method="pearson").iloc[0, 1]
    return {
        "data_period": DATA_PERIOD,
        "phn_count": int(summary["phn_code"].nunique()),
        "seifa_population_coverage_pct_range": [
            float(summary["seifa_population_coverage_pct"].min()),
            float(summary["seifa_population_coverage_pct"].max()),
        ],
        "national_age_standardised_pph_rate_per_100k": float(national_rate),
        "top_five_phns_by_pph_rate": [
            {
                "phn_code": row.phn_code,
                "phn_name": row.phn_name,
                "rate_per_100k": float(row.age_standardised_pph_rate_per_100k),
                "population_weighted_irsd_score": float(
                    row.population_weighted_irsd_score
                ),
            }
            for row in top_phns.itertuples(index=False)
        ],
        "pearson_r_pph_rate_vs_irsd_score": float(correlation),
        "association_interpretation": (
            "A negative correlation means higher PPH rates tend to coincide with "
            "lower IRSD scores (greater area-level disadvantage); it is descriptive "
            "and does not establish causation."
        ),
    }


def _write_sqlite(
    database_path: Path,
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    retrieved_at: str,
) -> None:
    metadata = pd.DataFrame(
        [
            {
                "source": "AIHW Potentially Preventable Hospitalisations",
                "url": AIHW_URL,
                "reference_period": DATA_PERIOD,
                "retrieved_at_utc": retrieved_at,
            },
            {
                "source": "ABS SEIFA 2021, SA2 Table 1",
                "url": ABS_URL,
                "reference_period": "2021",
                "retrieved_at_utc": retrieved_at,
            },
            {
                "source": "Department of Health PHN 2023 to SA2 2021 concordance",
                "url": CONCORDANCE_URL,
                "reference_period": "PHN 2023 / SA2 2021",
                "retrieved_at_utc": retrieved_at,
            },
        ]
    )
    with sqlite3.connect(database_path) as connection:
        summary.to_sql("phn_summary", connection, if_exists="replace", index=False)
        detail.to_sql("sa2_phn_seifa", connection, if_exists="replace", index=False)
        metadata.to_sql("source_metadata", connection, if_exists="replace", index=False)


def build_dataset(raw_dir: Path, output_dir: Path) -> dict[str, Any]:
    sources = _ensure_sources(raw_dir)
    pph, national_rate = load_pph_rates(sources["aihw"])
    seifa = load_seifa(sources["abs"])
    concordance = load_concordance(sources["concordance"])
    seifa_summary, detail = aggregate_seifa(concordance, seifa)
    summary = build_phn_summary(pph, national_rate, seifa_summary)
    metrics = _build_metrics(summary, national_rate)

    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "phn_summary.csv", index=False, float_format="%.4f")
    detail.to_csv(output_dir / "sa2_phn_seifa.csv", index=False, float_format="%.4f")
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    retrieved_at = datetime.now(timezone.utc).isoformat()
    _write_sqlite(
        output_dir / "health_needs.sqlite", summary, detail, retrieved_at
    )
    return metrics


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Download official sources and build PHN population-health outputs."
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=project_root / "data" / "raw"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=project_root / "data" / "processed"
    )
    arguments = parser.parse_args()
    metrics = build_dataset(arguments.raw_dir, arguments.output_dir)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
