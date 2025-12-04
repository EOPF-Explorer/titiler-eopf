"""Custom stacApiBackend for EOPF."""

from attrs import define
from pystac import Collection
from pystac.extensions import datacube as dc

from titiler.openeo.stacapi import stacApiBackend as BaseBackend


@define
class stacApiBackend(BaseBackend):
    """Custom stacApiBackend."""

    def add_data_cubes_if_missing(self, collection: Collection):
        """Add datacubes extension to collection if missing."""
        if not collection.ext.has("cube"):
            dc.DatacubeExtension.add_to(collection)
            """ Add minimal dimensions """
            collection.ext.cube.apply(
                dimensions=self.getdimensions(collection),
                # variables=self.getvariables(collection),
            )

        return collection
