"""
extract_poverty_data_hdx.py

Downloads, per country:
  1. Subnational (admin-1) Multidimensional Poverty Index (MPI) tabular
     data, from that country's own HDX dataset (e.g. "niger-mpi",
     "chad-mpi"), originally published by the Oxford Poverty and Human
     Development Initiative (OPHI), University of Oxford.
  2. The country's admin-1 boundary shapefile, from HDX's Common
     Operational Dataset - Administrative Boundaries (COD-AB), e.g.
     "cod-ab-ner" for Niger.

Both datasets use standardized PCodes, so the tabular poverty data joins
directly to the shapefile without any name-matching.

Output layout (created automatically if missing):
    <out_dir>/
        tabular/
            <Country>_<resource_name>.csv
        shapefile/
            <Country>_<resource_name>.zip
            <Country>_<resource_name>/          (extracted contents)
                ..._admbnda_adm1_....shp / .shx / .dbf / .prj / ...

extract_country_shapefile() returns the path to the ADMIN-1 .shp file
specifically (picked out from the extracted archive, which may bundle
multiple admin levels), with its .shx/.dbf/.prj companions alongside it
in the same folder — ready for geopandas.read_file().

Files already on disk are NOT re-downloaded.

Accepts either a country name (any casing/spelling, e.g. "Niger", "ivory coast")
or an ISO3 code (e.g. "NER"); normalizes it via pycountry (if installed) with
a manual alias fallback.

Usage (single country, both tabular + shapefile):
    python extract_poverty_data_hdx.py Niger

Usage (batch):
    python extract_poverty_data_hdx.py --batch Niger Chad "Burkina Faso"

Usage (as a module):
    from extract_poverty_data_hdx import extract_country_data, batch_extract_data
    result = extract_country_data("Niger")
    df_poverty = result["tabular"]
    shapefile_path = result["shapefile"]

Optional dependency for robust name/ISO3 normalization:
    pip install pycountry
(the script still works without it, using exact/fuzzy string matching only)
"""

import argparse
import difflib
import zipfile
from pathlib import Path

import pandas as pd
import requests

try:
    import pycountry
    HAS_PYCOUNTRY = True
except ImportError:
    HAS_PYCOUNTRY = False

HDX_CKAN_API = "https://data.humdata.org/api/3/action"

# Anchor all relative output paths to the folder this script lives in
# (e.g. C:\Users\Bachirou\Documents\CREDIT_layer), not to whatever
# directory the notebook kernel happens to be running from.
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = PROJECT_ROOT / "poverty_data"
TABULAR_SUBDIR = "tabular"
SHAPEFILE_SUBDIR = "shapefile"

# Fallback aliases for country names that differ between common usage and
# HDX/OPHI resource naming (extend as you encounter mismatches).
COUNTRY_ALIASES = {
    "ivory coast": "cote d'ivoire",
    "cape verde": "cabo verde",
    "swaziland": "eswatini",
    "drc": "congo, the democratic republic of the",
    "congo-kinshasa": "congo, the democratic republic of the",
    "congo-brazzaville": "congo",
}


def _exact_country_match(key: str):
    """
    Look for an exact case-insensitive match against a country's name,
    official_name, or common_name. Returns the pycountry Country object
    or None. This MUST run before any fuzzy search: pycountry's
    search_fuzzy("niger") can incorrectly return Nigeria, since "niger"
    is a substring of "nigeria" and fuzzy scoring doesn't reliably
    prioritize the exact match.
    """
    for c in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            val = getattr(c, attr, None)
            if val and val.lower() == key:
                return c
    return None


def normalize_country(country: str) -> str:
    """
    Accepts a country name (any casing/spelling) or an ISO3 code and
    returns the official short name pycountry/HDX is most likely to use.
    Falls back to a manual alias table, then to the input as-is.
    """
    key = country.strip().lower()
    key = COUNTRY_ALIASES.get(key, key)

    if HAS_PYCOUNTRY:
        # 1. Try as ISO3 code first (e.g. "NER")
        by_code = pycountry.countries.get(alpha_3=country.strip().upper())
        if by_code:
            return by_code.name
        # 2. Try an EXACT name match before any fuzzy search (avoids the
        #    Niger -> Nigeria fuzzy-match bug)
        exact = _exact_country_match(key)
        if exact:
            return exact.name
        # 3. Only now fall back to fuzzy matching
        try:
            match = pycountry.countries.search_fuzzy(key)
            if match:
                return match[0].name
        except LookupError:
            pass

    return country.strip()


