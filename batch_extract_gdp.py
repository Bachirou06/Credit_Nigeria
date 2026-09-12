"""
Batch extraction: run extract_country_gdp() across multiple countries and/or years
in one call, with a summary table at the end.

Requires extract_country_gdp() (and its helpers) already defined in your session.

Usage:
    results = batch_extract_gdp(
        countries=["Guinea", "Malawi", "Senegal"],
        years=[2015, 2024],
    )
    results  # a pandas DataFrame summarizing totals, valid pixel counts, output paths
"""

import pandas as pd


def batch_extract_gdp(countries, years, gdp_path=None, adm_level="ADM0",
                       pad_deg=0.05, plot=False, stop_on_error=False):
    """
    Run extract_country_gdp() for every (country, year) combination.

    countries: list of country names or ISO3 codes, e.g. ["Guinea", "Malawi"]
    years:     list of years to extract for each country, e.g. [2015, 2024]
    stop_on_error: if False (default), failures for one country/year are logged
                   and skipped rather than halting the whole batch.

    Returns a pandas DataFrame with one row per (country, year) summarizing the result.
    """
    rows = []

    for country in countries:
        for year in years:
            print(f"\n--- {country}, {year} ---")
            try:
                da = extract_country_gdp(
                    country=country,
                    year=year,
                    gdp_path=gdp_path,
                    adm_level=adm_level,
                    pad_deg=pad_deg,
                    plot=plot,
                )
                vals = da.values
                rows.append({
                    "country": country,
                    "year": year,
                    "status": "ok",
                    "total_gdp": float(pd.Series(vals.ravel()).sum(skipna=True)),
                    "n_valid_pixels": int((vals == vals).sum()),  # NaN-safe count
                    "shape": da.shape,
                    "error": None,
                })
            except Exception as e:
                print(f"  FAILED: {e}")
                rows.append({
                    "country": country,
                    "year": year,
                    "status": "error",
                    "total_gdp": None,
                    "n_valid_pixels": None,
                    "shape": None,
                    "error": str(e),
                })
                if stop_on_error:
                    raise

    summary = pd.DataFrame(rows)
    print("\n=== BATCH SUMMARY ===")
    print(summary.to_string(index=False))
    return summary
