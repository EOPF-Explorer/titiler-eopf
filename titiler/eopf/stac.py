"""titiler-eopf stac backend."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, cast

import attr
import pystac
import zarr
from fastapi import Path, Query
from pydantic import AfterValidator
from rio_tiler.errors import InvalidAssetName
from rio_tiler.io.stac import DEFAULT_VALID_TYPE, STAC_ALTERNATE_KEY
from rio_tiler.models import Info
from rio_tiler.types import AssetInfo, AssetType, AssetWithOptions
from starlette.requests import Request

from titiler.core.dependencies import DefaultDependency, ExpressionParams
from titiler.eopf.reader import GeoZarrReader
from titiler.stacapi.backend import STACAPIBackend
from titiler.stacapi.dependencies import get_stac_item
from titiler.stacapi.reader import SimpleSTACReader, STACAPIReader

_VALID_TYPE = {
    *DEFAULT_VALID_TYPE,
    "application/x-zarr",
    "application/vnd.zarr",
    "application/vnd+zarr",
    "application/vnd.zarr; version=3",
    "application/vnd.zarr; version=3; profile=multiscales",
}

VALID_ASSET_OPTIONS = {"bidx", "expression", "bands", "variables", "sel"}


def _parse_option(key: str, value: str) -> tuple[str, Any]:
    """Parse a single asset option key=value pair into (opts_key, opts_value)."""
    if key == "bidx":
        try:
            return ("indexes", list(map(int, value.split(","))))
        except ValueError:
            raise ValueError(
                f"Invalid bidx value '{value}'. "
                f"Expected comma-separated integers, e.g. 'bidx=1' or 'bidx=1,2,3'"
            ) from None

    if key == "expression":
        return ("expression", value)

    if key == "bands":
        return ("bands", value.split(","))

    # custom part for Stac/GeoZarrReader
    if key == "variables":
        return ("variables", value.split(","))

    if key == "sel":
        return ("sel", value.split(","))

    raise ValueError(
        f"Unknown asset option '{key}'. "
        f"Valid options: {', '.join(sorted(VALID_ASSET_OPTIONS))}"
    )


def _parse_asset(values: list[str]) -> list[AssetType]:
    """Parse assets with optional parameter.

    Format: ``asset_name`` or ``asset_name|key=value|key=value``

    Supported options:
        - ``bidx=1,2`` — band indexes
        - ``expression=...`` — band math expression
        - ``bands=red,green`` — band names
        - ``variables=vv,vh`` — variable names (for GeoZarr)
        - ``sel=time=2022-02-01`` — dimension selection (for GeoZarr)

    Raises:
        ValueError: If an option is missing a ``key=value`` pair or uses an unknown key.
    """
    # special case for ":all:" to avoid parsing it as an asset name
    if values == [":all:"]:
        return values

    assets: list[AssetType] = []
    for v in values:
        # asset with options
        if "|" in v:
            asset_name, params = v.split("|", 1)
            opts: dict[str, Any] = {"name": asset_name}
            for option in params.split("|"):
                if "=" not in option:
                    raise ValueError(
                        f"Invalid asset option '{option}' in '{v}'. "
                        f"Options must be in 'key=value' format. "
                        f"Valid keys: {', '.join(sorted(VALID_ASSET_OPTIONS))}. "
                        f"Example: '{asset_name}|bidx=1' or '{asset_name}|variables=vv,vh'"
                    )

                key, value = option.split("=", 1)
                try:
                    opts_key, opts_value = _parse_option(key, value)
                except ValueError as e:
                    raise ValueError(f"Error parsing asset '{v}': {e}") from e

                opts[opts_key] = opts_value

            asset = cast(AssetWithOptions, opts)
            assets.append(asset)

        # asset without options
        else:
            assets.append({"name": v})

    return assets


@dataclass
class AssetsParams(DefaultDependency):
    """Assets parameters."""

    assets: Annotated[
        list[str],
        AfterValidator(_parse_asset),
        Query(
            title="Asset names",
            description="Asset's names.",
            openapi_examples={
                "user-provided": {"value": None},
                "one-asset": {
                    "description": "Return results for asset `data`.",
                    "value": ["data"],
                },
                "multi-assets": {
                    "description": "Return results for assets `data` and `cog`.",
                    "value": ["data", "cog"],
                },
                "multi-assets-with-options": {
                    "description": "Return results for assets `data` and `cog`.",
                    "value": ["data|bidx=1", "cog|bidx=1,2"],
                },
            },
        ),
    ]


@dataclass
class AssetsExprParams(ExpressionParams, AssetsParams):
    """Assets and Expression parameters."""

    asset_as_band: Annotated[
        bool | None,
        Query(
            title="Consider asset as a 1 band dataset",
            description="Asset as Band",
        ),
    ] = None


def _get_options(  # noqa: C901
    asset: AssetWithOptions,
    metadata: dict,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return Method/Reader options for a given asset and stac metadata."""
    method_options: dict[str, Any] = {}
    reader_options: dict[str, Any] = {}
    if isinstance(asset, dict):
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
            stac_bands = metadata.get("bands") or metadata.get("eo:bands")
            if not stac_bands:
                raise ValueError(
                    "Asset does not have 'bands' metadata, unable to use 'bands' option"
                )

            # For Zarr bands = variable
            media_type = metadata.get("type", "")
            zarr_media_types = [
                "application/x-zarr",
                "application/vnd.zarr",
                "application/vnd+zarr",
            ]
            if media_type.split(";")[0].strip() in zarr_media_types:
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


