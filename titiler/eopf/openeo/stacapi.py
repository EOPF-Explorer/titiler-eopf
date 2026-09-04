"""Custom stacApiBackend for EOPF."""

from typing import Optional

from attrs import define
from openeo_pg_parser_networkx.pg_schema import BoundingBox, TemporalInterval
from pystac import Collection, Item
from pystac.extensions import datacube as dc
from rasterio.warp import transform_bounds
from rio_tiler.errors import EmptyMosaicError, TileOutsideBounds
from rio_tiler.mosaic.methods import PixelSelectionMethod
from rio_tiler.mosaic.reader import mosaic_reader

from titiler.openeo.errors import (
    ItemsLimitExceeded,
    NoDataAvailable,
    OutputLimitExceeded,
)
from titiler.openeo.processes.implementations.data_model import RasterStack
from titiler.openeo.reader import _estimate_output_dimensions
from titiler.openeo.settings import ProcessingSettings
from titiler.openeo.stacapi import LoadCollection as BaseLoadCollection
from titiler.openeo.stacapi import stacApiBackend as BaseBackend

from ..stac import _parse_asset
from .reader import _reader

processing_settings = ProcessingSettings()


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
        - Variables named as "asset|band" (e.g., "reflectance|b04")
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

            # Create variables for each band reference (asset|band format)
            for i, band_ref in enumerate(band_refs):
                # Parse the asset|band format to get individual band info
                _, band_name = (
                    band_ref.split("|") if "|" in band_ref else (asset_name, band_ref)
                )

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


def _make_mosaic_task(
    date_items: list[Item],
    bbox: list[float],
    bounds_crs,
    output_crs,
    bands: list[str] | None,
    width: int | None,
    height: int | None,
    tile_buffer: float | None,
):
    """Create a closure that loads data for a date group."""

    # parse bands to assets with options format expected by _reader
    assets = _parse_asset(bands) if bands else None

    def task():
        mosaic_kwargs = {
            "threads": 0,
            "bounds_crs": bounds_crs,
            "assets": assets,
            "dst_crs": output_crs,
            "width": int(width) if width else width,
            "height": int(height) if height else height,
            "buffer": float(tile_buffer) if tile_buffer is not None else tile_buffer,
            "pixel_selection": PixelSelectionMethod["first"].value(),
            # No explicit allowed_exceptions: mosaic_reader's own default is
            # already (TileOutsideBounds,) (rio-tiler 9.4.2). The
            # EmptyMosaicError -> TileOutsideBounds conversion below is the
            # real content here.
        }

        try:
            img, _ = mosaic_reader(
                date_items,
                _reader,
                bbox,
                **mosaic_kwargs,
            )
            return img
        except EmptyMosaicError as e:
            # All items failed to return data for this bbox/date.
            # Re-raise as TileOutsideBounds so RasterStack can handle it gracefully.
            raise TileOutsideBounds(
                f"No valid data found in bbox {bbox} for date group"
            ) from e

    return task


def _group_items_by_date(items: list[Item]) -> dict[str, list[Item]]:
    """Group items by their datetime."""
    items_by_date: dict[str, list[Item]] = {}
    for item in items:
        date = item.datetime.isoformat()
        if date not in items_by_date:
            items_by_date[date] = []
        items_by_date[date].append(item)
    return items_by_date


def _build_tasks(
    items_by_date: dict[str, list[Item]],
    bbox: list[float],
    bounds_crs,
    output_crs,
    bands: list[str] | None,
    width: int | None,
    height: int | None,
    tile_buffer: float | None,
) -> list:
    """Build task list for RasterStack from grouped items."""
    tasks = []
    for date, date_items in items_by_date.items():
        task_fn = _make_mosaic_task(
            date_items,
            bbox,
            bounds_crs,
            output_crs,
            bands,
            width,
            height,
            tile_buffer,
        )
        geometries = [item.geometry for item in date_items if item.geometry is not None]
        tasks.append(
            (
                task_fn,
                {
                    "id": date,
                    "datetime": date_items[0].datetime if date_items else None,
                    "geometry": geometries if geometries else None,
                    # The source items behind this date group's mosaic. Carried
                    # so processes that need per-item STAC metadata (asset
                    # hrefs, properties) can reach it -- notably
                    # sar_backscatter, whose calibration LUTs and GCP geometry
                    # are per source item. Retrieve via
                    # RasterStack.get_source_items, never by reaching into task
                    # metadata directly. Matches upstream's own load_collection.
                    "items": date_items,
                },
            )
        )
    return tasks


