"""titiler-eopf stac backend."""

from dataclasses import dataclass
from typing import Annotated, Any, cast

import attr
from fastapi import Query
from pydantic import AfterValidator
from rio_tiler.errors import InvalidAssetName
from rio_tiler.io.stac import STAC_ALTERNATE_KEY
from rio_tiler.types import AssetInfo, AssetType, AssetWithOptions

from titiler.core.dependencies import DefaultDependency, ExpressionParams
from titiler.eopf.reader import GeoZarrReader
from titiler.stacapi.backend import STACAPIBackend
from titiler.stacapi.reader import SimpleSTACReader, STACAPIReader


def _parse_asset(values: list[str]) -> list[AssetType]:
    """Parse assets with optional parameter."""
    assets: list[AssetType] = []
    for v in values:
        if "|" in v:
            asset_name, params = v.split("|", 1)
            opts: dict[str, Any] = {"name": asset_name}
            for option in params.split("|"):
                key, value = option.split("=", 1)
                if key == "bidx":
                    opts["indexes"] = list(map(int, value.split(",")))
                elif key == "expression":
                    opts["expression"] = value
                elif key == "bands":
                    opts["bands"] = value.split(",")
                # custom part for Stac/GeoZarrReader
                elif key == "variables":
                    opts["variables"] = value.split(",")

            asset = cast(AssetWithOptions, opts)
            assets.append(asset)
        else:
            assets.append(v)

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


@attr.s
class EOPFSTACAPIReader(STACAPIReader):
    """Custom EOPF STAC Reader."""

    include_asset_types: set[str] = attr.ib(
        factory=lambda: {
            "application/vnd+zarr",
            "application/vnd+zarr; version=2; profile=multiscales",
        }
    )
    reader: type[GeoZarrReader] = attr.ib(default=GeoZarrReader)


@attr.s
class EOPFSimpleSTACReader(SimpleSTACReader):
    """Custom EOPF Simple STAC Reader."""

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
            # Bands
            if bands := asset.get("bands"):
                stac_bands = asset_info.get("bands") or asset_info.get("eo:bands")
                if not stac_bands:
                    raise ValueError(
                        "Asset does not have 'bands' metadata, unable to use 'bands' option"
                    )

                # For Zarr bands = variable
                if "application/vnd+zarr" in asset_info["type"]:
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
