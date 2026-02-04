# Plan: Upgrade titiler-openeo to v0.12.0

Upgrade from titiler-openeo 0.11.0 to 0.12.0. The key insight is that `RasterStack` is now a **unique timestamp stack** - the base library handles date grouping and mosaicking internally. Our role is to provide **Zarr-specific readers and adapters only**.

## Architecture Principles

- **Delegate to upstream**: Use the base `load_collection` implementation from `titiler.openeo` directly
- **Zarr readers only**: Our custom code should only provide `GeoZarrReader` integration
- **Minimal overrides**: Only override what's necessary for Zarr asset detection and reading
- **Preserve laziness**: Tasks must remain lazy - they should only execute when data is actually accessed

## Laziness is Fundamental

The `RasterStack` in v0.12.0 is **inherently lazy**:

```python
# Tasks are (callable, asset_info) tuples - the callable is NOT executed at construction time
tasks = [
    (task_fn, {"datetime": dt1, "geometry": geom1}),
    (task_fn, {"datetime": dt2, "geometry": geom2}),
]

# RasterStack stores tasks, not results
stack = RasterStack(
    tasks=tasks,
    timestamp_fn=lambda asset: asset["datetime"],
    ...
)

# Data is only loaded when accessed:
img = stack[some_datetime]  # <-- THIS triggers task execution
```

### How Laziness Works in v0.12.0

1. **Construction**: `RasterStack.__init__` stores tasks and creates `ImageRef` objects (lazy references)
2. **Key mapping**: `timestamp_fn(asset_info)` extracts datetime to use as dictionary key
3. **Deferred execution**: The task function is only called when `stack[key]` is accessed
4. **Caching**: Once executed, results are cached in `_data_cache` to avoid re-execution

### Our Lazy Tasks Must Follow This Pattern

For `load_zarr`:
```python
def _create_zarr_time_task(time_key, zarr_dataset, variables, options):
    def load_time_slice():  # <-- This is the lazy task
        # Only executed when accessed
        return zarr_dataset.part(bbox=..., variables=...)
    return load_time_slice

# Build tasks list
tasks = []
for time_key in time_values:
    task_fn = _create_zarr_time_task(time_key, zarr_dataset, variables, options)
    asset_info = {"datetime": parse_datetime(time_key), ...}
    tasks.append((task_fn, asset_info))

return RasterStack(
    tasks=tasks,
    timestamp_fn=lambda asset: asset["datetime"],  # datetime IS the key
    ...
)
```

## Investigation: How upstream `load_collection` works in v0.12.0

The upstream `LoadCollection.load_collection()` method (in `titiler.openeo.stacapi`) now handles everything:

### 1. Item Retrieval
```python
items = self._get_items(id, spatial_extent, temporal_extent, properties, ...)
```

### 2. Automatic Date Grouping (HANDLED BY UPSTREAM)
```python
# Group items by date
items_by_date: dict[str, list[Item]] = {}
for item in items:
    date = item.datetime.isoformat()
    if date not in items_by_date:
        items_by_date[date] = []
    items_by_date[date].append(item)
```

### 3. Per-Date Mosaic Task Creation (HANDLED BY UPSTREAM)
```python
def make_mosaic_task(date_items, bbox, bounds_crs, output_crs, bands, width, height, tile_buffer):
    def task():
        mosaic_kwargs = {
            "threads": 0,
            "bounds_crs": bounds_crs,
            "assets": bands,
            "dst_crs": output_crs,
            "width": int(width) if width else width,
            "height": int(height) if height else height,
            "buffer": float(tile_buffer) if tile_buffer is not None else tile_buffer,
            "pixel_selection": PixelSelectionMethod["first"].value(),
        }
        img, _ = mosaic_reader(date_items, _reader, bbox, **mosaic_kwargs)
        return img
    return task
```

### 4. RasterStack Construction (HANDLED BY UPSTREAM)
```python
tasks = []
for date, date_items in items_by_date.items():
    task_fn = make_mosaic_task(date_items, bbox, ...)
    geometries = [item.geometry for item in date_items if item.geometry is not None]
    tasks.append((task_fn, {"id": date, "datetime": date_items[0].datetime, "geometry": geometries}))

return RasterStack(
    tasks=tasks,
    timestamp_fn=lambda asset: asset["datetime"],  # datetime IS the key
    width=int(width) if width else None,
    height=int(height) if height else None,
    bounds=output_bbox,
    dst_crs=output_crs,
    band_names=bands if bands else [],
)
```

