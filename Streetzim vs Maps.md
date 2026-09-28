# openzim/maps vs. streetzim: comparison and recommendation

## About this document

This document was written by **Claude** (Anthropic's Opus 5.5 model, running in Claude Code) at the request of the PR author. Claude cloned both repositories and read their source code and documentation at the commits listed above. Line counts and feature claims come from the code at those commits and may change. Effort estimates and the recommendation are Claude's own judgment and should be reviewed as such.

The prompt given to Claude was:

> Please make a thourough comparison of two tools creating ZIM of maps:
>
> - one is at https://github.com/jasontitus/streetzim
> - the other is at https://github.com/openzim/maps/
>
> I'm interested in:
>
> - user-facing features
> - software stack
> - technical implementation details
> - data sources
>
> Take time to review the codebase for details.

## Introduction

This document compares two tools that package OpenStreetMap-based maps into ZIM files:

- **openzim/maps** (`maps2zim`): <https://github.com/openzim/maps>, reviewed at `3c3cdbb` (2026-09-07)
- **streetzim**: <https://github.com/jasontitus/streetzim>, reviewed at `abdb891` (2026-09-26)

It covers user-facing features, the software stack, how each tool is built, and where each one gets its data. It ends with a recommendation on the way forward:

- **Option A**: add streetzim's features to openzim/maps.
- **Option B**: adapt streetzim to Kiwix/openZIM constraints and pay down its technical debt.

## TL;DR

- **openzim/maps** is small (about 2.4k lines of core Python plus a 360-line JS viewer), clean and well tested, and it already fits openZIM's conventions (Docker, Zimfarm offliner definition, strict typing, daily CI with `zimcheck`). It delegates nearly all the heavy lifting to OpenFreeMap. Its features are limited: a nicely styled map plus search over admin-area names.
- **streetzim** has far more features: search over POIs, streets and addresses, offline drive/walk/bike routing with GPS navigation, satellite imagery, terrain, and Wikipedia/Wikidata. It is also a large single-author system (about 119k tracked lines, 685 commits in 6.5 months). It has no CI, hardcoded local paths, custom binary formats, and operational tooling tied to the author's own infrastructure.
- **Recommendation: Option A.** Keep openzim/maps as the base and port streetzim's features one at a time, highest value per effort first. Adapting streetzim to Kiwix constraints would amount to a rewrite that deletes most of its code, and that ends up in the same place as Option A at higher risk. Section 6 has the reasoning and a proposed roadmap.

---

## 1. User-facing features

| Feature | openzim/maps | streetzim |
|---|---|---|
| Map rendering | MapLibre GL JS (vector) | MapLibre GL JS (vector); also an experimental Leaflet raster variant |
| Map style | `kiwix-light` (fork of OpenFreeMap Liberty) and `kiwix-dark`, chosen automatically from `prefers-color-scheme` | One hand-written style inline in the viewer (about 36 layers), light only |
| POI icons | Yes (OpenFreeMap sprites) | No: labels only, no `icon-image` |
| Labels | Style defaults; RTL text plugin bundled | Prefers `name:latin`, then `name_int`, then `name` |
| Low-zoom background | Natural Earth shaded-relief raster (WebP) | Natural Earth 1:50m lakes (embedded GeoJSON) |
| Satellite imagery | No | Optional layer toggle (Sentinel-2 Cloudless 2021, AVIF/WebP) |
| Terrain | No | Optional toggle: off / hillshade / 3D terrain |
| Search | Kiwix title suggestions over GeoNames **ADM1–ADM4** only; one redirect page per place, plus disambiguation pages | In-map search box over lazily loaded prefix chunks; Kiwix title and Xapian indexes; one detail page per feature with "Directions to here" / "View on map" |
| Search scope | Admin areas only. Populated places (GeoNames PPL) are filtered out, so cities that GeoNames records as PPL rather than ADM4 (most US cities, for example) are probably missing. No POIs, streets or addresses. | Places, streets, addresses (OSM, optionally Overture), POIs, peaks, parks, water, airports |
| Category browsing | No | On-map category chips (Food & Drink, Bars, Hotels, Museums, Parks, Health, Shops, Gas…), sub-filters, "Search this area", plus a `places.html` list app with distance sort |
| Routing | No | Offline drive / walk / bike routing |
| Navigation | No | GPS turn-by-turn "drive HUD": ETA, remaining distance, off-route detection, re-route |
| Wikipedia / Wikidata | No | Wikidata popups (population, description), Wiki panel, optional bundled Wikipedia articles and images |
| POI details | No | Websites, phones, socials and brands from Overture |
| Other UI | Scale bar (metric/imperial toggle), "home" button, About/credits page, remembers last view (localStorage), `#lat=&lon=&zoom=` deep links, clear error page when WebGL or Fetch is missing | `#map=`, `#dest=`, `#origin=`, `#label=` deep-link protocol, attribution dialog, `?debug=1` overlay |
| Outside Kiwix | — | PWA (`streetzim.web.app/drive`) that opens local ZIMs through a service worker, or streams them from archive.org via a range proxy for "preview before download" |

## 2. Software stack

| | openzim/maps | streetzim |
|---|---|---|
| Languages | Python 3.14, JS (Vite build) | Python 3.12, vanilla JS, Rust (one crate), a lot of Bash |
| ZIM writer | `zimscraperlib` 5.4 `Creator` on `libzim>=3.9` | `python-libzim`, **or** `streetzim-pack`, a Rust packer built on the author's `zimru` fork (selected with `--zim-builder`) |
| Python dependencies | pydantic, shapely, schedule, requests | pyosmium, rasterio/GDAL, numpy, mercantile, Pillow + AVIF plugin, mapbox-vector-tile, duckdb + pyarrow, zstandard, reverse_geocoder, internetarchive |
| External tools | None (tiles come prebuilt) | tilemaker, osmium-tool, optionally `xapianbuilder` |
| Front end | Vite 8, `maplibre-gl` 5.24 (npm), yarn 4, Node 26, ESLint, Prettier | Single-file HTML viewers (`index.html` is about 11k lines, `places.html` about 2.5k), a routing Web Worker, MapLibre 5.23 downloaded from unpkg at build time |
| Distribution | Docker image (ghcr.io), PyPI, Zimfarm `offliner-definition.json` | Scripts and `requirements.txt`; ZIMs uploaded to the Internet Archive and as torrents; Firebase-hosted catalog |
| QA | ruff, pyright (strict), pytest, codecov, pre-commit; GitHub Actions: QA, tests, and a daily Monaco build followed by `zimcheck` and integration tests | Large pytest and node test suite, golden search corpora, Puppeteer/Playwright smoke tests, `validate_zim.py`, a Python reference router for differential testing. **No CI configuration in the repo.** |
| Code license | GPL-3.0 | MIT |

## 3. Technical implementation

### 3.1 openzim/maps

The whole pipeline lives in `scraper/src/maps2zim/processor.py` and runs linearly:

1. **Tiles.** Reads `https://btrfs.openfreemap.com/files.txt`, picks the newest `areas/{planet|monaco}/…/tiles.mbtiles` and downloads it. Only `planet` and `monaco` are supported, so any regional ZIM starts from the whole planet file.
2. **Regional cut.** `--include-poly` takes `.poly` URLs (usually from Geofabrik), but `TileFilter` keeps every tile that intersects the polygons' **bounding box**, not the polygons themselves. The antimeridian is handled.
3. **Deduplication.** Walks OpenFreeMap's `tiles_shallow`/`tiles_data` tables. The first occurrence of each `tile_data_id` is written as a real entry, and every repeat becomes a ZIM **alias**, which collapses ocean and land-fill tiles. Tile data is gunzipped and then compressed by libzim.
4. **Zoom.** Source tiles stop at z14. `--max-zoom` can only trim, and the viewer overzooms to 18. The URL-fragment parser in `zimui/main.js` rejects zoom values above 14.
5. **Styles and assets.** At build time, style layers whose `source-layer` is missing from the MBTiles metadata are pruned, and URLs are rewritten to relative paths. A TileJSON 3.0 file is generated. Fonts, sprites and Natural Earth tiles come from OpenFreeMap tarballs, with fonts and Natural Earth deduplicated.
6. **Search.** Uses GeoNames (`allCountries` or a single country) filtered to ADM1–4, with zoom 6/8/10/12 by level. Duplicate names are disambiguated in two steps: by admin level when one entry is an ancestor of another, then by the shallowest unique ancestor or country from `hierarchy.txt` and `countryInfo.txt`. Each place becomes `search/<label>` (a meta-refresh to `index.html#lat=…&lon=…&zoom=…`). Full-text indexing is disabled; only the title index is used.
7. **Viewer.** A Vite-built MapLibre app. `transformRequest` and `transformStyle` make every URL absolute, which is robust under the different URL schemes of Kiwix readers. It reads center, zoom, bounds (`setMaxBounds`) and max zoom from `content/config.json`.
8. **Operations.** Progress JSON for Zimfarm, a download cache (`--dl`), and standard openZIM metadata and illustration handling. The language is fixed to `eng`.

### 3.2 streetzim

The main builder is `create_osm_zim.py` (about 8.2k lines). Around it sit more than 70 shell scripts and a `cloud/` directory with about 50 helper scripts.

1. **Tiles.** Input is a Geofabrik extract, a local PBF, or a planet PBF cut with `osmium extract -b`. tilemaker then runs with the OpenMapTiles Lua profile (z0–14, gzip, ocean from `coastline/water_polygons.shp`, which the scripts do not download). The resulting MBTiles are unpacked into ZIM entries. `--mbtiles` reuses tiles across regional builds.
2. **Viewer robustness.** A custom MapLibre protocol, `zimtile://`, adds a concurrency cap and retries. The reason: the Kiwix JS service worker and kiwix-desktop on Windows drop requests under load. `map-config.json` is also fetched with retries.
3. **Satellite.** EOX WMTS tiles (Sentinel-2 Cloudless 2021), re-encoded to AVIF (default quality 40) or WebP. Optionally stitched into 512 px tiles, with separate zoom caps for downloading and shipping.
4. **Terrain.** Copernicus GLO-30 COGs from public S3, falling back to GLO-90 where GLO-30 has no coverage. Built into a VRT and rendered as terrain-RGB (Mapbox encoding) WebP tiles up to z12 in a multiprocessing pool. Includes DEM validation, seam fixes, and an optional world VRT for low zooms.
5. **Routing graph.** Two streaming pyosmium passes: collect junctions, then split ways into edges. It uses a speed table per highway class (motorway 100 … steps 3 km/h), a "no motor vehicles" bit and one-way handling, and stores road names. The output is a custom binary format (**SZRG v4/v5**, optionally with separate geometries), which can be converted into spatial cells (**SZCI v3**) that the browser loads lazily. Big graphs can be chunked across several ZIM entries.
6. **In-browser router.** A* in a Web Worker, run as a chain:
   - admissible pass (up to 200 km),
   - weighted ×1.25,
   - greedy ×1.875,
   - two-pass highway fallback.

   It uses typed-array hash tables, a 64 MB cell budget and a closed-component check, all tuned to stay under iOS Safari's heap limit. A Python reference router serves as the oracle for differential tests.
7. **Search.**
   - Sources: features extracted from the vector tiles, plus OSM addresses from the PBF, optionally merged with Overture addresses and places (DuckDB against S3 parquet; name and coordinate matching; dead-URL filtering).
   - Output: sharded JSON: `search-data/<prefix>.json` with hot-prefix sub-buckets, `category-index/`, per-chip files, and geographic shards for large categories.
   - Also: a libzim or external Xapian index and `search/<slug>.html` detail pages.
8. **Enrichment.** Wikidata via SPARQL (cached), Wikipedia extracts, Q-ID → enwiki title resolution, and optionally full articles and images read from a local enwiki ZIM.
9. **ZIM tuning.** zstd level 22 and 2 MiB clusters. Routing blobs of 200 MB or more are stored uncompressed, because decompressing them in the WebView timed out. There are repackaging and in-place viewer-patching tools for published ZIMs (see `docs/zim-packaging-gotchas.md`).
10. **Operations.** Scripts for cloud build VMs, a spot-to-on-demand watcher, Internet Archive uploads, torrent generation, a Firebase catalog, and a Cloudflare/Firebase range proxy for online previews.

## 4. Data sources

| Source | openzim/maps | streetzim | License |
|---|---|---|---|
| OpenStreetMap | Indirectly, via OpenFreeMap's weekly planet MBTiles | Directly: Geofabrik extracts or a planet PBF, processed with tilemaker | ODbL |
| Tile schema | OpenMapTiles (OpenFreeMap build) | OpenMapTiles (tilemaker profile) | CC BY 4.0 |
| Fonts / sprites | OpenFreeMap | openmaptiles font CDN; no sprites | OFL / various |
| Low-zoom context | Natural Earth shaded relief | Natural Earth lakes; OSM water polygons | Public domain / ODbL |
| Region definition | `.poly` files (bbox only) | `--bbox` or a Geofabrik path | — |
| Place search | GeoNames (`allCountries`, `hierarchy`, `countryInfo`) | OSM features and addresses, Overture, GeoNames (labels only, via `reverse_geocoder`) | CC BY 4.0 (GeoNames); CDLA-Permissive-2.0 / various (Overture) |
| Satellite | — | EOX Sentinel-2 Cloudless **2021** | **CC BY-NC-SA 4.0 (non-commercial)** |
| Elevation | — | Copernicus GLO-30 / GLO-90 | Copernicus free and open license |
| Encyclopedic | — | Wikidata, Wikipedia | CC0 / CC BY-SA |

## 5. Strengths and weaknesses

### openzim/maps

**Strengths**
- Small, readable, strictly typed and tested.
- Already running inside the openZIM toolchain: Docker, Zimfarm, `zimcheck` in CI.
- Tile aliasing gives cheap deduplication.
- Maintained styles with icons and a dark theme.
- Robust URL handling across Kiwix readers.
- Graceful error page when WebGL or Fetch is missing.
- No heavy build tools, so builds are cheap and reproducible.

**Weaknesses**
- Search covers administrative areas only.
- The regional cut uses the bbox, which wastes space on irregular regions.
- The whole planet MBTiles must be downloaded even for a small region.
- No routing, terrain or POI data.
- Data freshness depends on OpenFreeMap's release cadence.

### streetzim

**Strengths**
- The richest offline-map experience available in a ZIM today.
- Routing is carefully engineered and validated against a reference router, with real measurements on iOS memory limits.
- Hard-won knowledge about Kiwix reader behaviour: service-worker request drops, compressed-cluster timeouts, zstd window sizes in browsers.
- Search sharding that scales to continents.
- The author has already upstreamed fixes to libzim.

**Weaknesses (technical debt)**
- **Code shape.** Monolithic files (an 8.2k-line builder, an 11k-line viewer HTML). Category chip rules are duplicated in three places and must be kept in sync by hand.
- **Custom binary formats.** Several versions (SZRG v4/v5, SZCI v3). The viewer baked into each ZIM must understand whichever version was shipped, and there are repackaging tools to migrate published ZIMs.
- **Reproducibility.** No CI in the repo. Many one-off scripts (`tmp/`, rebuild queues, rollout lists) with hardcoded local paths such as `/Users/jasontitus/...`. Depends on personal forks and side projects (`zimru`, `xapianbuilder`).
- **Heavy builds.** Continent-scale builds are documented as needing up to about 100 GB of RAM; tilemaker `--fast` needs 32 GB or more.
- **Outside openZIM scope.** Large parts are specific to the author's hosting: cloud VMs, archive.org, Firebase PWA, Cloudflare proxy.
- **Licensing.** The satellite layer is non-commercial and cannot be redistributed freely.
- **Stale docs.** The README contradicts the code in places (it says there is no coastline and only placeholder fonts).
- **Bus factor.** A single author.

## 6. Recommendation: add features to openzim/maps (Option A)

### 6.1 Why not Option B (adapt streetzim)

To become an openZIM scraper, streetzim would need all of the following:

1. Split the builder and viewer into modules, and add a proper front-end build.
2. Remove the hosting and operations layer (cloud VMs, archive.org, Firebase, Cloudflare, torrents, rollout and repack scripts), which is a large share of the repo.
3. Replace the Rust `zimru` packer and external `xapianbuilder` with `zimscraperlib`/`libzim`, or bring those dependencies under openZIM maintenance.
4. Freeze and document the binary routing formats, then drop the legacy versions.
5. Adopt openZIM conventions: CLI flags, metadata, illustration, Zimfarm progress file, `offliner-definition.json`, Docker image, typing and linting, CI.
6. Package tilemaker, osmium and GDAL into the Docker image, and make the builds fit Zimfarm worker resources.
7. Drop the non-commercial satellite layer, or replace it.

After those steps, what is left is essentially new code that keeps streetzim's *ideas* and some of its algorithms. That is Option A done the hard way: the starting point carries a lot that has to be deleted, and the maintainers would need to learn a large unfamiliar codebase. The single-author history also means the knowledge needed to refactor safely lives mostly in one person.

### 6.2 Why Option A is realistic

- **Compatible foundations.** Both tools use MapLibre GL JS and the **OpenMapTiles schema**. Several streetzim features (search feature extraction, category chips, the style's layer logic) work on the same tile data maps2zim already ships. They can be ported without a new data pipeline.
- **Licensing works.** streetzim is MIT. MIT code can be incorporated into GPL-3.0 openzim/maps with its attribution kept, so algorithms and viewer code can be reused rather than reimplemented.
- **Incremental delivery.** Each feature can ship behind a CLI flag, with its own tests and the existing daily CI. The map keeps working at every step.
- **Proven maintainability.** maps2zim's small, typed codebase and existing CI make each addition reviewable.

### 6.3 Proposed roadmap (highest value per effort first)

Effort is a rough relative size: S = a small PR, M = a feature spanning scraper and UI, L = a multi-PR project.

| # | Item | Source of inspiration | Effort | Notes |
|---|---|---|---|---|
| 1 | Include populated places (GeoNames PPL*, filtered by population or feature class) in search | — | S | Biggest user-visible gap; uses data maps2zim already downloads |
| 2 | Filter by the actual polygon, not its bbox (shapely is already a dependency) | — | S | Smaller regional ZIMs; do it for places too |
| 3 | Retry and concurrency wrapper for tile, glyph and sprite fetches | streetzim's `zimtile://` protocol | S | Fixes Kiwix JS service-worker request drops and first-fetch failures on Windows kiwix-desktop |
| 4 | Index POIs, streets and water/peak names extracted from the vector tiles, with sharded search JSON and an in-map search box | `extract_searchable_features`, `search-data/` sharding | M | No new data source; mind ZIM size on continent builds |
| 5 | Category browsing (chips) over the POI index | `cloud/chip_rules.py`, the chip rail | M | Keep a single source of truth for chip rules (a JSON generated at build time) instead of streetzim's three copies |
| 6 | Regional MBTiles without downloading the planet (tilemaker/planetiler on Geofabrik extracts, or range-reading the OpenFreeMap planet) | streetzim's tilemaker pipeline | M–L | Lower bandwidth and disk use on Zimfarm; a trade-off against build simplicity |
| 7 | Hillshade / 3D terrain from Copernicus DEM | `generate_terrain_tiles` | M–L | Optional flag; adds GDAL to the image; watch ZIM size |
| 8 | Offline routing (graph builder, web-worker A*) | `extract_routing_graph`, `routing-worker.js`, `docs/routing.md` | L | Needs PBF input (Geofabrik) and a **documented, versioned** graph format. Port streetzim's reference-router differential tests alongside it. Budget the memory limits of mobile WebViews. |
| 9 | Wikidata / Wikipedia enrichment, possibly cross-linking into Wikipedia ZIMs | `wikidata_cache.py`, title resolution | M | Fits the Kiwix ecosystem well (links between ZIMs) |
| 10 | Satellite imagery | — | — | **Not recommended** with the 2021 EOX layer (CC BY-NC-SA). Only reconsider with a freely licensed source; check whether an earlier EOX vintage has a more permissive license before relying on it. |

Items 1–3 are small, independent improvements that could land right away. Items 4–5 turn the map into something closer to a usable offline atlas. Items 7–9 are larger, optional capabilities that should each be scoped as their own project.

### 6.4 Working with the streetzim author

- Invite the author to review or co-design the ports, especially routing and search sharding.
- Ask them to upstream Kiwix reader robustness findings (see `docs/zim-packaging-gotchas.md`) to the Kiwix reader projects, where they help every ZIM.
- Keep streetzim as an independent producer of "maxi" ZIMs. Nothing here requires it to stop; Option A only means openZIM's own scraper does not depend on its codebase.

---

*Review based on reading both repositories' source code and documentation at the commits listed above. Line counts and feature claims come from the code at those commits and may change.*
