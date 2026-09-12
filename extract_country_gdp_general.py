"""
General-purpose Kummu v4 GDP extractor.

Call with just a country name (or ISO3 code) and a year — the boundary is fetched
automatically from geoBoundaries, no local shapefile needed, and no need to call
preprocess_kummu_gdp_tif_windowed / get_country_boundary manually each time.

Usage:
    da = extract_country_gdp("Guinea", 2015)
    da = extract_country_gdp("Malawi", 2024)
    da = extract_country_gdp("GIN", 2020)          # ISO3 codes also work directly
"""

import os
import requests
import rasterio
from rasterio.windows import from_bounds
import numpy as np
import xarray as xr
import geopandas as gpd
import rioxarray as rxr

try:
    import pycountry
except ImportError:
    pycountry = None


# --- Simple in-memory cache so repeated calls for the same country don't re-download the boundary ---
_boundary_cache = {}


def _resolve_iso3(country: str) -> str:
    """
    Accepts either a country name ('Guinea') or an ISO3 code ('GIN') and returns
    the ISO3 code. Requires the `pycountry` package for name lookup.
    """
    country = country.strip()
    if len(country) == 3 and country.isalpha() and country.isupper():
        return country  # already looks like an ISO3 code

    if pycountry is None:
        raise ImportError(
            "pycountry is required for country-name lookup. "
            "Install it with: pip install pycountry\n"
            "Or pass the ISO3 code directly, e.g. extract_country_gdp('GIN', 2015)"
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
    geojson_url = meta["gjDownloadURL"]

    gdf = gpd.read_file(geojson_url)
    print(f"Loaded {iso3} {adm_level} boundary: {len(gdf)} feature(s), CRS={gdf.crs}")
    _boundary_cache[cache_key] = gdf
    return gdf


# --- Source file registry for the two GDP variants Kummu v4 provides ---
_VARIANT_FILES = {
    "total": "rast_gdpTot_1990_2024_30arcsec.tif",          # total GDP, PPP, per pixel
    "percapita": "rast_adm0_gdp_perCapita_1990_2024.tif",   # GDP per capita, PPP, adm0-level
}


def extract_country_gdp(country: str, year: int, tif_path: str = None, out_path: str = None,
                         band_years=(1990, 1995, 2000, 2005, 2010, 2015, 2020, 2024),
                         pad_deg: float = 0.05, adm_level: str = "ADM0",
                         gdp_path: str = None, plot: bool = False,
                         variant: str = "total",
                         mask_zero: bool = True, zero_value: float = 0):
    """
    Extract a clipped, single-year GDP raster for any country by name or ISO3 code.

    country:   country name ("Guinea") or ISO3 code ("GIN")
    year:      year to extract, must be one of band_years (default: Kummu v4's 5-year steps)
    tif_path:  path to the source multiband GeoTIFF. If None, built from gdp_path + variant.
    out_path:  where to save the clipped GeoTIFF. If None, auto-named in gdp_path.
    gdp_path:  folder containing the source file / where output is saved (uses the
               global `gdp_path` variable from your session if not passed).
    plot:      if True, shows a quick matplotlib preview after extraction.
    variant:   "total" (default) for total GDP per pixel (summing pixels = country total),
               or "percapita" for GDP per capita per pixel (summing pixels is meaningless —
               use mean/median across valid pixels instead for a representative figure).
    mask_zero: if True (default), pixels equal to `zero_value` are converted to
               NoData before clipping/saving. Set False to keep raw zeros.
    zero_value: the pixel value treated as "empty" when mask_zero=True (default 0).

    Returns the clipped xarray DataArray.
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

    # --- Reproject boundary to raster CRS if needed ---
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

    # --- Convert zero-value pixels to NoData (replaces manual QGIS transparency step) ---
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
        mean_val = float(np.nanmean(vals)) if n_valid else float("nan")
        median_val = float(np.nanmedian(vals)) if n_valid else float("nan")
        print(f"{country} ({iso3}) {year}: {n_valid}/{vals.size} valid pixels, "
              f"GDP per capita — mean = {mean_val:,.0f}, median = {median_val:,.0f}")
    else:
        total = float(np.nansum(vals))
        print(f"{country} ({iso3}) {year}: {n_valid}/{vals.size} valid pixels, "
              f"total GDP (sum of pixels) = {total:,.0f}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    da_clipped.rio.to_raster(out_path)
    print("Saved:", out_path)

    if plot:
        import matplotlib.pyplot as plt
        da_clipped.plot(robust=True)
        plt.title(f"{country} GDP (PPP) {year} — Kummu v4")
        plt.show()

    return da_clipped