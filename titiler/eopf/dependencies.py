"""titiler.eopf.dependencies."""

import os
from dataclasses import dataclass
from typing import Annotated, List, Literal

from fastapi import Path, Query
from starlette.requests import Request

from titiler.core.dependencies import BidxParams, DefaultDependency
from titiler.xarray.dependencies import SelDimStr

from .settings import DataStoreSettings

store_settings = DataStoreSettings()


def DatasetPathParams(
    request: Request,
    collection_id: Annotated[
        str,
        Path(description="Copernicus Collection Identifier"),
    ],
    item_id: Annotated[str, Path(description="Copernicus Item Identifier")],
) -> str:
    """Item dependency."""
    store_url = str(store_settings.url)
    return os.path.join(store_url, collection_id, item_id) + ".zarr"


@dataclass
class XarrayParams(DefaultDependency):
    """Xarray Dataset Options."""

    variables: Annotated[
        List[str],
        Query(
            description="Xarray Variable name in form of `{group_name}:{variable_name}`."
        ),
    ]

    sel: Annotated[
        List[SelDimStr] | None,
        Query(
            description="Xarray Indexing using dimension names `{dimension}={value}`.",
        ),
    ] = None

    method: Annotated[
        Literal["nearest", "pad", "ffill", "backfill", "bfill"] | None,
        Query(
            alias="sel_method",
            description="Xarray indexing method to use for inexact matches.",
        ),
    ] = None


@dataclass
class LayerParams(BidxParams, XarrayParams):
    """variable + indexes."""

    pass


@dataclass
class VariablesParams(DefaultDependency):
    """Xarray Dataset Options."""

    variables: Annotated[
        List[str] | None,
        Query(
            description="Xarray Variable name in form of `{group_name}:{variable_name}`."
        ),
    ] = None

    sel: Annotated[
        List[SelDimStr] | None,
        Query(
            description="Xarray Indexing using dimension names `{dimension}={value}`.",
        ),
    ] = None

    method: Annotated[
        Literal["nearest", "pad", "ffill", "backfill", "bfill"] | None,
        Query(
            alias="sel_method",
            description="Xarray indexing method to use for inexact matches.",
        ),
    ] = None
