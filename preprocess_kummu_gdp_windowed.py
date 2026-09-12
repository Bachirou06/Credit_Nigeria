"""
Fast, memory-light version: reads only the Malawi bounding-box window directly from
disk (via rasterio windowed reads) instead of loading the full global band into memory.
"""

import os
import rasterio
from rasterio.windows import from_bounds
import numpy as np
import xarray as xr
import rioxarray as rxr


def preprocess_kummu_gdp_tif_windowed(tif_path, year, boundary_gdf, out_path,
                                       band_years=(1990, 1995, 2000, 2005, 2010, 2015, 2020, 2024),
                                       pad_deg=0.05):
    """
    Windowed read: only pulls the pixels inside boundary_gdf's bounding box (plus a
    small padding) from disk, instead of reading the entire global raster.
    """
    # Make sure boundary is in the raster's CRS (EPSG:4326) before computing bounds
    with rasterio.open(tif_path) as src:
        raster_crs = src.crs

    if boundary_gdf.crs != raster_crs:
        print(f"Reprojecting boundary from {boundary_gdf.crs} to {raster_crs}")
        boundary_gdf = boundary_gdf.to_crs(raster_crs)

    minx, miny, maxx, maxy = boundary_gdf.total_bounds
    minx, miny, maxx, maxy = minx - pad_deg, miny - pad_deg, maxx + pad_deg, maxy + pad_deg
    print(f"Malawi window bounds (padded): {(minx, miny, maxx, maxy)}")

    with rasterio.open(tif_path) as src:
        n_bands = src.count

        # Recover year labels from band tags where possible
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

        band_idx = band_years.index(year) + 1

        window = from_bounds(minx, miny, maxx, maxy, transform=src.transform)
        window = window.round_offsets().round_lengths()
        print(f"Reading window: {window} (band {band_idx} -> year {year})")

        data = src.read(band_idx, window=window)
        window_transform = src.window_transform(window)
        nodata = src.nodata

        print("Window shape (rows, cols):", data.shape)
        print("Window data min/max:", np.nanmin(data), np.nanmax(data))
        print("# finite (non-nan/non-nodata) pixels:", np.isfinite(data).sum(), "/", data.size)

    height, width = data.shape
    xs = window_transform.c + window_transform.a * (np.arange(width) + 0.5)
    ys = window_transform.f + window_transform.e * (np.arange(height) + 0.5)

    da_year = xr.DataArray(
        data,
        dims=("y", "x"),
        coords={"y": ys, "x": xs},
        name="gdp",
    )
    da_year = da_year.rio.write_crs(raster_crs, inplace=True)
    da_year = da_year.rio.write_nodata(nodata if nodata is not None else np.nan, inplace=True)

    print("Pre-clip shape:", da_year.shape, "CRS:", da_year.rio.crs)

    da_clipped = da_year.rio.clip(boundary_gdf.geometry, boundary_gdf.crs, drop=True)

    vals = da_clipped.values
    print("Post-clip shape:", da_clipped.shape)
    print("Post-clip # finite pixels:", np.isfinite(vals).sum(), "/", vals.size)
    print("Post-clip min/max:", np.nanmin(vals) if np.isfinite(vals).any() else "ALL NAN",
          np.nanmax(vals) if np.isfinite(vals).any() else "ALL NAN")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    da_clipped.rio.to_raster(out_path)
    print("Saved:", out_path)

    return da_clipped


if __name__ == "__main__":
    pass  # call preprocess_kummu_gdp_tif_windowed(...) from your notebook