@attr.s
class EOPFSTACAPIReader(STACAPIReader):
    """Custom EOPF STACAPI Reader."""

    reader: type[GeoZarrReader] = attr.ib(default=GeoZarrReader)
    include_asset_types: set[str] = attr.ib(default=_VALID_TYPE)

    def info(
        self,
        assets: Sequence[AssetType] | AssetType | None = None,
        **kwargs: Any,
    ) -> dict[str, Info]:
        """Return metadata from multiple assets.

        Args:
            assets (sequence of str or str, optional): assets to fetch info from. Required keyword argument.

        Returns:
            dict: Multiple assets info in form of {"asset1": rio_tile.models.Info}.

        """

        # Some STAC assets (e.g. AOT/SCL/WVP) point at a single Zarr Array rather
        # than a Group, and `GeoZarrReader` opens every asset as a `DataTree`.
        # Opening an Array path as a DataTree raises `ContainsArrayError` (xarray
        # tries `zarr.open_group`/`open_consolidated` on a path that is actually
        # an Array). Since `.info()` fans out over *all* assets, allow that
        # exception so those non-group assets are skipped instead of failing
        # the whole request.
        allowed_exceptions = kwargs.pop("allowed_exceptions", ())
        allowed_exceptions += (zarr.errors.ContainsArrayError,)
        infos = super().info(
            assets=assets, **kwargs, allowed_exceptions=allowed_exceptions
        )

        def _key_to_var(v: str) -> str:
            if ":" in v:
                group, var = v.split(":")
                return var if group == "/" else f"{group.lstrip("/")}_{var}"
            return v

        # Keys are in form or "{asset_name}_({group_name}_)?{variable_name}"
        return {
            f"{asset_name.split("|")[0]}_{_key_to_var(key)}": value
            for asset_name, info in infos.items()
            for key, value in info.items()
        }

    def _get_options(
        self,
        asset: AssetWithOptions,
        metadata: pystac.Asset,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return _get_options(asset, metadata.to_dict())


@attr.s
class EOPFSimpleSTACReader(SimpleSTACReader):
    """Custom EOPF Simple STAC Reader, used in STACAPI Mosaic Backend."""

    reader: type[GeoZarrReader] = attr.ib(default=GeoZarrReader)

    def _get_asset_info(self, asset: AssetType) -> AssetInfo:  # noqa: C901
        """Validate asset names and return asset's url.

        Args:
            asset (AssetType): STAC asset name.

        Returns:
            AssetInfo: STAC asset informations.

        """
        if isinstance(asset, str):
            asset = {"name": asset}

        if not asset.get("name"):
            raise ValueError("asset dictionary does not have `name` key")

        asset_name = asset["name"]
        if asset_name not in self.assets:
            raise InvalidAssetName(
                f"'{asset_name}' is not valid, should be one of {self.assets}"
            )

        asset_info = self.input["assets"][asset_name]

        reader_options, method_options = _get_options(asset, asset_info)

        info = AssetInfo(
            url=asset_info["href"],
            name=asset_name,
            media_type=asset_info.get("type"),
            reader_options=reader_options,
            method_options=method_options,
        )

        if STAC_ALTERNATE_KEY and "alternate" in asset_info:
            if alternate := asset_info["alternate"].get(STAC_ALTERNATE_KEY):
                info["url"] = alternate["href"]

        if header_size := asset_info.get("file:header_size"):
            info["env"]["GDAL_INGESTED_BYTES_AT_OPEN"] = header_size

        asset_modified = "expression" in method_options
        if (bands := asset_info.get("raster:bands")) and not asset_modified:
            stats = [
                (b["statistics"]["minimum"], b["statistics"]["maximum"])
                for b in bands
                if {"minimum", "maximum"}.issubset(b.get("statistics", {}))
            ]
            if len(stats) == len(bands):
                info["dataset_statistics"] = stats

        return info


@attr.s
class EOPFSTACAPIBackend(STACAPIBackend):
    """Custom EOPF STACAPI Backend."""

    reader: type[EOPFSimpleSTACReader] = attr.ib(default=EOPFSimpleSTACReader)


def asset_path_parameter(
    request: Request,
    collection_id: Annotated[str, Path(description="STAC Collection Identifier")],
    item_id: Annotated[str, Path(description="STAC Item Identifier")],
    asset_id: Annotated[str, Path(description="STAC Asset Identifier")],
) -> str:
    """STAC Asset dependency."""
    headers: dict[str, Any] = {}
    item = get_stac_item(
        request.app.state.stac_url,
        collection_id,
        item_id,
        headers=headers,
    )

    if asset_id not in item.assets:
        raise InvalidAssetName(
            f"'{asset_id}' is not valid, should be one of {list(item.assets)}"
        )

    asset_info = item.assets[asset_id]

    url = asset_info.get_absolute_href()
    if STAC_ALTERNATE_KEY and asset_info.extra_fields.get("alternate"):
        if alternate := asset_info.extra_fields["alternate"].get(STAC_ALTERNATE_KEY):
            url = alternate["href"]

    return url
