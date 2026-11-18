"""Custom stacApiBackend for EOPF."""

from collections.abc import Sequence

from attrs import define, field
from pystac import Collection
from pystac.extensions import datacube as dc
from rio_tiler.types import AssetType

from titiler.openeo.reader import SimpleSTACReader
from titiler.openeo.stacapi import LoadCollection as BaseLoadCollection
from titiler.openeo.stacapi import stacApiBackend as BaseBackend

from ..stac import _parse_asset
from .angles import ANGLE_BANDS, has_angle_bands
from .reader import STACReader


def extract_bands_from_asset(asset) -> list[dict]:
    """Extract band metadata from a STAC asset using various methods.

    Args:
        asset: The STAC asset object

    Returns:
        List of band dictionaries with metadata
    """
    # Method 1: STAC 1.1., from properties.bands (custom STAC extension)
    if hasattr(asset, "properties") and asset.properties.get("bands"):
        return asset.properties.get("bands", [])

    # Method 2: STAC 1.0.0, from extra_fields["eo:bands"] (EO extension)
    if getattr(asset, "extra_fields", {}).get("eo:bands"):
        return getattr(asset, "extra_fields", {}).get("eo:bands", [])

    # Method 3: STAC 1.1.0, from extra_fields.raster:bands (STAC raster extension)
    if getattr(asset, "extra_fields", {}).get("raster:bands"):
        return getattr(asset, "extra_fields", {}).get("raster:bands", [])

    # Method 4: From direct bands property
    if hasattr(asset, "bands") and asset.bands:
        return asset.bands

    return []


def get_band_names(asset_name: str, asset) -> list[str]:
    """Extract band references from a STAC asset.

    Args:
        asset_name: The name of the asset
        asset: The STAC asset object

    Returns:
        List of band references in format 'asset_name|bands=band_name' if bands exist,
        or just ['asset_name'] if no bands are defined
    """
    bands = extract_bands_from_asset(asset)

    if not bands:
        # When no bands are defined, return just the asset name
        return [asset_name]

    return [f"{asset_name}|bands={band['name']}" for band in bands if band.get("name")]


def get_all_band_names(collection: Collection) -> list[str]:  # noqa: C901
    """Get all unique band references from collection item assets.

    Some EOPF collections publish the same band several times over: once as
    its own single-band, single-resolution asset (e.g. Sentinel-2's
    ``B02_10m``, declaring one band named ``B02``), and again inside a
    multi-band composite covering the same or another resolution (``SR_10m``,
    ``SR_20m``, ``SR_60m``, and the true-colour ``TCI_10m``, none of which
    carry a rendering role in this catalogue's metadata, so a naive per-asset
    walk cannot tell them apart from real per-band data). Left unfiltered,
    that means up to four different names for one physical band
    (``B02_10m|bands=B02``, ``SR_10m|bands=B02``, ``SR_20m|bands=B02``,
    ``SR_60m|bands=B02``) -- all reading the identical pixels at whatever
    resolution their asset happens to be, which is confusing to advertise and
    doubles as an easy way to end up mixing resolutions across a request
    without noticing.

    When a band name is available from a **single-band** asset, that is
    always the preferred, and only advertised, source for it: a composite
    asset's copy of the same band is dropped. A band that is *only* ever
    published inside a composite (no single-band asset declares it) keeps
    every composite that carries it -- dropping those would make the band
    unreachable rather than just less redundantly named, which this function
    must never do.

    Returns:
        List of band references in format 'asset_name|bands=band_name' if bands exist,
        or just asset names if no bands are defined for those assets
    """
    bare_names: set[str] = set()
    # band display name -> asset names that publish it as their one declared band
    single_band_sources: dict[str, set[str]] = {}
    # band display name -> {asset_name: full "asset|bands=band" reference}
    composite_candidates: dict[str, dict[str, str]] = {}

    for asset_name, asset in collection.item_assets.items():
        roles = asset.roles or []
        # Skip non-data assets, and a "data" asset that is also flagged
        # "metadata" -- the whole underlying store packaged as one asset
        # (EOPF's `product`), which has no bands of its own to select.
        if "data" not in roles or "metadata" in roles:
            continue

        bands = extract_bands_from_asset(asset)
        if not bands:
            bare_names.add(asset_name)
            continue

        if len(bands) == 1:
            band_name = bands[0].get("name")
            if band_name:
                single_band_sources.setdefault(band_name, set()).add(asset_name)
                bare_names.add(f"{asset_name}|bands={band_name}")
            continue

        # A composite (2+ declared bands): hold each of its bands as a
        # candidate rather than adding it directly, so the dedup pass below
        # can drop it in favour of a single-band asset if one exists.
        for band in bands:
            band_name = band.get("name")
            if band_name:
                composite_candidates.setdefault(band_name, {})[asset_name] = (
                    f"{asset_name}|bands={band_name}"
                )

    all_band_names = bare_names
    for band_name, by_asset in composite_candidates.items():
        if band_name in single_band_sources:
            # A single-band asset already covers this band -- the composite's
            # copy is pure redundancy, drop it.
            continue
        # No single-band alternative: keep every composite that carries this
        # band, exactly as before this function started deduplicating.
        all_band_names.update(by_asset.values())

    # If no bands found from item_assets, try to infer from summaries for EOPF collections
    if not all_band_names and collection.summaries and collection.summaries.bands:
        for band in collection.summaries.bands:
            band_name = band.get("name", "")
            if band_name:
                # For spectral bands (b01, b02, etc.), assume they go in reflectance asset
                if band_name.startswith(("b0", "b1")) and band_name[1:].isdigit():
                    all_band_names.add(f"reflectance|bands={band_name}")
                # For other bands like AOT, WVP, SCL, use them as direct assets
                elif band_name.upper() in ["AOT", "WVP", "SCL"]:
                    all_band_names.add(band_name)
                else:
                    # Default to reflectance asset for unknown spectral bands
                    all_band_names.add(f"reflectance|bands={band_name}")

    # View and sun angle bands, read from the product's `conditions/geometry`
    # arrays (titiler/eopf/openeo/angles.py).
    if has_angle_bands(
        collection.id,
        ((asset.media_type, asset.roles) for asset in collection.item_assets.values()),
    ):
        all_band_names.update(ANGLE_BANDS)

    return sorted(all_band_names)


