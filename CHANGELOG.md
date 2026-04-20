# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add map scale control (metric units) to display real-world distances at current zoom level (#46)
- Toggle map scale units between metric and imperial when clicking the scale control (#77)
- Add default ZIM tags based on Kiwix convention (#76)
- Add --max-zoom to configure maximum zoom level of tiles to include in the ZIM (#84)

### Fixed

- Set the maximum zoom level to 18 (#86)
- Use libzim 3.9.0 or above to fix freezing compression issues (#61)
- Immediately redirect when opening search results (#60)
- Remove pin button with display of coordinates and zoom (#58)
- Remove style selector (#57)
- Switch to automatically chosen map style based on prefer-colors-scheme (#56)
- Fix support of RTL strings in the map (#54)
- Move from --assets to --dl CLI param for code clarity (#68)
- Fix bad favicon paths (#68)
- Replace axios with fetch API and move config.json to a relative URL (#75)
- Create ZIM alias instead of redirects for tiles (#53)
- Reduce number of alias for tiles to a strict minimum (#78)
- Bundle ZIM UI inside pip package (#63)
- Ensure map borders are consistent at all zoom levels (#90)
- Homepage should focus on the proper location and zoom (#55)
- Fix prettier and eslint check in zimui QA CI (#85)
- Do not create a full-text index (#91)

## [0.1.1] - 2026-03-10

### Fixed

- Tiles are not compressed by libzim (#47)
- Default longitude and latitude handling is wrong (#43)
- Prefer webp to png for natural earth (#48)

## [0.1.0] - 2026-03-06

### Added

- Initial version
