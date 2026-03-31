"""Custom STAC reader with Zarr support for EOPF."""

import logging
import time
import warnings
from typing import Any, Dict, Sequence, Type

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

from titiler.openeo.reader import SimpleSTACReader

from ..reader import GeoZarrReader

__all__ = ["STACReader", "_reader"]

logger = logging.getLogger(__name__)


@attr.s
class STACReader(SimpleSTACReader):
    """STACReader with support of Zarr or COG."""

    def _get_reader(self, asset_info: AssetInfo) -> Type[BaseReader]:
        """Get Asset Reader."""
        if asset_type := asset_info.get("media_type", None):
            if asset_type.split(";")[0] in [
                "application/x-zarr",
                "application/vnd+zarr",
                "application/vnd.zarr",
            ]:
                return GeoZarrReader

        return self.reader

    def _get_options(
        self,
        asset: AssetWithOptions,
        metadata: pystac.Asset,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Copy from rio_tiler.io.stac._get_options."""
        method_options: dict[str, Any] = {}
        reader_options: dict[str, Any] = {}

        # Indexes
        if indexes := asset.get("indexes"):
            method_options["indexes"] = indexes
        # Expression
        if expr := asset.get("expression"):
            method_options["expression"] = expr
        # Variables
        if vars := asset.get("variables"):
            method_options["variables"] = vars
        # Sel (dimension selection)
        if vars := asset.get("sel"):
            method_options["sel"] = vars
        # Bands
        if bands := asset.get("bands"):
            stac_bands = (
                metadata.extra_fields.get("bands")
                or metadata.extra_fields.get("eo:bands")  # V1.0
            )
            if not stac_bands:
                raise ValueError(
                    "Asset does not have 'bands' metadata, unable to use 'bands' option"
                )

            # For Zarr bands = variable
            media_type = (
                metadata.media_type.split(";")[0].strip() if metadata.media_type else ""
            )
            zarr_media_types = [
                "application/x-zarr",
                "application/vnd.zarr",
                "application/vnd+zarr",
            ]
            if media_type in zarr_media_types:
                common_to_variable = {
                    b.get("eo:common_name") or b.get("common_name") or b["name"]: b[
                        "name"
                    ]
                    for b in stac_bands
                }
                method_options["variables"] = [
                    common_to_variable.get(v, v) for v in bands
                ]

            # For COG bands = indexes
            else:
                common_to_variable = {
                    b.get("eo:common_name")
                    or b.get("common_name")
                    or b.get("name")
                    or str(ix): ix
                    for ix, b in enumerate(stac_bands, 1)
                }
                band_indexes: list[int] = []
                for b in bands:
                    if idx := common_to_variable.get(b):
                        band_indexes.append(idx)
                    else:
                        raise ValueError(
                            f"Band '{b}' not found in asset metadata, unable to use 'bands' option"
                        )

                    method_options["indexes"] = band_indexes

        return reader_options, method_options

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
            - HTTPS -> S3 URI replacement
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

            # TODO: add s3 alternate in STAC Items
            uri = uri.replace(
                "https://esa-zarr-sentinel-explorer-fra.s3.de.io.cloud.ovh.net/",
                "s3://esa-zarr-sentinel-explorer-fra/",
            )

            with self.ctx(**asset_info.get("env", {})):
                with reader(uri, tms=self.tms, **reader_options) as src:
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
                allowed_exceptions=(
                    TileOutsideBounds,
                    ValueError,
                    IndexError,
                ),
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


def _reader(item: Dict[str, Any], bbox: BBox, **kwargs: Any) -> ImageData:
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

    while True:
        try:
            with STACReader(item) as src_dst:  # type: ignore
                img = src_dst.part(bbox, **kwargs)

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

                return img
        except RasterioIOError as e:
            retries += 1
            if retries >= max_retries:
                # If we've reached max retries, re-raise the exception
                raise
            # Log the error and retry after a delay
            logger.warning(
                f"RasterioIOError encountered: {str(e)}. Retrying in {retry_delay} seconds... (Attempt {retries}/{max_retries})"
            )
            time.sleep(retry_delay)
            # Increase delay for next retry (exponential backoff)
            retry_delay *= 2
