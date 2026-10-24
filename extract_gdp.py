"""
GDP extraction pipeline for Nigeria (NGA) — Kummu v4 dataset.

Combines:
  - General-purpose country GDP extractor (any country by name or ISO3 code)
  - Batch extraction across multiple countries/years
  - Nigeria-specific extraction (NGA, 2024 only)

Boundary fetched automatically from the geoBoundaries API — no local shapefile needed.

Usage (general):
    from extract_gdp import extract_country_gdp, batch_extract_gdp
    da = extract_country_gdp("NGA", 2024, gdp_path=r"C:\...\GDP_data")

Usage (Nigeria-specific, run as script):
    python extract_gdp.py
"""

import os
import requests
import rasterio
from rasterio.windows import from_bounds
import numpy as np
import xarray as xr
import geopandas as gpd
import rioxarray as rxr
import pandas as pd

try:
    import pycountry
except ImportError:
    pycountry = None


# ---------------------------------------------------------------------------
# Boundary cache — avoids re-downloading the same boundary in one session
# ---------------------------------------------------------------------------
_boundary_cache = {}


def _resolve_iso3(country: str) -> str:
    """Accepts a country name ('Nigeria') or ISO3 code ('NGA') and returns the ISO3 code."""
    country = country.strip()
    if len(country) == 3 and country.isalpha() and country.isupper():
        return country

    if pycountry is None:
        raise ImportError(
            "pycountry is required for country-name lookup. "
            "Install it with: pip install pycountry\n"
            "Or pass the ISO3 code directly, e.g. extract_country_gdp('NGA', 2024)"
        )
    try:
        matches = pycountry.countries.search_fuzzy(country)
        iso3 = matches[0].alpha_3
        print(f"Resolved '{country}' -> ISO3 '{iso3}' ({matches[0].name})")
        return iso3
    except LookupError:
        raise ValueError(f"Could not resolve country name '{country}' to an ISO3 code.")


def _get_country_boundary(iso3: str, adm_level: str = "ADM0") -> gpd.GeoDataFrame:
    """Download a country boundary from the geoBoundaries API (cached per iso3+level)."""
    cache_key = (iso3, adm_level)
    if cache_key in _boundary_cache:
        return _boundary_cache[cache_key]

    api_url = f"https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{adm_level}/"
    meta = requests.get(api_url, timeout=30).json()
    gdf = gpd.read_file(meta["gjDownloadURL"])
    print(f"Loaded {iso3} {adm_level} boundary: {len(gdf)} feature(s), CRS={gdf.crs}")
    _boundary_cache[cache_key] = gdf
    return gdf


# Source file registry for the two GDP variants Kummu v4 provides
_VARIANT_FILES = {
    "total":     "rast_gdpTot_1990_2024_30arcsec.tif",
    "percapita": "rast_adm0_gdp_perCapita_1990_2024.tif",
}


