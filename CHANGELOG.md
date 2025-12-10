

## [Unreleased]

## [0.4.0] - 2025-12-10

### Added

* Improved error handling and resilient reading in case of missing data (#50)
* Enhanced code organization in STACReader and LazyZarrRasterStack classes (#50)
* Better logging for data loading traceability (#50)
* Graceful handling of missing data to ensure processing continuity (#50)

### Changed

* Initialize cache settings in main application and openeo (#49)
* Centralized cache management for better handling of cache settings (#49)
* Updated titiler-openeo dependency to v0.7.0 (#50)
* Fixed environment variable naming: `TITILER_OPENEO_SERVICE_STORE_URL` → `TITILER_OPENEO_STORE_URL` (#50)
* Improved bounds checking with proper exception handling (#50)
* Enhanced variable name handling in band descriptions (#50)
* Updated OpenEO processing max items limit to 1000 (#50)

### Fixed

* Resilient data reading with retry logic for network errors (#50)
* Better handling of Zarr data loading edge cases (#50)
* Improved variable filtering and band name extraction (#50)

## [0.3.0] - 2025-12-04

### Added

* Ability to deploy redis via chart or to bring your own redis deployment (#43)
* Updated titiler-openeo dependency to use v0.6.1 (#44)

## [0.2.0] - 2025-12-04

### Added

* OpenEO API support (#30, #33)
* Redis cache support (#26)
* Chunk viewer with enhanced metadata (#21, #27)
* Preview endpoint (#24)
* `/bbox` and `/feature` endpoints (#25)
* `/viewer` endpoint (#16)
* Multiscale pyramid support with optimized variable collection (#22)
* AWS_PROFILE environment variable support (#19)
* Timing middleware
* Mercator grid support
* CI: tag latest when default branch merge (#39)

### Changed

* Updated to titiler 0.24 (#20)
* Enhanced multiscale level parameter to support both string and integer values (#36)
* Improved logging configuration
* Refactored code structure for improved readability and maintainability
* Updated zarr dependency to version 3.1.3

### Fixed

* Adjusted pixel sizes for pyramid datasets (#23)
* Improved handling of missing variables in pyramids (#22)

## [0.1.0] - TBD

* initial release

[Unreleased]: <https://github.com/EOPF-Explorer/titiler-eopf/compare/0.4.0..main>
[0.4.0]: <https://github.com/EOPF-Explorer/titiler-eopf/compare/0.3.0..0.4.0>
[0.3.0]: <https://github.com/EOPF-Explorer/titiler-eopf/compare/0.2.0..0.3.0>
[0.2.0]: <https://github.com/EOPF-Explorer/titiler-eopf/compare/0.1.0..0.2.0>
[0.1.0]: <https://github.com/EOPF-Explorer/titiler-eopf/tree/0.1.0>
