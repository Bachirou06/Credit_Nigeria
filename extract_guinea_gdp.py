"""
Extract Kummu v4 GDP data for Guinea WITHOUT a local admin boundary file —
pulls the ADM0 (country) boundary on the fly from the geoBoundaries API.

geoBoundaries: https://www.geoboundaries.org  (open, free, no API key needed)
"""

import requests
import geopandas as gpd


def get_country_boundary(iso3: str, adm_level: str = "ADM0") -> gpd.GeoDataFrame:
    """
    Download a country boundary from the geoBoundaries API without needing a
    local shapefile/geopackage.

    iso3: 3-letter ISO country code, e.g. "GIN" for Guinea, "MWI" for Malawi
    adm_level: "ADM0" (country), "ADM1" (region/province), "ADM2" (district), etc.
    """
    api_url = f"https://www.geoboundaries.org/api/current/gbOpen/{iso3}/{adm_level}/"
    meta = requests.get(api_url, timeout=30).json()
    geojson_url = meta["gjDownloadURL"]

    gdf = gpd.read_file(geojson_url)
    print(f"Loaded {iso3} {adm_level} boundary: {len(gdf)} feature(s), CRS={gdf.crs}")
    return gdf


# --- Get Guinea's country boundary (ISO3 = GIN) ---
guinea_gdf = get_country_boundary("GIN", adm_level="ADM0")

# --- Run the same windowed extraction used for Malawi ---
tif_path = gdp_path + "\\rast_gdpTot_1990_2024_30arcsec.tif"

da_guinea_2015 = preprocess_kummu_gdp_tif_windowed(
    tif_path=tif_path,
    year=2015,
    boundary_gdf=guinea_gdf,
    out_path=gdp_path + "\\GDP_PPP_2015_Guinea_v4.tif",
)

da_guinea_2024 = preprocess_kummu_gdp_tif_windowed(
    tif_path=tif_path,
    year=2024,
    boundary_gdf=guinea_gdf,
    out_path=gdp_path + "\\GDP_PPP_2024_Guinea_v4.tif",
)

print("\nTotal Guinea GDP 2015 (v4, sum of pixels):", float(da_guinea_2015.sum()))
print("Total Guinea GDP 2024 (v4, sum of pixels):", float(da_guinea_2024.sum()))