# ---------------------------------------------------------------------------
# General-purpose extractor
# ---------------------------------------------------------------------------
def extract_country_gdp(country: str, year: int, tif_path: str = None, out_path: str = None,
                         band_years=(1990, 1995, 2000, 2005, 2010, 2015, 2020, 2024),
                         pad_deg: float = 0.05, adm_level: str = "ADM0",
                         gdp_path: str = None, plot: bool = False,
                         variant: str = "total", mask_zero: bool = True,
                         zero_value: float = 0):
    """
    Extract a clipped, single-year GDP raster for any country by name or ISO3 code.

    country:   country name or ISO3 code (e.g. "NGA", "Nigeria")
    year:      year to extract — must be one of band_years
    gdp_path:  folder containing the source .tif and where output is saved
    variant:   "total" (default) for total GDP per pixel,
               "percapita" for GDP per capita per pixel
    """
    if variant not in _VARIANT_FILES:
        raise ValueError(f"variant must be one of {list(_VARIANT_FILES)}, got '{variant}'")

    if gdp_path is None:
        gdp_path = globals().get("gdp_path")
        if gdp_path is None:
            raise ValueError("gdp_path not provided and no global 'gdp_path' variable found.")

    if tif_path is None:
        tif_path = os.path.join(gdp_path, _VARIANT_FILES[variant])

    iso3 = _resolve_iso3(country)
    boundary_gdf = _get_country_boundary(iso3, adm_level=adm_level)

    if out_path is None:
        suffix = "PerCapita" if variant == "percapita" else "PPP"
        out_path = os.path.join(gdp_path, f"GDP_{suffix}_{year}_{iso3}.tif")

    with rasterio.open(tif_path) as src:
        raster_crs = src.crs

    if boundary_gdf.crs != raster_crs:
        boundary_gdf = boundary_gdf.to_crs(raster_crs)

    minx, miny, maxx, maxy = boundary_gdf.total_bounds
    minx, miny, maxx, maxy = minx - pad_deg, miny - pad_deg, maxx + pad_deg, maxy + pad_deg

    with rasterio.open(tif_path) as src:
        n_bands = src.count

        tag_years = []
        for b in range(1, n_bands + 1):
            tags = src.tags(b)
            y = tags.get("year") or tags.get("YEAR") or tags.get("DATE") or tags.get("DESCRIPTION")
            tag_years.append(int(y) if y and str(y).strip().isdigit() else None)

        if all(y is not None for y in tag_years) and len(tag_years) == n_bands:
            band_years = tag_years
        if len(band_years) != n_bands:
            raise ValueError(f"band_years has {len(band_years)} entries but file has {n_bands} bands.")
        if year not in band_years:
            raise ValueError(f"Year {year} not available. Bands correspond to: {band_years}")

        band_idx = band_years.index(year) + 1
        window = from_bounds(minx, miny, maxx, maxy, transform=src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(band_idx, window=window)
        window_transform = src.window_transform(window)
        nodata = src.nodata

    data = data.astype("float32")
    if mask_zero:
        data[data == zero_value] = np.nan
    nodata_out = np.nan if (mask_zero or nodata is None) else nodata

    height, width = data.shape
    xs = window_transform.c + window_transform.a * (np.arange(width) + 0.5)
    ys = window_transform.f + window_transform.e * (np.arange(height) + 0.5)

    da_year = xr.DataArray(data, dims=("y", "x"), coords={"y": ys, "x": xs}, name="gdp")
    da_year = da_year.rio.write_crs(raster_crs, inplace=True)
    da_year = da_year.rio.write_nodata(nodata_out, inplace=True)
    da_clipped = da_year.rio.clip(boundary_gdf.geometry, boundary_gdf.crs, drop=True)

    vals = da_clipped.values
    n_valid = int(np.isfinite(vals).sum())
    if variant == "percapita":
        print(f"{country} ({iso3}) {year}: {n_valid} valid pixels, "
              f"GDP/capita mean={float(np.nanmean(vals)):,.0f}, median={float(np.nanmedian(vals)):,.0f}")
    else:
        print(f"{country} ({iso3}) {year}: {n_valid} valid pixels, "
              f"total GDP={float(np.nansum(vals)):,.0f}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    da_clipped.rio.to_raster(out_path)
    print("Saved:", out_path)

    if plot:
        import matplotlib.pyplot as plt
        da_clipped.plot(robust=True)
        plt.title(f"{country} GDP (PPP) {year} — Kummu v4")
        plt.show()

    return da_clipped


# ---------------------------------------------------------------------------
# Batch extractor
# ---------------------------------------------------------------------------
def batch_extract_gdp(countries, years, gdp_path=None, adm_level="ADM0",
                       pad_deg=0.05, plot=False, stop_on_error=False):
    """
    Run extract_country_gdp() for every (country, year) combination.
    Returns a pandas DataFrame summarising results.
    """
    rows = []
    for country in countries:
        for year in years:
            print(f"\n--- {country}, {year} ---")
            try:
                da = extract_country_gdp(country=country, year=year, gdp_path=gdp_path,
                                          adm_level=adm_level, pad_deg=pad_deg, plot=plot)
                vals = da.values
                rows.append({
                    "country": country, "year": year, "status": "ok",
                    "total_gdp": float(pd.Series(vals.ravel()).sum(skipna=True)),
                    "n_valid_pixels": int((vals == vals).sum()),
                    "shape": da.shape, "error": None,
                })
            except Exception as e:
                print(f"  FAILED: {e}")
                rows.append({
                    "country": country, "year": year, "status": "error",
                    "total_gdp": None, "n_valid_pixels": None, "shape": None, "error": str(e),
                })
                if stop_on_error:
                    raise

    summary = pd.DataFrame(rows)
    print("\n=== BATCH SUMMARY ===")
    print(summary.to_string(index=False))
    return summary


# ---------------------------------------------------------------------------
# Nigeria-specific extraction (NGA, 2024)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    gdp_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\path\to\GDP_data"

    da_nga = extract_country_gdp(
        country="NGA",
        year=2024,
        gdp_path=gdp_path,
        out_path=os.path.join(gdp_path, "GDP_PPP_2024_NGA.tif"),
    )
    print("\nTotal Nigeria GDP 2024 (sum of pixels):", float(da_nga.sum()))
