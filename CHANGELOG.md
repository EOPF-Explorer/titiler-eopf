

## [Unreleased]

## [0.2.1] - 2025-12-04

### Added

* Ability to deploy redis via chart or to bring your own redis deployment (#43)

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

[Unreleased]: <https://github.com/EOPF-Explorer/titiler-eopf/compare/0.2.0..main>
[0.2.0]: <https://github.com/EOPF-Explorer/titiler-eopf/compare/0.1.0..0.2.0>
[0.1.0]: <https://github.com/EOPF-Explorer/titiler-eopf/tree/0.1.0>
