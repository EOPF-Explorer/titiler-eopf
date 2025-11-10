"""titiler-eopf openeo test processes"""

from titiler.eopf.openeo.processes import PROCESS_IMPLEMENTATIONS, process_registry


def test_custom_processes():
    """make sure custom processes are registered"""
    assert len(PROCESS_IMPLEMENTATIONS) == 1
    assert PROCESS_IMPLEMENTATIONS[0].__name__ == "load_zarr"


def test_registery():
    """Check load_zarr is in the registery"""
    _, last_registered = list(process_registry)[-1]
    assert last_registered == "load_zarr"

    assert process_registry.get("load_zarr")
