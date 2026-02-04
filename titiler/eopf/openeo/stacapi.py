"""Custom stacApiBackend for EOPF."""

from typing import Dict, List, Optional, Union

from attrs import define, field
from cachetools import TTLCache, cached  # type: ignore
from cachetools.keys import hashkey  # type: ignore
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
from titiler.openeo.stacapi import CacheSettings
from titiler.openeo.stacapi import LoadCollection as BaseLoadCollection
from titiler.openeo.stacapi import stacApiBackend as BaseBackend

from .reader import _reader

cache_config = CacheSettings()
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
        List of band references in format 'asset|band_name' if bands exist,
        or just ['asset_name'] if no bands are defined
    """
    bands = extract_bands_from_asset(asset)

    if not bands:
        # When no bands are defined, return just the asset name
        return [asset_name]

    return [
        f"{asset_name}|{band.get('name', '')}" for band in bands if band.get("name")
    ]


def get_all_band_names(collection: Collection) -> list[str]:
    """Get all unique band references from collection item assets.

    Returns:
        List of band references in format 'asset|band_name' if bands exist,
        or just asset names if no bands are defined for those assets
    """
    all_band_names = set()

    # First try to get from item_assets
    for asset_name, asset in collection.item_assets.items():
        # Skip non-data assets
        if not asset.roles or "data" not in asset.roles:
            continue

        band_refs = get_band_names(asset_name, asset)
        all_band_names.update(band_refs)

    # If no bands found from item_assets, try to infer from summaries for EOPF collections
    if not all_band_names and collection.summaries and collection.summaries.bands:
        for band in collection.summaries.bands:
            band_name = band.get("name", "")
            if band_name:
                # For spectral bands (b01, b02, etc.), assume they go in reflectance asset
                if band_name.startswith(("b0", "b1")) and band_name[1:].isdigit():
                    all_band_names.add(f"reflectance|{band_name}")
                # For other bands like AOT, WVP, SCL, use them as direct assets
                elif band_name.upper() in ["AOT", "WVP", "SCL"]:
                    all_band_names.add(band_name)
                else:
                    # Default to reflectance asset for unknown spectral bands
                    all_band_names.add(f"reflectance|{band_name}")

    return sorted(all_band_names)


@define
class stacApiBackend(BaseBackend):
    """Custom stacApiBackend for EOPF Zarr collections."""

    @cached(  # type: ignore
        TTLCache(maxsize=cache_config.maxsize, ttl=cache_config.ttl),
        key=lambda self, **kwargs: hashkey(self.url, **kwargs),
    )
    def get_collections(self, **kwargs) -> List[Dict]:
        """Return List of STAC Collections."""
        collections = []
        for collection in self.client.get_collections():
            collection = self.add_version_if_missing(collection)
            collection = self.add_data_cubes_if_missing(collection)

            # Convert to dict and fix summaries bands
            col_dict = collection.to_dict()
            col_dict = self.replace_bands_in_summaries_dict(col_dict)
            collections.append(col_dict)
        return collections

    @cached(  # type: ignore
        TTLCache(maxsize=cache_config.maxsize, ttl=cache_config.ttl),
        key=lambda self, collection_id, **kwargs: hashkey(
            self.url, collection_id, **kwargs
        ),
    )
    def get_collection(self, collection_id: str, **kwargs) -> Dict:
        """Return STAC Collection"""
        col = self.client.get_collection(collection_id)
        col = self.add_version_if_missing(col)
        col = self.add_data_cubes_if_missing(col)

        # Convert to dict first, then modify summaries
        col_dict = col.to_dict()
        col_dict = self.replace_bands_in_summaries_dict(col_dict)
        return col_dict

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

    def getzarrdimensions(self, collection: Collection) -> Dict[str, dc.Dimension]:
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

    def getzarrvariables(self, collection: Collection) -> Dict[str, dc.Variable]:
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

    def replace_bands_in_summaries(self, collection: Collection):
        """Replace band names in summaries to match cube:dimension band values.

        The bands in summaries should be the same list as in cube:dimension band.
        For asset-only bands, use the asset description.
        """
        if not collection.summaries:
            return collection

        # Get the band names from cube dimension (this is our target list)
        # Use the cube dimension values if they exist, otherwise fall back to get_all_band_names
        if (
            hasattr(collection, "ext")
            and collection.ext.has("cube")
            and collection.ext.cube.dimensions.get("bands")
            and collection.ext.cube.dimensions.get("bands").properties.get("values")
        ):
            cube_band_names = collection.ext.cube.dimensions.get(
                "bands"
            ).properties.get("values")
        else:
            cube_band_names = get_all_band_names(collection)

        # Create new bands list matching cube dimension
        updated_bands = []
        for cube_band_name in cube_band_names:
            if "|" in cube_band_name:
                # This is asset|band format (e.g., "reflectance|b01")
                asset_name, band_name = cube_band_name.split("|", 1)

                # Find original band properties from summaries
                original_band = None
                if (
                    hasattr(collection.summaries, "bands")
                    and collection.summaries.bands
                ):
                    for band in collection.summaries.bands:
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
                # This is asset-only format (e.g., "AOT", "SCL", "WVP")
                # Use the asset description
                asset = (
                    collection.item_assets.get(cube_band_name)
                    if collection.item_assets
                    else None
                )
                if asset and asset.description:
                    updated_band = {
                        "name": cube_band_name,
                        "description": asset.description,
                    }
                else:
                    # Fallback if asset not found or no description
                    updated_band = {
                        "name": cube_band_name,
                        "description": f"Data from {cube_band_name} asset",
                    }

                updated_bands.append(updated_band)

        # Set the bands in summaries (though this won't be used)
        collection.summaries.bands = updated_bands

        return collection

    def replace_bands_in_summaries_dict(self, collection_dict: Dict) -> Dict:
        """Replace band names in summaries dict to match cube:dimension band values."""
        if not collection_dict.get("summaries"):
            return collection_dict

        # Get the band names from cube dimension
        cube_bands = collection_dict.get("cube:dimensions", {}).get("bands", {})
        cube_band_names = cube_bands.get("values", [])

        if not cube_band_names:
            return collection_dict

        # Get original summaries bands
        original_bands = collection_dict.get("summaries", {}).get("bands", [])

        # Create new bands list matching cube dimension
        updated_bands = []
        for cube_band_name in cube_band_names:
            if "|" in cube_band_name:
                # This is asset|band format (e.g., "reflectance|b01")
                asset_name, band_name = cube_band_name.split("|", 1)

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
                # This is asset-only format (e.g., "AOT", "SCL", "WVP")
                # Use the asset description if available
                assets = collection_dict.get("assets", {})
                asset = assets.get(cube_band_name, {})
                if asset.get("description"):
                    updated_band = {
                        "name": cube_band_name,
                        "description": asset["description"],
                    }
                else:
                    # Fallback if asset not found or no description
                    updated_band = {
                        "name": cube_band_name,
                        "description": f"Data from {cube_band_name} asset",
                    }

                updated_bands.append(updated_band)

        # Update the summaries in the dictionary
        collection_dict["summaries"]["bands"] = updated_bands

        return collection_dict


def _make_mosaic_task(
    date_items: list[Item],
    bbox: list[float],
    bounds_crs,
    output_crs,
    bands: Optional[list[str]],
    width: Optional[int],
    height: Optional[int],
    tile_buffer: Optional[float],
):
    """Create a closure that loads data for a date group."""

    def task():
        mosaic_kwargs = {
            "threads": 0,
            "bounds_crs": bounds_crs,
            "assets": bands,
            "dst_crs": output_crs,
            "width": int(width) if width else width,
            "height": int(height) if height else height,
            "buffer": float(tile_buffer) if tile_buffer is not None else tile_buffer,
            "pixel_selection": PixelSelectionMethod["first"].value(),
            "allowed_exceptions": (TileOutsideBounds,),
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
    bands: Optional[list[str]],
    width: Optional[int],
    height: Optional[int],
    tile_buffer: Optional[float],
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
                },
            )
        )
    return tasks


@define
class LoadCollection(BaseLoadCollection):
    """Load Collection process implementation with Zarr support.

    This class inherits from the base LoadCollection and uses our custom
    _reader that supports both COG and Zarr assets.
    """

    stac_api: stacApiBackend = field()

    def _validate_limits(
        self, items: list[Item], width: Optional[int], height: Optional[int]
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
        spatial_extent: Optional[BoundingBox] = None,
        temporal_extent: Optional[TemporalInterval] = None,
        bands: Optional[list[str]] = None,
        properties: Optional[dict] = None,
        # private arguments
        width: Optional[int] = 1024,
        height: Optional[int] = 1024,
        tile_buffer: Optional[float] = None,
        named_parameters: Optional[dict] = None,
        target_crs: Optional[Union[int, str]] = None,
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
        items = self._get_items(
            id,
            spatial_extent=spatial_extent,
            temporal_extent=temporal_extent,
            properties=properties,
            named_parameters=named_parameters,
            limit=100,
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