@define
class LoadCollection(BaseLoadCollection):
    """Load Collection process implementation with Zarr support.

    This class inherits from the base LoadCollection and uses our custom
    _reader that supports both COG and Zarr assets.

    NOTE: `stac_api` is inherited from `BaseLoadCollection` rather than
    redeclared here. Upstream 0.18.0 added `signer_key: Optional[str] =
    field(default=None)` to the base class; attrs orders an overridden field
    at the *subclass's* declaration position, so redeclaring `stac_api` here
    (mandatory, no default) put it after `signer_key` (has a default) and
    attrs refused to build the class ("No mandatory attributes allowed after
    an attribute with a default value"). EOPF's `stacApiBackend` subclasses
    the upstream one, so passing an instance of it still satisfies the
    inherited (upstream-typed) `stac_api` field.
    """

    def _validate_limits(
        self, items: list[Item], width: int | None, height: int | None
    ) -> None:
        """Validate item count and pixel limits."""
        if len(items) > processing_settings.max_items:
            raise ItemsLimitExceeded(len(items), processing_settings.max_items)

        if width and height:
            width_int = int(width)
            height_int = int(height)
            pixel_count = width_int * height_int * len(items)
            if pixel_count > processing_settings.max_pixels:
                raise OutputLimitExceeded(
                    width_int,
                    height_int,
                    processing_settings.max_pixels,
                    items_count=len(items),
                )

    def load_collection(
        self,
        id: str,
        # NOTE: spatial_extent/temporal_extent stay `Optional[X]` (old-style),
        # not `X | None`, deliberately. titiler.openeo's process-graph
        # ParameterReference resolution (core._is_optional_type) only
        # recognises `typing.Union` -- `typing.get_origin(X | None)` returns
        # `types.UnionType`, a different object, so `X | None` silently skips
        # the BoundingBox/TemporalInterval coercion and a raw dict/list from a
        # UDP parameter default reaches this function unconverted (then fails
        # deeper, e.g. `temporal_extent.start` on a plain list in
        # LoadCollection._get_items). Confirmed this affects both parameters
        # identically; upstream's own load_collection dodges it only because
        # it happens to use `Optional[X]` already. See EOPF-Explorer/titiler-eopf
        # migration notes and the upstream fix this should eventually make
        # unnecessary.
        spatial_extent: Optional[BoundingBox] = None,
        temporal_extent: Optional[TemporalInterval] = None,
        bands: list[str] | None = None,
        properties: dict | None = None,
        # private arguments
        width: int | None = 1024,
        height: int | None = 1024,
        tile_buffer: float | None = None,
        named_parameters: dict | None = None,
        target_crs: int | str | None = None,
    ) -> RasterStack:
        """Load Collection with Zarr support.

        Args:
            id: Collection ID
            spatial_extent: Bounding box for the output (coordinates in its own CRS)
            temporal_extent: Temporal filter
            bands: Band names to load
            properties: Metadata filters
            width: Output width in pixels
            height: Output height in pixels
            tile_buffer: Tile overlap buffer
            named_parameters: Named parameters for process graph evaluation
            target_crs: Target CRS for output. If None, uses native CRS from source images.
        """
        # Retrieve up to one item beyond the configured processing limit so the
        # guard below (_validate_limits) can detect genuine overflow. Without an
        # explicit max_items, upstream's get_items silently caps at the first
        # page (limit=100, newest-first), which drops whole months/years from
        # wide temporal extents instead of raising ItemsLimitExceeded. Matches
        # upstream's own load_collection (titiler-openeo#302).
        items = self._get_items(
            id,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            properties=properties,
            named_parameters=named_parameters,
            limit=100,
            max_items=processing_settings.max_items + 1,
        )
        if not items:
            raise NoDataAvailable("There is no data available for the given extents.")

        self._validate_limits(items, width, height)

        # If bands parameter is missing, use the first asset from the first item
        if bands is None and items and items[0].assets:
            bands = list(items[0].assets.keys())[:1]

        # Estimate dimensions based on items and spatial extent
        dimensions = _estimate_output_dimensions(
            items, spatial_extent, bands, width, height, target_crs=target_crs
        )

        width = dimensions["width"]
        height = dimensions["height"]
        bbox = dimensions["bbox"]
        bounds_crs = dimensions["bounds_crs"]
        output_crs = dimensions["crs"]

        # Reproject bbox from bounds_crs to output_crs for the RasterStack bounds
        output_bbox = (
            list(transform_bounds(bounds_crs, output_crs, *bbox, densify_pts=21))
            if bounds_crs != output_crs
            else bbox
        )

        items_by_date = _group_items_by_date(items)
        tasks = _build_tasks(
            items_by_date,
            bbox,
            bounds_crs,
            output_crs,
            bands,
            width,
            height,
            tile_buffer,
        )

        return RasterStack(
            tasks=tasks,
            timestamp_fn=lambda asset: asset["datetime"],
            width=int(width) if width else None,
            height=int(height) if height else None,
            bounds=output_bbox,
            dst_crs=output_crs,
            band_names=bands if bands else [],
        )
