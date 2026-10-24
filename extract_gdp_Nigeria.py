"""
Extract Kummu v4 GDP data for Nigeria WITHOUT a local admin boundary file —
pulls the ADM0 (country) boundary on the fly from the geoBoundaries API.

geoBoundaries: https://www.geoboundaries.org  (open, free, no API key needed)
Nigeria ISO3 code: NGA
"""

import requests
import geopandas as gpd


def get_country_boundary(iso3: str, adm_level: str = "ADM0") -> gpd.GeoDataFrame:
    """
    Download a country boundary from the geoBoundaries API without needing a
    local shapefile/geopackage.

    iso3: 3-letter ISO country code, e.g. "NGA" for Nigeria, "COD" for DRC
    adm_level: "ADM0" (country), "ADM1" (state), "ADM2" (LGA), etc.
    """
    api_url = f"https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{adm_level}/"
    meta = requests.get(api_url, timeout=30).json()
    geojson_url = meta["gjDownloadURL"]

    gdf = gpd.read_file(geojson_url)
    print(f"Loaded {iso3} {adm_level} boundary: {len(gdf)} feature(s), CRS={gdf.crs}")
    return gdf


# --- Get Nigeria's country boundary (ISO3 = NGA) — latest year only (2024) ---
nigeria_gdf = get_country_boundary("NGA", adm_level="ADM0")

tif_path = gdp_path + "\\rast_gdpTot_1990_2024_30arcsec.tif"

da_nga_2024 = preprocess_kummu_gdp_tif_windowed(
    tif_path=tif_path,
    year=2024,
    boundary_gdf=nigeria_gdf,
    out_path=gdp_path + "\\GDP_PPP_2024_NGA.tif",
)

print("\nTotal Nigeria GDP 2024 (v4, sum of pixels):", float(da_nga_2024.sum()))