def country_iso3(country: str) -> str:
    """Return the lowercase ISO3 code for a country, e.g. 'Niger' -> 'ner'."""
    if HAS_PYCOUNTRY:
        by_code = pycountry.countries.get(alpha_3=country.strip().upper())
        if by_code:
            return by_code.alpha_3.lower()
        key = country.strip().lower()
        key = COUNTRY_ALIASES.get(key, key)
        exact = _exact_country_match(key)
        if exact:
            return exact.alpha_3.lower()
        try:
            match = pycountry.countries.search_fuzzy(normalize_country(country))
            if match:
                return match[0].alpha_3.lower()
        except LookupError:
            pass
    raise ValueError(
        f"Could not resolve an ISO3 code for country='{country}'. "
        f"Install pycountry (pip install pycountry) or pass the ISO3 code directly."
    )


def country_dataset_slug(country: str) -> str:
    """
    Build the HDX dataset slug for a country's subnational MPI dataset,
    following HDX's observed pattern: '<country-name-lowercase-hyphenated>-mpi'
    e.g. 'Niger' -> 'niger-mpi', 'Burkina Faso' -> 'burkina-faso-mpi'.
    """
    official_name = normalize_country(country)
    slug_base = official_name.lower().strip()
    slug_base = slug_base.replace("'", "").replace(",", "")
    slug_base = "-".join(slug_base.split())
    return f"{slug_base}-mpi"


def get_dataset_resources(dataset_slug: str) -> list:
    """Fetch metadata (including the resource list) for an HDX dataset by slug."""
    url = f"{HDX_CKAN_API}/package_show"
    resp = requests.get(url, params={"id": dataset_slug}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"HDX API request failed for dataset '{dataset_slug}': {data}")
    return data["result"]["resources"]


def get_country_mpi_resources(country: str) -> list:
    """
    Resolve a country's own HDX MPI dataset and return its resources.
    Tries the primary slug (normalized official name), then falls back
    to the raw input name.
    """
    official_name = normalize_country(country)
    tried = []
    for name_variant in dict.fromkeys([official_name, country.strip()]):
        slug = country_dataset_slug(name_variant)
        tried.append(slug)
        try:
            return get_dataset_resources(slug)
        except (requests.HTTPError, RuntimeError):
            continue
    raise ValueError(
        f"Could not find an HDX MPI dataset for country='{country}' "
        f"(resolved as '{official_name}'). Tried slugs: {tried}. "
        f"Check the exact dataset slug on https://data.humdata.org."
    )


def get_country_boundary_resources(country: str) -> list:
    """
    Resolve a country's HDX COD-AB (admin boundaries) dataset, following
    the observed slug pattern 'cod-ab-<iso3>', e.g. 'cod-ab-ner' for Niger.
    """
    iso3 = country_iso3(country)
    slug = f"cod-ab-{iso3}"
    try:
        return get_dataset_resources(slug)
    except (requests.HTTPError, RuntimeError) as exc:
        raise ValueError(
            f"Could not find an HDX admin-boundaries dataset for country='{country}' "
            f"(tried slug='{slug}'). Check the exact slug on https://data.humdata.org. "
            f"Original error: {exc}"
        )


def _warn_if_country_mismatch(resource: dict, country: str) -> None:
    """Print a loud warning if the resource name doesn't mention the
    requested country at all — a sign the wrong dataset/resource was matched."""
    name_lower = resource["name"].lower()
    official = normalize_country(country).lower()
    tokens = {official, country.strip().lower()}
    if HAS_PYCOUNTRY:
        try:
            tokens.add(country_iso3(country))
        except ValueError:
            pass
    if not any(tok in name_lower for tok in tokens if tok):
        print(
            f"[WARNING] Resource '{resource['name']}' does not appear to mention "
            f"'{country}' — double-check this is the correct country's data before using it."
        )


def find_resource_by_kind(resources: list, label: str, kind: str) -> dict:
    """
    Pick the resource matching 'kind' (a substring or fuzzy target) within
    a list of resources. 'label' is only used for error messages.
    """
    kind_lower = kind.lower()
    matches = [r for r in resources if kind_lower in r["name"].lower()]

    if not matches:
        candidate_names = [r["name"] for r in resources]
        close = difflib.get_close_matches(kind, candidate_names, n=1, cutoff=0.4)
        if close:
            matches = [r for r in resources if r["name"] == close[0]]

    if not matches:
        available = [r["name"] for r in resources]
        raise ValueError(
            f"No resource matching kind='{kind}' found for '{label}'. "
            f"Available resources: {available}"
        )
    return matches[0]


