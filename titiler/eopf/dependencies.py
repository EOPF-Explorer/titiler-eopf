"""titiler.eopf.dependencies."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Query

from titiler.core.dependencies import BidxParams, DefaultDependency, ExpressionParams
from titiler.xarray.dependencies import SelDimStr


@dataclass
class VariablesParams(DefaultDependency):
    """Xarray Dataset Options."""

    variables: Annotated[
        list[str] | None,
        Query(
            description="Xarray Variable name in form of `{group_name}:{variable_name}`."
        ),
    ] = None

    sel: Annotated[
        list[SelDimStr] | None,
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
