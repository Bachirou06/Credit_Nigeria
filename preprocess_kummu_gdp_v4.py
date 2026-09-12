"""
Download + preprocess the Kummu et al. GDP (PPP) v4 dataset from Zenodo (record 18429133),
select a single year's band from the multiband GeoTIFF, and clip it to a boundary.

Source: https://zenodo.org/records/18429133
Kummu, M., Kosonen, M. & Masoumzadeh Sayyar, S. 2025. Downscaled gridded global dataset
for gross domestic product (GDP) per capita PPP over 1990-2022 (updated to 2024).
Scientific Data 12: 178. https://doi.org/10.1038/s41597-025-04487-x

Usage:
    from preprocess_kummu_gdp_v4 import download_file, preprocess_kummu_gdp_tif

    tif_path = download_file(
        url="https://zenodo.org/records/18429133/files/rast_gdpTot_1990_2024_30arcsec.tif?download=1",
        out_dir=gdp_path,
    )

    da_mw = preprocess_kummu_gdp_tif(
        tif_path=tif_path,
        year=2015,
        boundary_gdf=malawi_gdf,
        out_path=os.path.join(gdp_path, "GDP_PPP_2015_v4.tif"),
    )
"""

import os
import requests
import rioxarray as rxr


# --- File registry: name -> direct download URL (from the Zenodo files list) ---
KUMMU_V4_FILES = {
    "rast_gdpTot_1990_2024_30arcsec.tif":
        "https://zenodo.org/records/18429133/files/rast_gdpTot_1990_2024_30arcsec.tif?download=1",
    "rast_gdpTot_1990_2024_5arcmin.tif":
        "https://zenodo.org/records/18429133/files/rast_gdpTot_1990_2024_5arcmin.tif?download=1",
    "rast_gdpTot_1990_2024_30arcmin.tif":
        "https://zenodo.org/records/18429133/files/rast_gdpTot_1990_2024_30arcmin.tif?download=1",
    "rast_adm2_gdp_perCapita_1990_2024.tif":
        "https://zenodo.org/records/18429133/files/rast_adm2_gdp_perCapita_1990_2024.tif?download=1",
    "rast_adm1_gdp_perCapita_1990_2024.tif":
        "https://zenodo.org/records/18429133/files/rast_adm1_gdp_perCapita_1990_2024.tif?download=1",
    "rast_adm0_gdp_perCapita_1990_2024.tif":
        "https://zenodo.org/records/18429133/files/rast_adm0_gdp_perCapita_1990_2024.tif?download=1",
}


def download_file(url: str, out_dir: str, filename: str = None, chunk_size: int = 1 << 20,
                   overwrite: bool = False) -> str:
    """
    Stream-download a (potentially large) file from a direct URL without loading it
    fully into memory. Returns the local file path.
    """
    if filename is None:
        filename = url.split("/")[-1].split("?")[0]
    out_path = os.path.join(out_dir, filename)

    if os.path.exists(out_path) and not overwrite:
        print(f"Already exists, skipping download: {out_path}")
        return out_path

    os.makedirs(out_dir, exist_ok=True)

    print(f"Downloading {url}\n  -> {out_path}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {downloaded/1e6:,.0f} MB / {total/1e6:,.0f} MB ({pct:5.1f}%)",
                          end="", flush=True)
    print("\nDownload complete.")
    return out_path


def preprocess_kummu_gdp_tif(tif_path, year, boundary_gdf, out_path,
                              band_years=(1990, 1995, 2000, 2005, 2010, 2015, 2020, 2024)):
    import rasterio
    import numpy as np
    import xarray as xr

    with rasterio.open(tif_path) as src:
        n_bands = src.count
        transform = src.transform
        crs = src.crs
        height, width = src.height, src.width

        # Try to recover year labels from band tags; fall back to assumed order
        tag_years = []
        for b in range(1, n_bands + 1):
            tags = src.tags(b)
            y = tags.get("year") or tags.get("YEAR") or tags.get("DATE") or tags.get("DESCRIPTION")
            tag_years.append(int(y) if y and str(y).strip().isdigit() else None)

        if all(y is not None for y in tag_years) and len(tag_years) == n_bands:
            print("Using year labels found in band tags:", tag_years)
            band_years = tag_years
        else:
            print("No usable embedded band-year tags found; assuming order:", band_years)
            print("  -> VERIFY this matches github.com/mattikummu/griddedGDPpc before trusting results.")

        if len(band_years) != n_bands:
            raise ValueError(f"band_years has {len(band_years)} entries but file has {n_bands} bands.")
        if year not in band_years:
            raise ValueError(f"Year {year} not available. Bands correspond to: {band_years}")

        band_idx = band_years.index(year) + 1  # rasterio bands are 1-indexed
        print(f"Reading band {band_idx} -> year {year}")

        arr = src.read(band_idx, masked=True)
        nodata = src.nodata

    # Build pixel-center coordinates from the affine transform
    xs = transform.c + transform.a * (np.arange(width) + 0.5)
    ys = transform.f + transform.e * (np.arange(height) + 0.5)

    data = arr.filled(np.nan) if np.ma.isMaskedArray(arr) else arr

    da_year = xr.DataArray(
        data,
        dims=("y", "x"),
        coords={"y": ys, "x": xs},
        name="gdp",
    )
    da_year = da_year.rio.write_crs(crs, inplace=True)
    da_year = da_year.rio.write_nodata(np.nan, inplace=True)

    print("CRS:", da_year.rio.crs)
    print("Shape (y, x):", da_year.shape)

    da_year = da_year.rio.clip(boundary_gdf.geometry, boundary_gdf.crs, drop=True)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    da_year.rio.to_raster(out_path)
    print("Saved:", out_path)

    return da_year

if __name__ == "__main__":
    # Example end-to-end run — adjust paths/variables to match your environment.
    import geopandas as gpd

    gdp_path = r"C:\path\to\your\gdp_data"          # <-- set this
    boundary_path = r"C:\path\to\malawi_boundary.gpkg"  # <-- set this

    malawi_gdf = gpd.read_file(boundary_path)

    tif_path = download_file(
        url=KUMMU_V4_FILES["rast_gdpTot_1990_2024_30arcsec.tif"],
        out_dir=gdp_path,
    )

    da_mw = preprocess_kummu_gdp_tif(
        tif_path=tif_path,
        year=2015,
        boundary_gdf=malawi_gdf,
        out_path=os.path.join(gdp_path, "GDP_PPP_2015_v4.tif"),
    )