def find_admin1_shapefile_resource(resources: list, country: str) -> dict:
    """
    Pick the admin-1 shapefile resource from a COD-AB dataset's resource
    list. Tries common naming tokens in order, then falls back to any
    zipped shapefile resource (COD-AB datasets often ship one zip per
    admin level, or one zip containing all levels).
    """
    tokens = ["adm1", "admin1", "administrative level 1", "admin 1", "level 1", "level1"]
    for token in tokens:
        matches = [r for r in resources if token in r["name"].lower()]
        if matches:
            return matches[0]

    # Fallback: any resource that looks like a shapefile package
    shp_like = [
        r for r in resources
        if r.get("format", "").lower() in ("shp", "zip")
        or "shp" in r["name"].lower()
    ]
    if shp_like:
        return shp_like[0]

    available = [r["name"] for r in resources]
    raise ValueError(
        f"No admin-1 shapefile resource found for country='{country}'. "
        f"Available resources: {available}"
    )


def download_resource_if_missing(resource: dict, out_dir: Path, country: str,
                                  extension: str = None) -> Path:
    """
    Download a CKAN resource file to out_dir, unless a file with the same
    target name already exists on disk (in which case the existing file
    is reused and nothing is re-downloaded). Returns the local path.

    The saved extension is taken from the actual URL when possible
    (HDX's declared 'format' field is unreliable — e.g. a zipped
    shapefile is often labelled format='SHP' even though the file
    itself is a .zip archive).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{country.strip().replace(' ', '_')}_"
    safe_name = resource["name"].replace(" ", "_").replace("/", "-")

    url_suffix = Path(resource["url"].split("?")[0]).suffix.lstrip(".").lower()
    ext = extension or url_suffix or resource.get("format", "").lower() or "dat"
    out_path = out_dir / f"{prefix}{safe_name}.{ext}"

    if out_path.exists():
        print(f"[SKIP] {out_path.name} already exists, not re-downloading.")
        return out_path

    resp = requests.get(resource["url"], timeout=120)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)

    # If it's actually a zip but wasn't saved with a .zip extension
    # (declared format lied), rename it so extraction logic works.
    if zipfile.is_zipfile(out_path) and out_path.suffix.lower() != ".zip":
        fixed_path = out_path.with_suffix(out_path.suffix + ".zip")
        out_path.rename(fixed_path)
        out_path = fixed_path

    print(f"[OK] Downloaded {out_path.name}")
    return out_path


def extract_country_tabular(country: str, kind: str = "MPI and Partial Indices",
                             out_dir=None) -> pd.DataFrame:
    """
    Download (if not already present) the country's admin-1 poverty CSV
    into <out_dir>/tabular/, and return it as a pandas DataFrame.
    """
    base_dir = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
    tabular_dir = base_dir / TABULAR_SUBDIR

    resources = get_country_mpi_resources(country)
    resource = find_resource_by_kind(resources, country, kind)
    _warn_if_country_mismatch(resource, country)
    local_path = download_resource_if_missing(resource, tabular_dir, country, extension="csv")
    return pd.read_csv(local_path)


ADMIN1_TOKENS = ["adm1", "admbnda_adm1", "admin1", "adm_1", "administrative1"]
SHAPEFILE_COMPANION_EXTS = [".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx"]


def _find_admin1_shp_file(search_dir: Path) -> Path:
    """
    Recursively search an extracted boundaries folder for the admin-1
    .shp file specifically (COD-AB zips often bundle adm0/adm1/adm2 in
    one archive). Returns the path to the .shp file itself.
    """
    all_shp = list(search_dir.rglob("*.shp"))
    if not all_shp:
        raise ValueError(f"No .shp files found at all under {search_dir}.")

    for token in ADMIN1_TOKENS:
        matches = [p for p in all_shp if token in p.name.lower()]
        if matches:
            return matches[0]

    if len(all_shp) == 1:
        # Only one shapefile in the archive — assume it's the one we need,
        # but this should be verified against its attribute table (admin-1
        # boundaries typically have 8-50+ features; admin-0 has exactly 1).
        print(
            f"[WARNING] Could not identify an admin-1-specific file by name; "
            f"only one shapefile found ({all_shp[0].name}). Verify its feature "
            f"count / admin level before using it as admin-1 boundaries."
        )
        return all_shp[0]

    raise ValueError(
        f"Multiple shapefiles found but none matched admin-1 naming tokens "
        f"{ADMIN1_TOKENS}. Files found: {[p.name for p in all_shp]}. "
        f"Inspect these manually to identify the admin-1 file."
    )


def _verify_shapefile_companions(shp_path: Path) -> list:
    """Check that the .shp's required companion files exist alongside it.
    Returns a list of any missing extensions (empty list = all good)."""
    stem = shp_path.with_suffix("")
    missing = []
    for ext in (".shp", ".shx", ".dbf"):  # minimum required to open the file
        if not stem.with_suffix(ext).exists():
            missing.append(ext)
    return missing


def extract_country_shapefile(country: str, out_dir=None) -> Path:
    """
    Download (if not already present) the country's admin boundaries
    package into <out_dir>/shapefile/, extract it if it's a zip
    (detected by content, not by declared format), then locate and
    return the path to the ADMIN-1 .shp file specifically (with its
    .shx/.dbf/.prj companions alongside it in the same folder).
    """
    base_dir = Path(out_dir) if out_dir is not None else DEFAULT_OUT_DIR
    shapefile_dir = base_dir / SHAPEFILE_SUBDIR

    resources = get_country_boundary_resources(country)
    resource = find_admin1_shapefile_resource(resources, country)
    _warn_if_country_mismatch(resource, country)
    local_path = download_resource_if_missing(resource, shapefile_dir, country)

    if zipfile.is_zipfile(local_path):
        extract_dir = local_path.with_suffix("")
        if not extract_dir.exists():
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(local_path, "r") as zf:
                zf.extractall(extract_dir)
            print(f"[OK] Extracted to {extract_dir}")
        else:
            print(f"[SKIP] {extract_dir.name} already extracted, skipping.")
        search_root = extract_dir
    else:
        # Not a zip — assume the .shp (and companions) were downloaded
        # directly into shapefile_dir already.
        search_root = shapefile_dir

    admin1_shp = _find_admin1_shp_file(search_root)
    missing = _verify_shapefile_companions(admin1_shp)
    if missing:
        print(
            f"[WARNING] {admin1_shp.name} is missing required companion file(s) "
            f"{missing} in the same folder — geopandas.read_file() will fail on this."
        )

    return admin1_shp


def extract_country_data(country: str, kind: str = "MPI and Partial Indices",
                          out_dir=None) -> dict:
    """
    Full pipeline for one country: downloads both the admin-1 poverty
    table (into tabular/) and the admin-1 shapefile (into shapefile/),
    skipping anything already on disk.
    Returns {'tabular': DataFrame, 'shapefile': Path to the admin-1 .shp file}.
    """
    df = extract_country_tabular(country, kind=kind, out_dir=out_dir)
    shp_path = extract_country_shapefile(country, out_dir=out_dir)
    return {"tabular": df, "shapefile": shp_path}


def batch_extract_data(countries: list, kind: str = "MPI and Partial Indices",
                        out_dir=None) -> dict:
    """Run extract_country_data for several countries. Returns {country: result_dict}."""
    results = {}
    for country in countries:
        try:
            results[country] = extract_country_data(country, kind=kind, out_dir=out_dir)
        except Exception as exc:
            print(f"[WARN] Failed to extract data for {country}: {exc}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract admin-1 poverty tables and shapefiles from HDX for one or more countries."
    )
    parser.add_argument("countries", nargs="+",
                         help="One or more country names or ISO3 codes, e.g. Niger NER 'Burkina Faso'")
    parser.add_argument("--batch", action="store_true",
                         help="Treat all positional arguments as a batch list, even if only one is given")
    parser.add_argument("--kind", default="MPI and Partial Indices",
                         help="'MPI and Partial Indices' (snapshot) or 'MPI Trends Over Time'")
    parser.add_argument("--out_dir", default=None,
                         help="Base directory for tabular/ and shapefile/ subfolders. "
                              "Defaults to <script_folder>/poverty_data/")
    args = parser.parse_args()

    resolved_out_dir = args.out_dir if args.out_dir is not None else DEFAULT_OUT_DIR

    if args.batch or len(args.countries) > 1:
        results = batch_extract_data(args.countries, kind=args.kind, out_dir=resolved_out_dir)
        for country, result in results.items():
            print(f"\n=== {country} ({len(result['tabular'])} rows, shapefile at {result['shapefile']}) ===")
            print(result["tabular"].head())
    else:
        result = extract_country_data(args.countries[0], kind=args.kind, out_dir=resolved_out_dir)
        print(result["tabular"].head())
        print(f"\nShapefile saved at: {result['shapefile']}")