### Key Insight: The upstream uses `_reader` from `titiler.openeo.reader`

The upstream imports: `from .reader import _estimate_output_dimensions, _reader`

This `_reader` is the function that actually reads each STAC item. **This is where we need to inject our Zarr support!**

## Revised Strategy

Instead of overriding the entire `load_collection` method, we need to:

1. **Provide a custom `_reader` function** that detects Zarr media types and uses `GeoZarrReader`
2. **Or: Register `GeoZarrReader` as a reader for Zarr media types** if the upstream supports reader registration

### Option A: Override `_reader` only
If titiler-openeo allows customizing the reader function, we just provide our Zarr-aware reader.

### Option B: Minimal `load_collection` override
If we must override `load_collection`, we copy the upstream logic but use our custom reader.

### Option C: Monkey-patch or dependency injection
Register `GeoZarrReader` through whatever mechanism titiler-openeo provides.

## Steps

1. **Update dependency** in pyproject.toml: Change `titiler-openeo==0.11.0` to `titiler-openeo==0.12.0`

2. **Investigate reader injection**: Check if titiler-openeo 0.12.0 provides a way to register custom readers

3. **Move `LoadCollection` to stacapi.py** (matching upstream structure):
   - Move `LoadCollection` class from `io.py` to `stacapi.py`
   - This mirrors how `titiler.openeo` structures it: `LoadCollection` lives in `stacapi.py`
   - Keep only `load_zarr` in `io.py` (it's a process, not a backend loader)

4. **Simplify `LoadCollection` class** in stacapi.py:
   - Inherit from base `stacapi.LoadCollection`
   - Override only what's needed for Zarr reader injection
   - Let base class handle date grouping and RasterStack creation

5. **Update `load_zarr`** in io.py:
   - Replace `LazyRasterStack` with `RasterStack`
   - Remove `key_fn` parameter (datetime IS the key now)
   - Use `timestamp_fn` only

6. **Update imports**:
   - In `stacapi.py`: `from titiler.openeo.processes.implementations.data_model import RasterStack`
   - In `io.py`: Remove `LazyRasterStack` import, add `RasterStack`
   - Update `__init__.py` exports if needed

7. **Update tests**: Verify tests pass with simplified implementation

## Key Simplifications

| Before (v0.11.0) | After (v0.12.0) |
|------------------|-----------------|
| Custom `load_collection` with manual task creation | Inherit base `load_collection`, provide reader only |
| `LazyRasterStack` with `key_fn` + `timestamp_fn` | `RasterStack` with `timestamp_fn` only (datetime = key) |
| Manual item grouping by date | Handled by base library |
| Custom mosaicking logic | Handled by base library |

## Files to Modify

1. **pyproject.toml** - Bump dependency version
2. **titiler/eopf/openeo/stacapi.py** - Add `LoadCollection` class (moved from io.py)
3. **titiler/eopf/openeo/reader.py** - New file with `STACReader`, `_reader` function (Zarr-aware readers)
4. **titiler/eopf/openeo/processes/implementations/io.py** - Keep only `load_zarr`, remove `LoadCollection`
5. **titiler/eopf/openeo/main.py** - Update imports for `LoadCollection` from `stacapi`
6. **tests/test_openeo_processes.py** - Update for new API

## What We Keep

- `STACReader` class with Zarr media type detection (in `reader.py`)
- `_reader` function with retry logic (in `reader.py`)
- `GeoZarrReader` integration for reading Zarr assets
- `load_zarr` function in `io.py` for direct Zarr loading (non-STAC use case)
- Custom `stacApiBackend` in `stacapi.py` for EOPF collection metadata enrichment
- `LoadCollection` in `stacapi.py` importing reader from `reader.py`

## Other Considerations

- use uv
- keep and update devlog
- if integration is really a problem with openeo v0.12.0, we have the possibility to make quick fixes and release a v0.12.1 or v0.12.2 immediately after
