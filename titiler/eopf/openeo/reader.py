"""Custom STAC reader with Zarr support for EOPF."""

import logging
import time
import warnings
from typing import Any, Dict, Sequence, Tuple, Type, Union

import attr
from rasterio.errors import RasterioIOError
from rasterio.warp import transform_bounds
from rio_tiler.errors import (
    AssetAsBandError,
    ExpressionMixingWarning,
    InvalidAssetName,
    MissingAssets,
    TileOutsideBounds,
)
from rio_tiler.io import BaseReader
from rio_tiler.io.stac import STAC_ALTERNATE_KEY
from rio_tiler.models import ImageData
from rio_tiler.tasks import multi_arrays
from rio_tiler.types import AssetInfo, BBox, Indexes
from rio_tiler.utils import cast_to_sequence

from titiler.openeo.reader import SimpleSTACReader, _apply_cutline_mask

from ..reader import GeoZarrReader

__all__ = ["STACReader", "_reader"]

logger = logging.getLogger(__name__)


@attr.s
class STACReader(SimpleSTACReader):
    """STACReader with support of Zarr or COG."""

    def _get_reader(self, asset_info: AssetInfo) -> Tuple[Type[BaseReader], Dict]:
        """Get Asset Reader."""
        if asset_type := asset_info.get("media_type", None):
            if asset_type.split(";")[0] in [
                "application/x-zarr",
                "application/vnd+zarr",
                "application/vnd.zarr",
            ] and not asset_info["url"].startswith("vrt://"):
                return GeoZarrReader, asset_info.get("reader_options", {})

        return self.reader, asset_info.get("reader_options", {})

    def _get_asset_info(self, asset: str) -> AssetInfo:
        """Validate asset names and return asset's info.

        Args:
            asset (str): STAC asset name.

        Returns:
            AssetInfo: STAC asset info.

        """
        asset, vrt_options = self._parse_vrt_asset(asset)
        if asset not in self.assets:
            raise InvalidAssetName(
                f"'{asset}' is not valid, should be one of {self.assets}"
            )

        asset_info = self.item.assets[asset]
        extras = asset_info.extra_fields

        info = AssetInfo(
            url=asset_info.get_absolute_href() or asset_info.href,
            metadata=extras if not vrt_options else None,
        )

        if STAC_ALTERNATE_KEY and extras.get("alternate"):
            if alternate := extras["alternate"].get(STAC_ALTERNATE_KEY):
                info["url"] = alternate["href"]

        if asset_info.media_type:
            info["media_type"] = asset_info.media_type

        # https://github.com/stac-extensions/file
        if head := extras.get("file:header_size"):
            info["env"] = {"GDAL_INGESTED_BYTES_AT_OPEN": head}

        # https://github.com/stac-extensions/raster
        if extras.get("raster:bands") and not vrt_options:
            bands = extras.get("raster:bands")
            stats = [
                (b["statistics"]["minimum"], b["statistics"]["maximum"])
                for b in bands
                if {"minimum", "maximum"}.issubset(b.get("statistics", {}))
            ]
            # check that stats data are all double and make warning if not
            if (
                stats
                and all(isinstance(v, (int, float)) for stat in stats for v in stat)
                and len(stats) == len(bands)
            ):
                info["dataset_statistics"] = stats
            else:
                warnings.warn(
                    "Some statistics data in STAC are invalid, they will be ignored.",
                    UserWarning,
                    stacklevel=2,
                )

        if vrt_options:
            info["url"] = f"vrt://{info['url']}?{vrt_options}"

        return info

    def part(  # noqa: C901
        self,
        bbox: BBox,
        assets: Union[Sequence[str], str] | None = None,
        expression: str | None = None,
        asset_indexes: Dict[str, Indexes] | None = None,
        asset_as_band: bool = False,
        **kwargs: Any,
    ) -> ImageData:
        """Read and merge parts from multiple assets.

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
        assets = cast_to_sequence(assets)
        if assets and expression:
            warnings.warn(
                "Both expression and assets passed; expression will overwrite assets parameter.",
                ExpressionMixingWarning,
                stacklevel=2,
            )

        if expression:
            assets = self.parse_expression(expression, asset_as_band=asset_as_band)

        if not assets and self.default_assets:
            warnings.warn(
                f"No assets/expression passed, defaults to {self.default_assets}",
                UserWarning,
                stacklevel=2,
            )
            assets = self.default_assets

        if not assets:
            raise MissingAssets(
                "assets must be passed via `expression` or `assets` options, or via class-level `default_assets`."
            )

        asset_indexes = asset_indexes or {}

        # We fall back to `indexes` if provided
        indexes = kwargs.pop("indexes", None)

        def _asset_reader(asset_name: str, *args: Any, **kwargs: Any) -> ImageData:
            idx = asset_indexes.get(asset_name) or indexes

            # Parse Asset `{asset}|{variable}`
            variable = asset_name.split("|")[1] if "|" in asset_name else None
            asset = asset_name.split("|")[0]

            read_options = {**kwargs, "variables": [variable]} if variable else kwargs

            asset_info = self._get_asset_info(asset)
            reader, options = self._get_reader(asset_info)
            uri = asset_info["url"]

            # TODO: add s3 alternate in STAC Items
            uri = uri.replace(
                "https://esa-zarr-sentinel-explorer-fra.s3.de.io.cloud.ovh.net/",
                "s3://esa-zarr-sentinel-explorer-fra/",
            )

            with self.ctx(**asset_info.get("env", {})):
                with reader(
                    uri,
                    tms=self.tms,
                    **{**self.reader_options, **options},
                ) as src:
                    # Check if the `variable` name is a common name
                    metadata = asset_info.get("metadata", {})
                    if (bands := metadata.get("bands", {})) and (
                        variables := read_options.pop("variables", None)
                    ):
                        common_to_variable = {
                            b["eo:common_name"]
                            if "eo:common_name" in b
                            else b["name"]: b["name"]
                            for b in bands
                        }
                        read_options["variables"] = [
                            common_to_variable.get(v, v) for v in variables
                        ]

                    bounds_crs = read_options.get("bounds_crs", "epsg:4326")

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

                    data = src.part(*args, indexes=idx, **read_options)

                    self._update_statistics(
                        data,
                        indexes=idx,
                        statistics=asset_info.get("dataset_statistics"),
                    )

                    metadata = data.metadata or {}
                    if m := asset_info.get("metadata"):
                        metadata.update(m)
                    data.metadata = {asset: metadata}

                    if asset_as_band:
                        if len(data.band_names) > 1:
                            raise AssetAsBandError(
                                "Can't use `asset_as_band` for multibands asset"
                            )
                        data.band_names = [asset_name]
                    else:
                        data.band_names = [f"{asset_name}_{n}" for n in data.band_names]

                    return data

        img = multi_arrays(
            assets,
            _asset_reader,
            bbox,
            allowed_exceptions=(
                TileOutsideBounds,
                ValueError,
                IndexError,
            ),
            **kwargs,
        )
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

                # Create cutline_mask from item geometry if available
                # Handle both pystac.Item objects and dictionaries
                geometry = None
                if hasattr(item, "geometry"):
                    geometry = item.geometry
                elif isinstance(item, dict):
                    geometry = item.get("geometry")

                if geometry is not None:
                    img = _apply_cutline_mask(img, geometry, kwargs.get("dst_crs"))

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
