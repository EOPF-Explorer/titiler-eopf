# Optimize reader: defer indexes & fast metadata-only info

## Problem

Two performance issues in `GeoZarrReader`:

### 1. Eager coordinate loading on open (~7s)

When opening a Zarr dataset from S3 with `xarray.open_datatree`, xarray creates `PandasIndex` objects for all 1-D coordinate variables by default. This triggers `PandasIndex.from_variables()`, which eagerly materializes coordinate arrays by reading them from S3 — even when only metadata (dims, CRS) is needed.

Profiling showed this costs **~7.15 seconds** out of a total **~7.8s** dataset open time (92%), all spent in `ZarrArrayWrapper.__getitem__` → S3 I/O. Additionally, `_maybe_create_default_indexes` was called redundantly across many methods, each time re-materializing the same coordinate arrays.

### 2. `info()` slower than `open` (~108ms vs ~22ms)

After fixing the open, the `info()` endpoint became the bottleneck — **5x slower** than opening the dataset. Profiling showed two sources of waste:

- **Double `write_crs`** (~34ms): `_arrange_dims` calls `write_crs` unconditionally, then `_get_variable` calls it again — redundant pyproj `CRS.to_cf` work.
- **XarrayReader init overhead** (~52ms): For each variable, `info()` instantiated `XarrayReader` which recomputes bounds/transform/resolution via rioxarray (`_internal_bounds` called ~6x) — all unnecessary when only metadata is needed.

## Solution

### 1. Open without indexes (`create_default_indexes=False`)

Pass `create_default_indexes=False` to `xarray.open_datatree` in `open_dataset()`. Coordinate arrays remain lazy, making the open call near-instant for metadata operations.

### 2. Cache indexed datasets via `_get_indexed_dataset(path)`

New method with per-path caching (`_indexed_ds_cache` dict). When a method actually needs coordinate values, it calls this method which:
- Creates indexes via `_maybe_create_default_indexes` on first access
- Caches the result so subsequent calls for the same group path are free

### 3. Skip index creation for metadata-only validation

`_validate_zarr` only checks `ds.dims` and `ds.rio.crs` — both work without indexes when `decode_coords="all"` is set.

### 4. Fast-path `info()` via `_build_info_fast`

New method builds `Info` objects directly from GeoZarr metadata attributes and the raw lazy DataArray, bypassing `_get_variable` + `XarrayReader` entirely:
- Reads CRS from group attributes (V1: `proj:code`/`proj:wkt2`, V0: `tile_matrix_set.crs`)
- Reads bounds from `spatial:bbox` attributes or cached `_get_scale_bounds`
- Gets width/height from `da.sizes` (no rioxarray needed)
- Falls back to `_get_info_via_reader` only when `sel` parameter is provided

### 5. Skip redundant `write_crs` in `_arrange_dims`

`_arrange_dims` now only calls `write_crs` when the DataArray has no CRS set, avoiding the redundant second call.

### 6. Cache per-scale bounds via `_get_scale_bounds`

New `_bounds_cache` dict + `_get_scale_bounds(path)` method caches `ds.rio.bounds()` per scale path, reused across multiple variables in the same group.

## Changes

**`titiler/eopf/reader.py`**:

- **`open_dataset`**: Added `create_default_indexes=False` to `open_datatree` call
- **`_arrange_dims`**: `write_crs` now conditional — only when CRS is missing
- **`GeoZarrReader._indexed_ds_cache`**: New `Dict` attribute for caching indexed datasets
- **`GeoZarrReader._bounds_cache`**: New `Dict` attribute for caching per-scale bounds
- **`GeoZarrReader._get_indexed_dataset(path)`**: New method — creates and caches datasets with indexes per datatree path
- **`GeoZarrReader._get_scale_bounds(path)`**: New method — caches `ds.rio.bounds()` per scale path
- **`GeoZarrReader.info()`**: Rewritten with fast path (`_build_info_fast`) and fallback (`_get_info_via_reader`)
- **`GeoZarrReader._build_info_fast()`**: New method — builds `Info` directly from metadata without XarrayReader
- **`GeoZarrReader._get_info_via_reader()`**: New method — original XarrayReader-based info (used when `sel` is provided)
- **`__attrs_post_init__`**: Root dataset explicitly calls `_maybe_create_default_indexes` (only for datasets with global spatial info)
- **`_get_groups`**: `_validate_zarr` is metadata-only, no indexes needed
- **`get_bounds`**, **`get_minzoom`**, **`get_maxzoom`**, **`_get_variable`**: All use `_get_indexed_dataset` (cached)

## Impact

| Operation | Before | After | Speedup |
|-----------|--------|-------|---------|
| Dataset open (S3) | ~7.8s | ~0.85s | ~9x |
| `info()` (cached dataset) | ~108ms | ~23ms | ~5x |
| `info()` total (open + info) | ~7.9s | ~68ms | ~116x |
| `preview()` | ~0.52s | ~1.4s (S3 I/O) | N/A (I/O bound) |

The key wins:
- **Open** no longer reads coordinate data from S3 at all
- **`info()`** bypasses XarrayReader and `_get_variable` entirely — pure metadata reads
- **Data operations** (`tile`, `preview`, `part`) pay coordinate loading cost only once per group (cached)

## Tests

All 126 tests pass with no modifications to test code.