@define
class stacApiBackend(BaseBackend):
    """Custom stacApiBackend for EOPF Zarr collections."""

    def _fix_collection(self, collection: dict) -> None:
        self._normalize_summaries(collection)
        self.replace_bands_in_summaries_dict(collection)
        return

    def add_data_cubes_if_missing(self, collection: Collection):
        """Add datacubes extension to collection if missing."""
        if collection.ext.has("cube") is False:
            dc.DatacubeExtension.add_to(collection)

        """ Add specific dimensions and variables for EOPF Zarr """
        collection.ext.cube.apply(
            dimensions=self.getzarrdimensions(collection),
            variables=self.getzarrvariables(collection),
        )

        return collection

    def getzarrdimensions(self, collection: Collection) -> dict[str, dc.Dimension]:
        """Get datacube dimensions for EOPF Zarr collection.

        Returns standard dimensions for satellite imagery data:
        - x (longitude)
        - y (latitude)
        - time
        - bands (spectral dimension)
        """
        return {
            "x": dc.Dimension(
                properties={
                    "type": "spatial",
                    "axis": "x",
                    "description": "longitude coordinate",
                    "reference_system": {
                        "$schema": "https://proj.org/schemas/v0.4/projjson.schema.json"
                    },
                }
            ),
            "y": dc.Dimension(
                properties={
                    "type": "spatial",
                    "axis": "y",
                    "description": "latitude coordinate",
                    "reference_system": {
                        "$schema": "https://proj.org/schemas/v0.4/projjson.schema.json"
                    },
                }
            ),
            "time": dc.Dimension(
                properties={"type": "temporal", "description": "temporal coordinate"}
            ),
            "bands": dc.Dimension(
                properties={
                    "type": "bands",
                    "description": "spectral bands",
                    "values": get_all_band_names(collection),
                }
            ),
        }

    def getzarrvariables(self, collection: Collection) -> dict[str, dc.Variable]:
        """Get datacube variables from EOPF collection assets.

        Creates variables in the format expected by load_collection:
        - Variables named as "asset|bands=band" (e.g., "reflectance|bands=b04")
        - Each asset represents a Zarr group containing bands
        - Variables reference individual bands within assets
        """
        variables = {}

        # Extract variables from collection item assets
        for asset_name, asset in collection.item_assets.items():
            # Skip non-data assets (metadata, thumbnails, etc.)
            if not asset.roles or "data" not in asset.roles:
                continue

            # Get band references using helper function
            band_refs = get_band_names(asset_name, asset)
            bands = extract_bands_from_asset(asset)

            if not band_refs:
                # If no bands metadata, create a default variable for the asset
                variable_properties = {
                    "type": "data",
                    "description": f"Data from {asset_name} asset",
                    "dimensions": ["time", "y", "x", "bands"],
                    "unit": "1",
                }
                variables[asset_name] = dc.Variable(properties=variable_properties)
                continue

            # Create variables for each band reference (asset|bands=band format)
            for i, band_ref in enumerate(band_refs):
                # Parse through _parse_asset (titiler/eopf/stac.py), the one
                # place that already owns this notation, rather than
                # hand-splitting on "|" again -- that pattern silently broke
                # when the notation moved from "asset|band" to
                # "asset|bands=band" (0.8.0), same bug class fixed in
                # replace_bands_in_summaries_dict (§7.15). Falls back to the
                # bare band_ref for a reference with no "|" at all (e.g.
                # "AOT_10m"), matching the previous behaviour exactly.
                parsed_bands = _parse_asset([band_ref])[0].get("bands")
                band_name = (parsed_bands or [band_ref])[0]

                # Get corresponding band metadata
                band = bands[i] if i < len(bands) else {}

                variable_properties = {
                    "type": "data",
                    "description": band.get(
                        "description", f"{band_name} band from {asset_name}"
                    ),
                    "dimensions": ["time", "y", "x"],
                    "unit": band.get("unit", "1"),
                }

                # Add additional band metadata if available
                if "eo:center_wavelength" in band:
                    variable_properties["eo:center_wavelength"] = band[
                        "eo:center_wavelength"
                    ]
                if "eo:full_width_half_max" in band:
                    variable_properties["eo:full_width_half_max"] = band[
                        "eo:full_width_half_max"
                    ]
                if "eo:common_name" in band:
                    variable_properties["eo:common_name"] = band["eo:common_name"]

                # Use the full band reference as the variable key
                variables[band_ref] = dc.Variable(properties=variable_properties)

        return variables

    def replace_bands_in_summaries_dict(self, collection_dict: dict) -> None:
        """Replace band names in summaries dict to match cube:dimension band values."""
        if not collection_dict.get("summaries"):
            return

        # Get the band names from cube dimension
        cube_bands = collection_dict.get("cube:dimensions", {}).get("bands", {})
        cube_band_names = cube_bands.get("values", [])

        if not cube_band_names:
            return

        # Get original summaries bands
        original_bands = collection_dict.get("summaries", {}).get("bands", [])
        item_assets = collection_dict.get("item_assets", {})

        # Create new bands list matching cube dimension
        updated_bands = []
        for cube_band_name in cube_band_names:
            # `_parse_asset` is the single place that knows this format
            # (currently "asset|bands=band", e.g. "B01_20m|bands=B01" --
            # get_all_band_names is the only producer of these strings).
            # Hand-splitting on "|" here previously assumed the pre-0.8.0
            # "asset|band" shape and silently never matched, since the value
            # after the pipe is "bands=B01", not "B01" -- every qualified
            # band lost its description/eo:common_name/wavelength.
            parsed = _parse_asset([cube_band_name])[0]
            band_name = (parsed.get("bands") or [None])[0]

            if band_name:
                # Find original band properties from summaries
                original_band = None
                for band in original_bands:
                    if band.get("name") == band_name:
                        original_band = band
                        break

                if original_band:
                    # Use existing band properties but update name
                    updated_band = dict(original_band)
                    updated_band["name"] = cube_band_name
                else:
                    # Create basic band if not found in summaries
                    updated_band = {"name": cube_band_name}

                updated_bands.append(updated_band)
            elif angle_band := ANGLE_BANDS.get(cube_band_name):
                updated_bands.append(
                    {
                        "name": cube_band_name,
                        "description": angle_band.description,
                        "unit": "deg",
                    }
                )
            else:
                # This is asset-only format (e.g., "AOT_10m", "SCL_20m").
                # Description lives on the item_assets entry (its `title`,
                # occasionally `description`) -- not on the top-level
                # `assets` dict, which only ever holds collection-level
                # assets like a thumbnail and never matches a band name.
                asset = item_assets.get(cube_band_name, {})
                description = asset.get("description") or asset.get("title")
                updated_band = {
                    "name": cube_band_name,
                    "description": description or f"Data from {cube_band_name} asset",
                }

                updated_bands.append(updated_band)

        # Update the summaries in the dictionary
        collection_dict["summaries"]["bands"] = updated_bands

        return


@define
class LoadCollection(BaseLoadCollection):
    """Load Collection process implementation with Zarr support.

    Upstream `load_collection` does the read. This class only gives it the EOPF
    reader and the EOPF band notation, through the backend seam
    (sentinel-hub/titiler-openeo#462, ADR 0011):

    - `reader_cls`: `STACReader` opens each item, and sends the Zarr assets to
      `GeoZarrReader`. The same class is used for the dimension estimate.
    - `_bands_to_assets`: a band in `<asset>|bands=<band>` form becomes the
      asset dict that `STACReader` reads.

    NOTE: `stac_api` is inherited from `BaseLoadCollection` rather than
    redeclared here. attrs orders an overridden field at the *subclass's*
    declaration position, so redeclaring `stac_api` (mandatory, no default)
    after `signer_key` (has a default) makes attrs refuse to build the class.
    """

    reader_cls: type[SimpleSTACReader] | None = field(default=STACReader)

    def _bands_to_assets(self, bands: list[str] | None) -> Sequence[AssetType] | None:
        """Parse `<asset>|bands=<band>` (and the other asset options): one entry per band."""
        return _parse_asset(bands) if bands else bands
