"""Custom STAC reader with Zarr support for EOPF."""

import logging
import time
import warnings
from collections.abc import Sequence
from typing import Any

import attr
import pystac
from rasterio.errors import RasterioIOError
from rasterio.warp import transform_bounds
from rio_tiler.errors import AssetAsBandError, MissingAssets, TileOutsideBounds
from rio_tiler.io import BaseReader
from rio_tiler.models import ImageData
from rio_tiler.tasks import multi_arrays
from rio_tiler.types import AssetInfo, AssetType, AssetWithOptions, BBox
from rio_tiler.utils import cast_to_sequence, inherit_rasterio_env

from titiler.openeo.reader import SimpleSTACReader, _inherit_derived_band_masks

from ..reader import GeoZarrReader
from ..stac import _resolve_zarr_bands

__all__ = ["STACReader", "_reader"]

logger = logging.getLogger(__name__)


@attr.s
class STACReader(SimpleSTACReader):
    """STACReader with support of Zarr or COG."""

    def _get_reader(self, asset_info: AssetInfo) -> type[BaseReader]:
        """Get Asset Reader."""
        if asset_type := asset_info.get("media_type", None):
            if asset_type.split(";")[0] in [
                "application/x-zarr",
                "application/vnd+zarr",
                "application/vnd.zarr",
            ]:
                return GeoZarrReader

        # Not Zarr: defer to upstream, which checks `_derived_bands` before
        # falling back to `self.reader`. Returning `self.reader` directly (as
        # this override used to) skipped that check, so a band-source-derived
        # band (SAR noise/calibration LUTs, S2 view/sun angles) would be read
        # with the plain OpenEOReader instead of its own resolved reader.
        return super()._get_reader(asset_info)

    def _get_options(
        self,
        asset: AssetWithOptions,
        metadata: pystac.Asset,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """EOPF: Zarr `bands` -> `variables` mapping, plus `variables`/`sel`
        pass-through, on top of upstream's `_get_options`.

        The non-Zarr path (`indexes`/`expression`, and `bands` -> `indexes`
        for COG-like assets) is delegated to `super()` rather than duplicated:
        it is now byte-identical to what this used to copy, since
        titiler-openeo#378 fixed the one thing that used to differ (an
        unreachable positional-index fallback -- an int key looked up against
        string band values).
        """
        method_options: dict[str, Any] = {}
        reader_options: dict[str, Any] = {}

        # Variables (Zarr-only; upstream has no equivalent option)
        if vars := asset.get("variables"):
            method_options["variables"] = vars
        # Sel (dimension selection; Zarr-only; upstream has no equivalent option)
        if vars := asset.get("sel"):
            method_options["sel"] = vars

        media_type = (
            metadata.media_type.split(";")[0].strip() if metadata.media_type else ""
        )
        is_zarr = media_type in (
            "application/x-zarr",
            "application/vnd.zarr",
            "application/vnd+zarr",
        )

        if is_zarr and (bands := asset.get("bands")):
            stac_bands = (
                metadata.extra_fields.get("bands")
                or metadata.extra_fields.get("eo:bands")  # V1.0
            )
            if not stac_bands:
                raise ValueError(
                    "Asset does not have 'bands' metadata, unable to use 'bands' option"
                )

            method_options["variables"] = _resolve_zarr_bands(bands, stac_bands)
            return reader_options, method_options

        # Not Zarr, or Zarr with no `bands` requested: everything left
        # (indexes/expression, and COG-style bands -> indexes) is upstream's
        # unmodified logic.
        up_reader_options, up_method_options = super()._get_options(asset, metadata)
        return (
            {**reader_options, **up_reader_options},
            {**method_options, **up_method_options},
        )

    def part(  # noqa: C901
        self,
        bbox: BBox,
        assets: Sequence[AssetType] | AssetType | None = None,
        expression: str | None = None,
        asset_as_band: bool = False,
        **kwargs: Any,
    ) -> ImageData:
        """Custom `part` method.

        NOTE:
            - BBOX check before reading

        Custom PART method for multi-asset reading.
        We customize the `part()._reader` method to parse the asset
        (which can be in form of `{asset}|{variable}` for Zarr)
        then pass the variable to the `GeoZarrReader`.

        Args:
            bbox (tuple): Output bounds (left, bottom, right, top) in target crs.
            assets (sequence of str or str, optional): assets to fetch info from.
            expression (str, optional): rio-tiler expression for the asset list.
            asset_indexes (dict, optional): Band indexes for each asset.
            kwargs (optional): Options to forward to the `self.reader.part` method.

        Returns:
            rio_tiler.models.ImageData: ImageData instance with data, mask and tile spatial info.

        """
        if kwargs.pop("asset_indexes", None):
            warnings.warn(
                "`asset_indexes` parameter is deprecated in `tile` method and will be ignored.",
                DeprecationWarning,
                stacklevel=2,
            )

        assets = cast_to_sequence(assets)
        if not assets and self.default_assets:
            warnings.warn(
                f"No assets/expression passed, defaults to {self.default_assets}",
                UserWarning,
                stacklevel=2,
            )
            assets = self.default_assets

        if not assets:
            raise MissingAssets(
                "No Asset defined by `assets` option or class-level `default_assets`."
            )

        @inherit_rasterio_env
        def _reader(asset: AssetType, *args: Any, **kwargs: Any) -> ImageData:
            asset_info = self._get_asset_info(asset)
            asset_name = asset_info["name"]
            reader = self._get_reader(asset_info)
            reader_options = {**self.reader_options, **asset_info["reader_options"]}
            method_options = {**asset_info["method_options"], **kwargs}

            uri = asset_info["url"]

            with self.ctx(**asset_info.get("env", {})):
                with reader(input=uri, tms=self.tms, **reader_options) as src:
                    bounds_crs = method_options.get("bounds_crs", "epsg:4326")

                    transformed_bbox = bbox
                    # Transform bbox to source CRS if needed
                    if bounds_crs != src.crs:
                        transformed_bbox = transform_bounds(bounds_crs, src.crs, *bbox)

                    # Check if bbox intersects with source bounds
                    if not (
                        transformed_bbox[2] > src.bounds[0]
                        and transformed_bbox[0] < src.bounds[2]
                        and transformed_bbox[3] > src.bounds[1]
                        and transformed_bbox[1] < src.bounds[3]
                    ):
                        raise TileOutsideBounds(
                            f"No data found in bounds {bbox} for asset {asset_name}"
                        )

                    data = src.part(*args, **method_options)

                    self._update_statistics(
                        data,
                        indexes=method_options.get("indexes"),
                        statistics=asset_info.get("dataset_statistics"),
                    )

                    metadata = data.metadata or {}
                    if m := asset_info.get("metadata"):
                        metadata.update(m)
                    data.metadata = {asset_name: metadata}

                    data.band_descriptions = [
                        f"{asset_name}_{n}" for n in data.band_descriptions
                    ]
                    if asset_as_band:
                        if len(data.band_names) > 1:
                            raise AssetAsBandError(
                                "Can't use `asset_as_band` for multibands asset"
                            )
                        data.band_descriptions = [asset_name]

                    return data

        try:
            img = multi_arrays(
                assets,
                _reader,
                bbox,
                # Only TileOutsideBounds -- matches mosaic_reader's own default one
                # level up. A wider tuple here used to swallow real option
                # errors (e.g. an unknown band name from _get_options)
                # silently: filter_tasks logs allowed exceptions at INFO and
                # drops the asset, so the ValueError naming the bad band
                # never reached the caller -- with every asset then dropped,
                # this degraded into a generic "no valid data" failure.
                allowed_exceptions=(TileOutsideBounds,),
                **kwargs,
            )
        except ValueError as e:
            # multi_arrays raises ValueError when all assets fail and it tries
            # to create an ImageData from an empty list. Convert to TileOutsideBounds
            # so the caller (mosaic_reader) can handle it gracefully.
            logger.warning(
                f"All assets failed to load for bbox {bbox}: {e!s}. "
                "Raising TileOutsideBounds to allow mosaicking to continue."
            )
            raise TileOutsideBounds(
                f"No valid data found in bounds {bbox} for any asset"
            ) from e

        img.band_names = [f"b{ix + 1}" for ix in range(img.count)]
        if expression:
            return img.apply_expression(expression)

        return img


def _reader(item: dict[str, Any], bbox: BBox, **kwargs: Any) -> ImageData:
    """Read a STAC item and return an ImageData object.

    This is the Zarr-aware reader function that uses STACReader
    which detects Zarr media types and uses GeoZarrReader.

    Args:
        item: STAC item dictionary or pystac.Item
        bbox: Bounding box to read
        **kwargs: Additional keyword arguments to pass to the reader

    Returns:
        ImageData object
    """
    max_retries = 10
    retry_delay = 1.0  # seconds
    retries = 0

    # Extract item info for logging
    item_id = (
        item.get("id", "unknown")
        if isinstance(item, dict)
        else getattr(item, "id", "unknown")
    )
    item_datetime = (
        item.get("properties", {}).get("datetime", "unknown")
        if isinstance(item, dict)
        else getattr(item, "datetime", None) or "unknown"
    )

    logger.debug(f"Loading STAC item: {item_id} (datetime: {item_datetime})")

    while True:
        try:
            with STACReader(item) as src_dst:  # type: ignore
                img = src_dst.part(bbox, **kwargs)

                requested = kwargs.get("assets")
                if requested:
                    # getattr, not a direct attribute access: some tests
                    # substitute a minimal stand-in for STACReader that does
                    # not carry this (SimpleSTACReader-internal) attribute --
                    # treat that the same as "no derived bands".
                    img = _inherit_derived_band_masks(
                        img, getattr(src_dst, "_derived_bands", {}), requested
                    )

                # IMPORTANT: We intentionally do NOT set cutline_mask on individual tiles.
                #
                # Background: rio-tiler's mosaic_reader uses cutline_mask from the FIRST
                # image to determine when mosaicking is complete (via FirstMethod.is_done).
                # The is_done check only verifies that pixels INSIDE the first tile's
                # footprint geometry are filled, ignoring pixels outside that footprint.
                #
                # Problem: For multi-tile mosaics where each tile covers only a portion
                # of the target bbox, this causes early termination after the first tile.
                # Example: If tile 1 covers 7% of the bbox and has valid data for that 7%,
                # is_done returns True even though 93% of the mosaic is still empty.
                #
                # Solution: By not setting cutline_mask, is_done falls back to checking
                # if ALL pixels in the mosaic are filled (not numpy.ma.is_masked(mosaic)).
                # This allows mosaicking to continue until all tiles are processed or
                # all pixels have valid data.
                #
                # The nodata mask (created from the nodata value in STAC metadata)
                # correctly tracks which pixels have valid data vs nodata, and this
                # mask is properly combined during mosaicking via FirstMethod.feed().

                logger.debug(
                    f"  Loaded {item_id}: {img.width}x{img.height}, "
                    f"bands={img.count}, dtype={img.data.dtype}"
                )

                return img
        except RasterioIOError as e:
            retries += 1
            if retries >= max_retries:
                # If we've reached max retries, re-raise the exception
                logger.error(
                    f"Failed to load {item_id} after {max_retries} retries: {e}"
                )
                raise
            # Log the error and retry after a delay
            logger.warning(
                f"RasterioIOError loading {item_id}: {str(e)}. "
                f"Retrying in {retry_delay}s... (Attempt {retries}/{max_retries})"
            )
            time.sleep(retry_delay)
            # Increase delay for next retry (exponential backoff)
            retry_delay *= 2
