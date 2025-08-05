"""titiler.xarray Extensions."""

from typing import List

from attrs import define
from fastapi import Depends
from starlette.responses import HTMLResponse

from titiler.core.factory import FactoryExtension
from titiler.core.resources.enums import MediaType

from .factory import TilerFactory


@define
class DatasetMetadataExtension(FactoryExtension):
    """Add dataset metadata endpoints to a Factory."""

    def register(self, factory: TilerFactory):
        """Register endpoint to the tiler factory."""

        @factory.router.get(
            "/dataset/",
            responses={
                200: {
                    "description": "Returns the HTML representation of the Xarray DataTree.",
                    "content": {
                        MediaType.html.value: {},
                    },
                },
            },
            response_class=HTMLResponse,
        )
        def dataset_metadata_html(src_path=Depends(factory.path_dependency)):
            """Returns the HTML representation of the Xarray Dataset."""
            with factory.reader(src_path) as ds:
                return HTMLResponse(ds.datatree._repr_html_())

        @factory.router.get(
            "/dataset/dict",
            responses={
                200: {"description": "Returns the full Xarray dataset as a dictionary."}
            },
        )
        def dataset_metadata_dict(src_path=Depends(factory.path_dependency)):
            """Returns the full Xarray dataset as a dictionary."""
            with factory.reader(src_path) as ds:
                return ds.datatree.to_dict(data=False)

        @factory.router.get(
            "/dataset/groups",
            response_model=List[str],
            responses={
                200: {"description": "Returns the list of groups in the DataTree."}
            },
        )
        def dataset_groups(src_path=Depends(factory.path_dependency)):
            """Returns the list of groups in the DataTree."""
            with factory.reader(src_path) as ds:
                return ds.groups

        @factory.router.get(
            "/dataset/keys",
            response_model=List[str],
            responses={
                200: {
                    "description": "Returns the list of keys/variables in the DataTree."
                }
            },
        )
        def dataset_variables(src_path=Depends(factory.path_dependency)):
            """Returns the list of keys/variables in the DataTree."""
            with factory.reader(src_path) as ds:
                return ds.variables
