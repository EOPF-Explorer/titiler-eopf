"""titiler.eopf.dependencies."""

import os
from dataclasses import dataclass
from typing import Annotated, List

from fastapi import Path, Query
from starlette.requests import Request

from titiler.core.dependencies import BidxParams, DefaultDependency, ExpressionParams
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
            description="Xarray Indexing using dimension names `{dimension}={value}` or `{dimension}={method}::{value}`.",
        ),
    ] = None


@dataclass
class LayerParams(BidxParams, ExpressionParams, VariablesParams):
    """variable + indexes."""

    def __post_init__(self):
        """Post Init."""
        if not self.variables and not self.expression:
            raise ValueError(
                "variables must be defined either via expression or variables options."
            )
