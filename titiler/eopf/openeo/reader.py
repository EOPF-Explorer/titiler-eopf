"""Custom STAC reader with Zarr support for EOPF."""

import logging
import warnings
from collections.abc import Sequence
from typing import Any

import attr
import pystac
from rasterio.warp import transform_bounds
from rio_tiler.errors import (
    AssetAsBandError,
    InvalidAssetName,
    MissingAssets,
    TileOutsideBounds,
)
from rio_tiler.io import BaseReader
from rio_tiler.models import ImageData
from rio_tiler.tasks import multi_arrays
from rio_tiler.types import AssetInfo, AssetType, AssetWithOptions, BBox
from rio_tiler.utils import cast_to_sequence, inherit_rasterio_env

from titiler.openeo import reader as upstream_reader
from titiler.openeo.bandsources import ResolvedBand
from titiler.openeo.reader import OpenEOReader, SimpleSTACReader, _resolve_asset_href

from ..reader import GeoZarrReader
from ..stac import _resolve_zarr_bands
from .angles import ANGLE_BANDS, angle_source_asset, product_root

__all__ = ["STACReader"]

logger = logging.getLogger(__name__)

# `GeoZarrReader` returns decoded values (xarray CF decoding and the GeoZarr
# ScaleOffset codec). The upstream `_reader` would apply the STAC
# `raster:scale`/`raster:offset` of the same asset a second time, and the EOPF
# items publish them (e.g. `reflectance` 0.0001). So scale/offset is off unless
# the deployment sets TITILER_OPENEO_PROCESSING_APPLY_SCALE_OFFSET. Re-enable
# when EOPF-Explorer/data-pipeline#384 lands (docs/openeo-migration.md §6).
if "apply_scale_offset" not in upstream_reader.processing_settings.model_fields_set:
    upstream_reader.processing_settings.apply_scale_offset = False


def _numeric_nodata(value: Any) -> Any:
    """A STAC `nodata` value as a number.

    JSON has no NaN or infinity, so the STAC raster extension and the
    common `bands` metadata give them as the strings "nan", "inf" and
    "-inf" (e.g. the Sentinel-1 RTC items). The readers need a number:
    rasterio's reprojection checks the value with `numpy.isnan`, which
    raises a TypeError for a string. Returns None for a string that is
    not a number.
    """
    if not isinstance(value, str):
        return value
    try:
        return float(value)
    except ValueError:
        return None


@attr.s
class STACReader(SimpleSTACReader):
    """STACReader with support of Zarr or COG.

    For an EOPF Sentinel-2 item, also gives the view and sun angle bands from
    the product's `conditions/geometry` arrays (see `angles.py`).
    """

    def __attrs_post_init__(self) -> None:
        """Upstream setup, then the EOPF angle bands."""
        super().__attrs_post_init__()
        self._add_angle_bands()

    def _add_angle_bands(self) -> None:
        """Add the angle bands to `_derived_bands`.

        Upstream gives these bands only from a `granule_metadata` XML asset,
        which EOPF items do not have. A band that upstream already gives for
        this item keeps the upstream reader.
        """
        collection_id = self.input.collection_id or ""
        asset_key = angle_source_asset(collection_id, self.input.assets)
        if asset_key is None:
            return
        for name, band in ANGLE_BANDS.items():
            self._derived_bands.setdefault(
                name,
                ResolvedBand(
                    asset_key=asset_key,
                    sibling_key=None,
                    quantity=band.quantity,
                    reader=band.reader,
                ),
            )

    def _get_derived_asset_info(self, asset_name: str) -> AssetInfo:
        """Asset info of an angle band: the product root and the band options."""
        band = ANGLE_BANDS.get(asset_name)
        resolved = self._derived_bands[asset_name]
        if band is None or resolved.reader is not band.reader:
            return super()._get_derived_asset_info(asset_name)

        # The href as the reflectance read resolves it (absolute href, and the
        # `STAC_ALTERNATE_KEY` alternate), as upstream does for its own
        # derived bands. The signer applies to the product root, after the
        # cut, so that the cut does not remove a signature.
        asset = self.input.assets[resolved.asset_key]
        root = product_root(_resolve_asset_href(asset))
        if root is None:
            raise InvalidAssetName(
                f"Band '{asset_name}': the href of asset '{resolved.asset_key}' "
                "is not in a Zarr product"
            )
        if self.signer is not None:
            root = self.signer(root)
        return AssetInfo(
            url=root,
            name=asset_name,
            media_type=asset.media_type,
            reader_options={"quantity": band.quantity, "band": band.band},
            method_options={},
        )

    def _get_reader(self, asset_info: AssetInfo) -> type[BaseReader]:
        """Get Asset Reader."""
        # A derived band can have a Zarr media type (the angle bands do):
        # its own reader comes first.
        if asset_info["name"] in self._derived_bands:
            return super()._get_reader(asset_info)

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

    def _get_asset_info(self, asset: AssetType) -> AssetInfo:
        """Upstream asset info, without the options this asset's reader rejects.

        Upstream (titiler-openeo#464) adds `fallback_nodata` to
        `reader_options` when the class-level `self.reader` is an
        `OpenEOReader`. But `_get_reader` selects the reader for each asset,
        and `GeoZarrReader` does not accept that option. The value comes from
        Sentinel-2 SAFE product metadata (`MTD_MSIL2A.xml`), which does not
        apply to a GeoZarr asset, so remove it for each other reader.

        Upstream also copies the STAC `nodata` without conversion, so a
        "nan"/"inf"/"-inf" string reaches the reader. Convert it to a float
        (`_numeric_nodata`), or remove it when it is not a number.
        """
        info = super()._get_asset_info(asset)
        if "fallback_nodata" in info["reader_options"] and not issubclass(
            self._get_reader(info), OpenEOReader
        ):
            info["reader_options"].pop("fallback_nodata")

        method_options = info.get("method_options", {})
        if isinstance(method_options.get("nodata"), str):
            nodata = _numeric_nodata(method_options["nodata"])
            if nodata is None:
                logger.warning(
                    "Asset '%s': STAC nodata %r is not a number, it is ignored.",
                    info.get("name"),
                    method_options["nodata"],
                )
                method_options.pop("nodata")
            else:
                method_options["nodata"] = nodata
        return info

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

        # No `allowed_exceptions`: one asset outside the bbox makes the whole
        # item outside it (`TileOutsideBounds`, which `mosaic_reader` skips).
        # Dropping only that asset would give this item fewer bands than the
        # others, in another order: openEO `load_collection` puts the bands
        # in the requested order in each slice, and a pixel with no data is a
        # no-data value, not a missing band. All the assets of an EOPF item
        # cover the same tile, so no data is lost. Any other error (e.g. an
        # unknown band name from `_get_options`) reaches the caller.
        img = multi_arrays(
            assets,
            _reader,
            bbox,
            allowed_exceptions=(),
            **kwargs,
        )

        img.band_names = [f"b{ix + 1}" for ix in range(img.count)]
        if expression:
            return img.apply_expression(expression)

        return img
