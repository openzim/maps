import datetime
import gzip
import html
import json
import logging
import re
import sqlite3
import tarfile
import time
import zipfile
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel
from schedule import every, run_pending
from zimscraperlib.download import save_large_file
from zimscraperlib.image import convert_image, resize_image
from zimscraperlib.image.conversion import convert_svg2png
from zimscraperlib.image.probing import format_for
from zimscraperlib.zim import Creator, metadata
from zimscraperlib.zim.dedup import Deduplicator
from zimscraperlib.zim.filesystem import (
    validate_file_creatable,
    validate_folder_writable,
)

from maps2zim.constants import (
    NAME,
    VERSION,
)
from maps2zim.context import Context
from maps2zim.download import stream_file
from maps2zim.errors import NoIllustrationFoundError
from maps2zim.tile_filter import TileFilter
from maps2zim.ui import ConfigModel
from maps2zim.zimconfig import ZimConfig

context = Context.get()
logger = context.logger

LOG_EVERY_SECONDS = 60
GEONAMES_REGION = "allCountries"  # Customize if needed when developing


class FilteringResult(BaseModel):
    dedup_ids: set[int] = set()
    redirects: list[tuple[str, str]] = []
    filtered_tile_count: int = 0


class SearchPlace(BaseModel):
    """A single place for search indexing."""

    geoname_id: str
    latitude: float
    longitude: float
    zoom: int
    label: str
    feature_code: str
    country_code: str


class SearchEntry(BaseModel):
    """Entry in places dictionary mapping name to list of places."""

    places: list[SearchPlace]


class Processor:
    """Generates ZIMs based on the user's configuration."""

    def __init__(self) -> None:
        """Initializes Processor."""

        self.stats_items_done = 0
        # we add 1 more items to process so that progress is not 100% at the beginning
        # when we do not yet know how many items we have to process and so that we can
        # increase counter at the beginning of every for loop, not minding about what
        # could happen in the loop in terms of exit conditions
        self.stats_items_total = 1

    def run(self) -> Path:
        """Generates a zim for a single document.

        Returns the path to the generated ZIM.
        """
        try:
            return self._run_internal()
        except Exception:
            logger.error(
                f"Problem encountered while processing "
                f"{context.current_thread_workitem}"
            )
            raise

    def _run_internal(self) -> Path:
        logger.setLevel(level=logging.DEBUG if context.debug else logging.INFO)

        if (
            context.area != "planet" or context.include_poly_urls
        ) and not context.default_view:
            logger.warning(
                "You should pass --default-view arg when using a custom --area or "
                "--include_poly_urls value(s), so that default map displayed in the UI "
                "is nice."
            )

        self.zim_config = ZimConfig(
            file_name=context.file_name,
            name=context.name,
            title=context.title,
            publisher=context.publisher,
            creator=context.creator,
            description=context.description,
            long_description=context.long_description,
            tags=context.tags,
            secondary_color=context.secondary_color,
        )

        # initialize all paths, ensuring they are ok for operation
        context.output_folder.mkdir(exist_ok=True)
        validate_folder_writable(context.output_folder)

        context.tmp_folder.mkdir(exist_ok=True)
        validate_folder_writable(context.tmp_folder)

        logger.info("Generating ZIM")

        # create first progress report and and a timer to update every 10 seconds
        self._report_progress()
        every(10).seconds.do(  # pyright: ignore[reportUnknownMemberType]
            self._report_progress
        )

        self.formatted_config = self.zim_config.format(
            {
                "name": self.zim_config.name,
                "period": datetime.date.today().strftime("%Y-%m"),
            }
        )
        zim_file_name = f"{self.formatted_config.file_name}.zim"
        zim_path = context.output_folder / zim_file_name

        if zim_path.exists():
            if context.overwrite_existing_zim:
                zim_path.unlink()
            else:
                logger.error(f"  {zim_path} already exists, aborting.")
                raise SystemExit(2)

        validate_file_creatable(context.output_folder, zim_file_name)

        logger.info(f"  Writing to: {zim_path}")

        logger.debug(f"User-Agent: {context.wm_user_agent}")

        creator = Creator(zim_path, "index.html")

        logger.info("  Fetching ZIM illustration...")
        zim_illustration = self._fetch_zim_illustration()

        logger.debug("Configuring metadata")
        creator.config_metadata(
            metadata.StandardMetadataList(
                Name=metadata.NameMetadata(self.formatted_config.name),
                Title=metadata.TitleMetadata(self.formatted_config.title),
                Publisher=metadata.PublisherMetadata(self.formatted_config.publisher),
                Date=metadata.DateMetadata(
                    datetime.datetime.now(tz=datetime.UTC).date()
                ),
                Creator=metadata.CreatorMetadata(self.formatted_config.creator),
                Description=metadata.DescriptionMetadata(
                    self.formatted_config.description
                ),
                LongDescription=(
                    metadata.LongDescriptionMetadata(
                        self.formatted_config.long_description
                    )
                    if self.formatted_config.long_description
                    else None
                ),
                # As of 2024-09-4 all documentation is in English.
                Language=metadata.LanguageMetadata(context.language_iso_639_3),
                Tags=(
                    metadata.TagsMetadata(self.formatted_config.tags)
                    if self.formatted_config.tags
                    else None
                ),
                Scraper=metadata.ScraperMetadata(f"{NAME} v{VERSION}"),
                Illustration_48x48_at_1=metadata.DefaultIllustrationMetadata(
                    zim_illustration.getvalue()
                ),
            ),
        )

        # Start creator early to detect problems early.
        with creator as creator:
            try:
                creator.add_item_for(
                    "favicon.ico",
                    content=self._fetch_favicon_from_illustration(
                        zim_illustration
                    ).getvalue(),
                )
                del zim_illustration

                self.run_with_creator(creator)
            except Exception:
                creator.can_finish = False
                raise

        if creator.can_finish:
            logger.info(f"ZIM creation completed, ZIM is at {zim_path}")
        else:
            logger.error("ZIM creation failed")

        # same reason than self.stats_items_done = 1 at the beginning, we need to add
        # a final item to complete the progress
        self.stats_items_done += 1
        self._report_progress()

        return zim_path

    def run_with_creator(self, creator: Creator):

        context.current_thread_workitem = "standard files"

        logger.info("  Storing configuration...")
        creator.add_item_for(
            "content/config.json",
            content=ConfigModel(
                secondary_color=self.zim_config.secondary_color,
                zim_name=self.formatted_config.name,
                center=(
                    [context.default_view[0], context.default_view[1]]
                    if context.default_view
                    else None
                ),
                zoom=context.default_view[2] if context.default_view else None,
            ).model_dump_json(by_alias=True, exclude_none=True),
        )

        count_zimui_files = len(list(context.zimui_dist.rglob("*")))
        if count_zimui_files == 0:
            raise OSError(f"No Vue.JS UI files found in {context.zimui_dist}")
        logger.info(
            f"Adding {count_zimui_files} Vue.JS UI files in {context.zimui_dist}"
        )
        self.stats_items_total += count_zimui_files
        for file in context.zimui_dist.rglob("*"):
            self.stats_items_done += 1
            run_pending()
            if file.is_dir():
                continue
            path = str(Path(file).relative_to(context.zimui_dist))
            logger.debug(f"Adding {path} to ZIM")
            if path == "index.html":  # Change index.html title and add to ZIM
                index_html_path = context.zimui_dist / path
                creator.add_item_for(
                    path=path,
                    content=index_html_path.read_text(encoding="utf-8").replace(
                        "<title>Vite App</title>",
                        f"<title>{self.formatted_config.title}</title>",
                    ),
                    mimetype="text/html",
                    is_front=True,
                )
            else:
                creator.add_item_for(
                    path=path,
                    fpath=file,
                    is_front=False,
                )

        context.current_thread_workitem = "about page"
        logger.info("  Generating about page...")
        self._write_about_html(creator)

        context.current_thread_workitem = "download fonts"
        self._fetch_fonts_tar_gz()

        context.current_thread_workitem = "write fonts"
        self._write_fonts(creator)

        context.current_thread_workitem = "download natural_earth"
        self._fetch_natural_earth_tar_gz()

        context.current_thread_workitem = "write natural_earth"
        self._write_natural_earth(creator)

        context.current_thread_workitem = "download sprites"
        self._fetch_sprites_tar_gz()

        context.current_thread_workitem = "write sprites"
        self._write_sprites(creator)

        context.current_thread_workitem = "download mbtiles"
        self._fetch_mbtiles()

        context.current_thread_workitem = "download styles"
        self._fetch_styles_tar_gz()

        context.current_thread_workitem = "write styles"
        self._write_styles(creator)

        context.current_thread_workitem = "tilejson"
        self._write_tilejson(creator)

        # Initialize tile filter if poly files or zoom filtering is specified
        tile_filter: TileFilter | None = None
        if context.include_poly_urls or context.include_up_to_zoom is not None:
            context.current_thread_workitem = "loading poly files"

            # Validate include_up_to_zoom if specified
            if context.include_up_to_zoom is not None:
                max_zoom = self._get_mbtiles_maxzoom()
                if context.include_up_to_zoom >= max_zoom:
                    raise ValueError(
                        f"--include_up_to_zoom ({context.include_up_to_zoom}) "
                        f"must be less than the maximum zoom in mbtiles ({max_zoom})"
                    )

            if context.include_poly_urls:
                logger.info("  Downloading and loading .poly file(s) for filtering")
            tile_filter = TileFilter(
                context.include_poly_urls or "",
                max_zoom_no_filter=context.include_up_to_zoom,
            )
            if context.include_poly_urls:
                logger.info(
                    f"  Loaded {tile_filter.polygon_count} polygon(s) for filtering"
                )
            if context.include_up_to_zoom is not None:
                logger.info(
                    f"  Including all tiles up to zoom "
                    f"level {context.include_up_to_zoom}"
                )

        context.current_thread_workitem = "download places data"
        self._fetch_geonames_zip()
        self._fetch_hierarchy_zip()
        self._fetch_country_info()

        context.current_thread_workitem = "process places data"
        places_dict = self._parse_geonames(tile_filter=tile_filter)
        # Build reverse mapping for hierarchy traversal
        id_to_place = {
            p.geoname_id: p for places in places_dict.values() for p in places
        }
        # Parse hierarchy and country info, then compute disambiguating labels
        child_to_parent = self._parse_hierarchy()
        iso_to_country = self._parse_country_info()
        if child_to_parent:
            self._compute_discriminating_labels(
                places_dict, id_to_place, child_to_parent, iso_to_country
            )
        self._write_places(creator, places_dict)

        # Free memory
        del places_dict
        del id_to_place
        del child_to_parent
        del iso_to_country

        # Count items for progress reporting (just totals, no filtering)
        dedupl_count, tile_count = self._count_mbtiles_items()
        self.stats_items_total += tile_count + dedupl_count

        # If filtering is active, collect filtered data in single pass
        # filtered_dedup_ids: set[int] | None = None
        # filtered_redirects: list[tuple[str, str]] | None = None
        filtering_results: FilteringResult | None = None
        if tile_filter:
            context.current_thread_workitem = "filtering tiles"
            # Add all tiles to progress total for filtering step
            self.stats_items_total += tile_count
            # Collect filtered data (dedup IDs and redirects) in single pass
            filtering_results = self._collect_filtered_tiles_data(
                tile_filter, tile_count
            )
            # In addition to read all tiles_shallow, we will have to create redirects
            self.stats_items_total += len(filtering_results.redirects)

        context.current_thread_workitem = "dedupl files"
        # Calculate total dedup count (use filtered if available, otherwise full)
        dedupl_total = (
            len(filtering_results.dedup_ids)
            if filtering_results is not None
            else dedupl_count
        )
        self._write_dedupl_files(
            creator,
            filtering_results.dedup_ids if filtering_results else None,
            dedupl_total,
        )

        context.current_thread_workitem = "tile files"
        # Calculate total tile count (use filtered if available, otherwise full)
        tile_total = (
            len(filtering_results.redirects)
            if filtering_results is not None
            else tile_count
        )
        self._write_title_files(
            creator,
            filtering_results.redirects if filtering_results else None,
            tile_total,
        )

    def _report_progress(self):
        """report progress to stats file"""

        logger.info(f"  Progress {self.stats_items_done} / {self.stats_items_total}")
        if not context.stats_filename:
            return
        progress = {
            "done": self.stats_items_done,
            "total": self.stats_items_total,
        }
        context.stats_filename.write_text(json.dumps(progress, indent=2))

    def _fetch_zim_illustration(self) -> BytesIO:
        """Fetch ZIM illustration, convert/resize and return it"""
        icon_url = context.illustration_url
        try:
            logger.debug(f"Downloading {icon_url} illustration")
            illustration_content = BytesIO()
            stream_file(
                icon_url,
                byte_stream=illustration_content,
            )
            illustration_format = format_for(illustration_content, from_suffix=False)
            png_illustration = BytesIO()
            if illustration_format == "SVG":
                logger.debug("Converting SVG illustration to PNG")
                convert_svg2png(illustration_content, png_illustration, 48, 48)
            elif illustration_format == "PNG":
                png_illustration = illustration_content
            else:
                logger.debug(f"Converting {illustration_format} illustration to PNG")
                convert_image(illustration_content, png_illustration, fmt="PNG")
            logger.debug("Resizing ZIM illustration")
            resize_image(
                src=png_illustration,
                width=48,
                height=48,
                method="cover",
            )
            return png_illustration
        except Exception as exc:
            raise NoIllustrationFoundError(
                f"Failed to retrieve illustration at {icon_url}"
            ) from exc

    def _fetch_favicon_from_illustration(self, illustration: BytesIO) -> BytesIO:
        """Return a converted version of the illustration into favicon"""
        favicon = BytesIO()
        convert_image(illustration, favicon, fmt="ICO")
        logger.debug("Resizing ZIM favicon")
        resize_image(
            src=favicon,
            width=32,
            height=32,
            method="cover",
        )
        return favicon

    def _fetch_fonts_tar_gz(self):
        """Download fonts tar.gz from OpenFreeMap if not already cached.

        If file already exists in assets folder, do nothing.
        Otherwise, download from https://assets.openfreemap.com/fonts/ofm.tar.gz
        """
        fonts_tar_gz_path = context.assets_folder / "ofm.tar.gz"

        # If file already exists, we're done
        if fonts_tar_gz_path.exists():
            logger.info(
                f"  using fonts tar.gz already available at {fonts_tar_gz_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info("  Downloading fonts from OpenFreeMap")
        save_large_file(
            "https://assets.openfreemap.com/fonts/ofm.tar.gz",
            fpath=fonts_tar_gz_path,
        )
        logger.info(f"  fonts tar.gz saved to {fonts_tar_gz_path}")

    def _write_fonts(self, creator: Creator):
        """Extract fonts from tar.gz and add to ZIM under 'fonts' folder.

        Extracts the cached fonts tar.gz file and adds all contents to the ZIM
        with paths under the 'fonts/' subfolder.
        """
        fonts_tar_gz_path = context.assets_folder / "ofm.tar.gz"

        logger.info("  Extracting fonts and adding to ZIM")

        # Create a deduplicator to detect duplicate natural earth tiles and save space
        deduplicator = Deduplicator(creator)
        deduplicator.filters.append(re.compile(".*"))

        # Extract and add fonts to ZIM
        with tarfile.open(fonts_tar_gz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    # Extract file content
                    f = tar.extractfile(member)
                    if f is not None:
                        content = f.read()
                        # Transform path from ofm/{fontstack}/{range}.pbf to
                        # fonts/{fontstack}/{range}.pbf
                        relative_path = member.name.replace("ofm/", "", 1)
                        zim_path = f"fonts/{relative_path}"
                        deduplicator.add_item_for(
                            path=zim_path,
                            content=content,
                        )

        logger.info("  Fonts added to ZIM")

    def _fetch_natural_earth_tar_gz(self):
        """Download natural_earth tar.gz from OpenFreeMap if not already cached.

        If file already exists in assets folder, do nothing.
        Otherwise, download from http://assets.openfreemap.com/natural_earth/ofm.tar.gz
        """
        natural_earth_tar_gz_path = context.assets_folder / "natural_earth.tar.gz"

        # If file already exists, we're done
        if natural_earth_tar_gz_path.exists():
            logger.info(
                "  using natural_earth tar.gz already available at "
                f"{natural_earth_tar_gz_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info("  Downloading natural_earth from OpenFreeMap")
        save_large_file(
            "https://assets.openfreemap.com/natural_earth/ofm.tar.gz",
            fpath=natural_earth_tar_gz_path,
        )
        logger.info(f"  natural_earth tar.gz saved to {natural_earth_tar_gz_path}")

    def _write_natural_earth(self, creator: Creator):
        """Extract natural_earth from tar.gz and add to ZIM.

        Extracts the cached natural_earth tar.gz file and adds all contents to the ZIM,
        transforming paths from ofm/ne2sr/ to natural_earth/ne2sr/.
        """
        natural_earth_tar_gz_path = context.assets_folder / "natural_earth.tar.gz"

        logger.info("  Extracting natural_earth and adding to ZIM")

        # Create a deduplicator to detect duplicate natural earth tiles and save space
        deduplicator = Deduplicator(creator)
        deduplicator.filters.append(re.compile(".*"))

        # Extract and add natural_earth to ZIM
        with tarfile.open(natural_earth_tar_gz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    # Extract file content
                    f = tar.extractfile(member)
                    if f is not None:
                        content = f.read()
                        # Transform path from ofm/ne2sr/... to natural_earth/ne2sr/...
                        relative_path = member.name.replace("ofm/ne2sr/", "", 1)
                        zim_path = f"natural_earth/ne2sr/{relative_path}"
                        deduplicator.add_item_for(
                            path=zim_path,
                            content=content,
                        )

        logger.info("  Natural_earth added to ZIM")

    def _fetch_geonames_zip(self):
        """Download and extract geonames data from ZIP if not already cached.

        Downloads from https://download.geonames.org/export/dump/{region}.zip,
        extracts the TSV file, and removes the ZIP file.
        The extracted TSV is cached in the assets folder for processing.
        """
        geonames_zip_path = context.assets_folder / f"{GEONAMES_REGION}.zip"
        geonames_txt_path = context.assets_folder / f"{GEONAMES_REGION}.txt"

        # If extracted TSV file already exists, we're done
        if geonames_txt_path.exists():
            logger.info(
                f"  using geonames {GEONAMES_REGION} TSV already available at "
                f"{geonames_txt_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"  Downloading geonames {GEONAMES_REGION} from geonames.org")
        geonames_url = (
            f"https://download.geonames.org/export/dump/{GEONAMES_REGION}.zip"
        )
        save_large_file(geonames_url, fpath=geonames_zip_path)
        logger.info(f"  geonames {GEONAMES_REGION} ZIP saved to {geonames_zip_path}")

        # Extract TSV file from ZIP
        logger.info(f"  Extracting {GEONAMES_REGION}.txt from ZIP")
        with zipfile.ZipFile(geonames_zip_path, "r") as zip_ref:
            # Extract the TSV file (named {region}.txt)
            txt_file_name = f"{GEONAMES_REGION}.txt"
            if txt_file_name not in zip_ref.namelist():
                raise OSError(
                    f"Could not find {txt_file_name} in geonames ZIP at "
                    f"{geonames_zip_path}"
                )
            zip_ref.extract(txt_file_name, context.assets_folder)

        # Remove ZIP file to save space
        geonames_zip_path.unlink()
        logger.info(f"  Removed ZIP file, keeping extracted TSV at {geonames_txt_path}")

    def _fetch_hierarchy_zip(self):
        """Download and extract geonames hierarchy data from ZIP if not already cached.

        Downloads from https://download.geonames.org/export/dump/hierarchy.zip,
        extracts the hierarchy.txt file, and removes the ZIP file.
        The extracted TSV is cached in the assets folder for processing.
        """
        hierarchy_zip_path = context.assets_folder / "hierarchy.zip"
        hierarchy_txt_path = context.assets_folder / "hierarchy.txt"

        # If extracted TSV file already exists, we're done
        if hierarchy_txt_path.exists():
            logger.info(
                f"  using hierarchy TSV already available at {hierarchy_txt_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info("  Downloading hierarchy from geonames.org")
        hierarchy_url = "https://download.geonames.org/export/dump/hierarchy.zip"
        save_large_file(hierarchy_url, fpath=hierarchy_zip_path)
        logger.info(f"  hierarchy ZIP saved to {hierarchy_zip_path}")

        # Extract TSV file from ZIP
        logger.info("  Extracting hierarchy.txt from ZIP")
        with zipfile.ZipFile(hierarchy_zip_path, "r") as zip_ref:
            if "hierarchy.txt" not in zip_ref.namelist():
                raise OSError(
                    f"Could not find hierarchy.txt in ZIP at {hierarchy_zip_path}"
                )
            zip_ref.extract("hierarchy.txt", context.assets_folder)

        # Remove ZIP file to save space
        hierarchy_zip_path.unlink()
        logger.info(
            f"  Removed ZIP file, keeping extracted TSV at {hierarchy_txt_path}"
        )

    def _fetch_country_info(self):
        """Download country info TSV from geonames if not already cached.

        Downloads from https://download.geonames.org/export/dump/countryInfo.txt
        and caches it in the assets folder.
        """
        country_info_path = context.assets_folder / "countryInfo.txt"

        # If file already exists, we're done
        if country_info_path.exists():
            logger.info(
                f"  using country info already available at {country_info_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info("  Downloading country info from geonames.org")
        save_large_file(
            "https://download.geonames.org/export/dump/countryInfo.txt",
            fpath=country_info_path,
        )
        logger.info(f"  country info saved to {country_info_path}")

    @staticmethod
    def _parse_country_info() -> dict[str, str]:
        """Parse country info TSV and return ISO code to country name mapping.

        Format of countryInfo.txt: ISO\t...\tCountry name (5th column)
        Comments start with #

        Returns:
            Dictionary mapping ISO code to country name.
        """
        country_info_path = context.assets_folder / "countryInfo.txt"

        if not country_info_path.exists():
            logger.info("  Country info not available, skipping country name lookup")
            return {}

        logger.info("  Parsing country info file")

        iso_to_country: dict[str, str] = {}

        try:
            with open(country_info_path, encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.rstrip("\n")
                    if not line_stripped or line_stripped.startswith("#"):
                        continue

                    parts = line_stripped.split("\t")
                    if len(parts) < 5:  # noqa: PLR2004
                        continue

                    iso_code = parts[0]
                    country_name = parts[4]

                    if iso_code and country_name:
                        iso_to_country[iso_code] = country_name

            logger.debug(f"  Loaded {len(iso_to_country)} countries")
            return iso_to_country

        except Exception as e:
            logger.error(f"  Error parsing country info: {e}")
            return {}

    def _fetch_sprites_tar_gz(self):
        """Download sprites tar.gz from OpenFreeMap if not already cached.

        If file already exists in assets folder, do nothing.
        Otherwise, download from https://assets.openfreemap.com/sprites/ofm_f384.tar.gz
        """
        sprites_tar_gz_path = context.assets_folder / "sprites.tar.gz"

        # If file already exists, we're done
        if sprites_tar_gz_path.exists():
            logger.info(
                f"  using sprites tar.gz already available at {sprites_tar_gz_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info("  Downloading sprites from OpenFreeMap")
        save_large_file(
            "https://assets.openfreemap.com/sprites/ofm_f384.tar.gz",
            fpath=sprites_tar_gz_path,
        )
        logger.info(f"  sprites tar.gz saved to {sprites_tar_gz_path}")

    def _write_sprites(self, creator: Creator):
        """Extract sprites from tar.gz and add to ZIM under 'sprites/ofm_f384' folder.

        Extracts the cached sprites tar.gz file and adds all contents to the ZIM,
        transforming paths from ofm_f384/ to sprites/ofm_f384/.
        """
        sprites_tar_gz_path = context.assets_folder / "sprites.tar.gz"

        logger.info("  Extracting sprites and adding to ZIM")

        # Extract and add sprites to ZIM
        with tarfile.open(sprites_tar_gz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    # Extract file content
                    f = tar.extractfile(member)
                    if f is not None:
                        content = f.read()
                        # Transform path from ofm_f384/... to sprites/ofm_f384/...
                        zim_path = f"sprites/{member.name}"
                        creator.add_item_for(
                            path=zim_path,
                            content=content,
                        )

        logger.info("  Sprites added to ZIM")

    def _fetch_styles_tar_gz(self):
        """Download styles tar.gz from OpenFreeMap if not already cached.

        If file already exists in assets folder, do nothing.
        Otherwise, download from https://assets.openfreemap.com/styles/ofm.tar.gz
        """
        styles_tar_gz_path = context.assets_folder / "styles.tar.gz"

        # If file already exists, we're done
        if styles_tar_gz_path.exists():
            logger.info(
                f"  using styles tar.gz already available at {styles_tar_gz_path}"
            )
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info("  Downloading styles from OpenFreeMap")
        save_large_file(
            "https://assets.openfreemap.com/styles/ofm.tar.gz",
            fpath=styles_tar_gz_path,
        )
        logger.info(f"  styles tar.gz saved to {styles_tar_gz_path}")

    def _write_styles(self, creator: Creator):
        """Extract styles from tar.gz and add to ZIM under 'styles' folder.

        Extracts the cached styles tar.gz file, modifies JSON files to use relative
        paths by replacing the domain with '.', filters layers based on available
        mbtiles layers, and adds all contents to the ZIM without the .json extension.
        """
        styles_tar_gz_path = context.assets_folder / "styles.tar.gz"
        available_layers = self._get_available_layers_from_mbtiles()

        logger.info("  Extracting styles and adding to ZIM")

        # Extract and add styles to ZIM
        with tarfile.open(styles_tar_gz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    # Extract file content
                    f = tar.extractfile(member)
                    if f is not None:
                        content = f.read()

                        # If it's a JSON file, process it
                        if member.name.endswith(".json"):
                            # Parse JSON
                            style_obj = json.loads(content.decode("utf-8"))

                            # Filter layers based on available mbtiles layers
                            style_obj = self._filter_style_layers(
                                style_obj, available_layers
                            )

                            # Replace domain with relative path
                            content = json.dumps(
                                style_obj, ensure_ascii=False, indent=2
                            ).encode("utf-8")
                            content = content.replace(
                                b"https://__TILEJSON_DOMAIN__", b"."
                            )

                        # Transform path from ofm/... to styles/...
                        relative_path = member.name.replace("ofm/", "", 1)
                        # Remove .json extension from style files
                        if relative_path.endswith(".json"):
                            relative_path = relative_path[:-5]
                        zim_path = f"styles/{relative_path}"
                        creator.add_item_for(
                            path=zim_path,
                            content=content,
                        )

        logger.info("  Styles added to ZIM")

    def _get_available_layers_from_mbtiles(self) -> set[str]:
        """Get set of available source-layer names from mbtiles metadata.

        Reads the mbtiles database and extracts the list of available layers
        from the vector_layers metadata.
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"

        # If mbtiles doesn't exist yet, return empty set
        if not mbtiles_path.exists():
            return set()

        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            metadata = dict(c.execute("select name, value from metadata").fetchall())
            if "json" in metadata:
                metadata_json = json.loads(metadata["json"])
                if "vector_layers" in metadata_json:
                    # Extract all layer IDs from vector_layers
                    return {layer["id"] for layer in metadata_json["vector_layers"]}
        finally:
            conn.close()

        return set()

    @staticmethod
    def _filter_style_layers(
        style_obj: dict[str, Any], available_layers: set[str]
    ) -> dict[str, Any]:
        """Remove layers from style that reference non-existent source-layers.

        Filters the style's layer array to only include layers that reference
        existing source-layers in the mbtiles database.
        """
        if "layers" not in style_obj or not available_layers:
            return style_obj

        filtered_layers: list[Any] = []
        for layer in style_obj["layers"]:
            # If layer has no source-layer, keep it (e.g., background layers)
            if "source-layer" not in layer:
                filtered_layers.append(layer)
            # If source-layer exists in mbtiles, keep it
            elif layer.get("source-layer") in available_layers:
                filtered_layers.append(layer)
            else:
                logger.debug(
                    f"Removing layer '{layer.get('id')}' - "
                    f"source-layer '{layer.get('source-layer')}' not found in mbtiles"
                )

        style_obj["layers"] = filtered_layers
        return style_obj

    def _count_mbtiles_items(self) -> tuple[int, int]:
        """Count total dedupl and tile items in mbtiles database.

        Returns:
            Tuple of (dedupl_count, tile_count)
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            logger.info("  Counting tiles")
            dedupl_count = c.execute("select count(*) from tiles_data").fetchone()[0]
            logger.info(f"  Found {dedupl_count} unique tile data entries")
            tile_count = c.execute("select count(*) from tiles_shallow").fetchone()[0]
            logger.info(f"  Found {tile_count} tiles")
            return dedupl_count, tile_count
        finally:
            conn.close()

    def _collect_filtered_tiles_data(
        self, tile_filter: TileFilter, total_tile_count: int
    ) -> FilteringResult:
        """Collect dedup IDs and redirect info for filtered tiles.

        Performs a single pass through tiles_shallow to collect dedup IDs
        and tile redirect information for tiles that pass the filter.
        Reports progress every 60 seconds.

        Args:
            tile_filter: TileFilter object for geographic filtering
            total_tile_count: Total number of tiles in tiles_shallow (to avoid recount)

        Returns:
            Dict with keys:
                - dedup_ids: set[int] of dedup IDs to include
                - redirects: list of (tile_path, dedup_path) tuples
                - filtered_tile_count: number of tiles included
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            logger.info(f"  Filtering {total_tile_count} tiles")

            results = FilteringResult()

            last_log_time = time.time()

            c.execute(
                "select zoom_level, tile_column, tile_row, tile_data_id "
                "from tiles_shallow"
            )

            for i, row in enumerate(c, start=1):
                z = row[0]
                x = row[1]
                y = self._flip_y(z, row[2])
                dedup_id = row[3]

                if tile_filter.tile_intersects(z, x, y):
                    results.dedup_ids.add(dedup_id)
                    results.filtered_tile_count += 1

                    # Store redirect information
                    tile_path = f"tiles/{z}/{x}/{y}.pbf"
                    dedup_path = f"dedupl/{self._dedupl_helper_path(dedup_id)}"
                    results.redirects.append((tile_path, dedup_path))

                self.stats_items_done += 1
                run_pending()

                # Log progress every 60 seconds
                current_time = time.time()
                if current_time - last_log_time > LOG_EVERY_SECONDS:
                    progress_pct = i / total_tile_count * 100
                    logger.info(
                        f"  Filtered {i}/{total_tile_count} tiles "
                        f"({results.filtered_tile_count} included, {progress_pct:.1f}%)"
                    )
                    last_log_time = current_time

            logger.info(
                f"  Filtering complete: {results.filtered_tile_count}/"
                f"{total_tile_count} tiles included ({len(results.dedup_ids)} unique "
                "dedup IDs)"
            )
            return results
        finally:
            conn.close()

    def _get_mbtiles_maxzoom(self) -> int:
        """Get the maximum zoom level from mbtiles metadata.

        Returns:
            Maximum zoom level (default 14 if not found)
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        if not mbtiles_path.exists():
            return 14  # Default if file doesn't exist yet

        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()
        try:
            metadata = dict(c.execute("select name, value from metadata").fetchall())
            if "maxzoom" in metadata:
                return int(metadata["maxzoom"])
            return 14  # Default
        finally:
            conn.close()

    def _fetch_mbtiles(self):
        """Ensure mbtiles file is available in assets folder

        If file is already there, do nothing.

        Otherwise, download https://btrfs.openfreemap.com/files.txt file to check
        latest version published and then download mbtiles file
        """
        context.current_thread_workitem = "mbtiles"

        # Determine the mbtiles filename based on area
        mbtiles_filename = f"{context.area}.mbtiles"
        mbtiles_path = context.assets_folder / mbtiles_filename

        # If file already exists, we're done
        if mbtiles_path.exists():
            logger.info(f"  using mbtiles file already available at {mbtiles_path}")
            return

        # Create assets folder if it doesn't exist
        context.assets_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"  Fetching mbtiles file for area: {context.area}")

        # Download files.txt to check available versions
        logger.debug("  Downloading file list from openfreemap")
        files_list_stream = BytesIO()
        stream_file(
            "https://btrfs.openfreemap.com/files.txt",
            byte_stream=files_list_stream,
        )
        files_list_stream.seek(0)
        files_list_content = files_list_stream.read().decode("utf-8")

        # Parse files list to find the latest mbtiles file for the area
        mbtiles_path_in_list = None
        latest_timestamp = None

        for line in files_list_content.strip().split("\n"):
            # Look for pattern: areas/{area}/{timestamp}_{suffix}/tiles.mbtiles
            if f"areas/{context.area}/" in line and "tiles.mbtiles" in line:
                # Extract timestamp from path:
                # areas/{area}/{YYYYMMDD_HHMMSS_XX}/tiles.mbtiles
                parts = line.split("/")
                if len(parts) >= 4:  # noqa: PLR2004
                    timestamp_part = parts[2]  # e.g., "20250907_231001_pt"
                    timestamp = timestamp_part.split("_")[0]  # e.g., "20250907"

                    # Keep the latest version (highest timestamp)
                    if latest_timestamp is None or timestamp > latest_timestamp:
                        latest_timestamp = timestamp
                        mbtiles_path_in_list = line

        if not mbtiles_path_in_list:
            raise OSError(
                f"Could not find tiles.mbtiles for area '{context.area}' "
                f"in files list from openfreemap"
            )

        # Construct the full URL
        mbtiles_url = f"https://btrfs.openfreemap.com/{mbtiles_path_in_list}"

        logger.info(f"  Downloading mbtiles from {mbtiles_url}")
        save_large_file(
            mbtiles_url,
            fpath=mbtiles_path,
        )
        logger.info(f"  mbtiles file saved to {mbtiles_path}")

    def _write_dedupl_files(
        self,
        creator: Creator,
        filtered_dedup_ids: set[int] | None,
        filtered_total: int,
    ):
        """Extract unique tile data from mbtiles and add to ZIM.

        Each unique tile is stored once in the dedupl folder structure.
        The path structure organizes IDs to keep max 1000 items per directory.
        Tiles are decompressed from gzip format before adding to ZIM.

        Args:
            creator: ZIM creator object
            filtered_dedup_ids: Optional set of dedup IDs to include (for filtering)
            filtered_total: Number of dedup items to process (avoids SELECT COUNT(*))
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            logger.info(f"  Adding {filtered_total} unique tile data entries to ZIM")

            last_log_time = time.time()
            c.execute("select tile_data_id, tile_data from tiles_data")
            processed_count = 0

            for row in c:
                dedupl_id = row[0]

                # Update progress (at the beginning for simplicity should we skip tile)
                self.stats_items_done += 1
                run_pending()
                processed_count += 1

                # Log progress if more than 1 minute since last log
                current_time = time.time()
                if current_time - last_log_time > LOG_EVERY_SECONDS:
                    logger.info(
                        f"  Added {processed_count}/{filtered_total} dedupl files "
                        f"({processed_count / filtered_total * 100:.1f}%)"
                    )
                    last_log_time = current_time

                # Skip this dedup if we're filtering and it's not in the filtered set
                if (
                    filtered_dedup_ids is not None
                    and dedupl_id not in filtered_dedup_ids
                ):
                    continue

                tile_data = row[1]

                # Decompress gzipped tile data
                try:
                    tile_data = gzip.decompress(tile_data)
                except OSError, gzip.BadGzipFile:
                    # If decompression fails, assume data is already uncompressed
                    pass

                # Calculate dedupl path using the same logic as openfreemap
                dedupl_path = self._dedupl_helper_path(dedupl_id)

                # Add to ZIM
                creator.add_item_for(
                    path=f"dedupl/{dedupl_path}",
                    content=tile_data,
                    mimetype="application/x-protobuf",
                )

        finally:
            conn.close()

    def _write_title_files(
        self,
        creator: Creator,
        filtered_redirects: list[tuple[str, str]] | None,
        total: int,
    ):
        """Create redirects from tile paths to dedupl files.

        Uses redirects instead of hardlinks to avoid duplication in ZIM.
        Each tile path points to the corresponding deduplicated tile data.

        Args:
            creator: ZIM creator object
            filtered_redirects: Optional list of pre-computed (tile_path, dedup_path)
                tuples when filtering is active. If provided, uses these directly
                instead of querying tiles_shallow again.
            total: Total number of tiles to process (avoids SELECT COUNT(*))
        """
        logger.info("  Creating tile redirects in ZIM")

        last_log_time = time.time()
        # If we have pre-computed redirects from filtering, use them directly
        if filtered_redirects is not None:

            for i, (tile_path, dedup_path) in enumerate(filtered_redirects, start=1):
                # Update progress
                self.stats_items_done += 1
                run_pending()

                # Log progress if more than 1 minute since last log
                current_time = time.time()
                if current_time - last_log_time > LOG_EVERY_SECONDS:
                    logger.info(
                        f"  Created {i}/{total} tile redirects "
                        f"({i / total * 100:.1f}%)"
                    )
                    last_log_time = current_time

                # Create redirect from tile to dedupl
                creator.add_redirect(tile_path, dedup_path)

            return

        # Fallback: query tiles_shallow if no pre-computed redirects
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            c.execute(
                "select zoom_level, tile_column, tile_row, tile_data_id "
                "from tiles_shallow"
            )
            created_count = 0

            for row in c:
                z = row[0]
                x = row[1]
                y_raw = row[2]
                y = self._flip_y(z, y_raw)
                dedupl_id = row[3]

                # Update progress (at the beginning for simplicity should we skip tile)
                self.stats_items_done += 1
                run_pending()
                created_count += 1

                # Log progress if more than 1 minute since last log
                current_time = time.time()
                if current_time - last_log_time > LOG_EVERY_SECONDS:
                    logger.info(
                        f"  Created {created_count}/{total} tile redirects "
                        f"({created_count / total * 100:.1f}%)"
                    )
                    last_log_time = current_time

                # Calculate paths
                tile_path = f"tiles/{z}/{x}/{y}.pbf"
                dedupl_path = f"dedupl/{self._dedupl_helper_path(dedupl_id)}"

                # Create redirect from tile to dedupl
                creator.add_redirect(tile_path, dedupl_path)

        finally:
            conn.close()

    @staticmethod
    def _dedupl_helper_path(dedupl_id: int) -> str:
        """Calculate dedupl path for a given ID.

        Organizes IDs into a 3-level directory structure to keep max
        1000 items per directory, allowing for 1 billion files.
        """
        str_num = f"{dedupl_id:09d}"
        l1 = str_num[:3]
        l2 = str_num[3:6]
        l3 = str_num[6:]
        return f"{l1}/{l2}/{l3}.pbf"

    @staticmethod
    def _flip_y(zoom: int, y: int) -> int:
        """Flip Y coordinate for tile indexing.

        Converts from TMS (Tile Map Service) convention to Web Mercator.
        """
        return (2**zoom - 1) - y

    def _write_tilejson(self, creator: Creator):
        """Generate TileJSON 3.0.0 file from mbtiles metadata.

        Reads metadata from the mbtiles database and generates a TileJSON file
        that describes the tileset for use by the web UI.
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            # Read metadata from mbtiles
            metadata = dict(c.execute("select name, value from metadata").fetchall())

            # Initialize TileJSON with version
            tilejson: dict[str, Any] = {"tilejson": "3.0.0"}

            # Extract and parse JSON metadata
            if "json" in metadata:
                metadata_json_key: dict[str, Any] = json.loads(metadata.pop("json"))
                tilejson["vector_layers"] = metadata_json_key.pop("vector_layers")
                if metadata_json_key:  # check that no more keys are left
                    raise ValueError(
                        f"Unexpected keys in json metadata: {metadata_json_key.keys()}"
                    )

            # Set tiles path - use relative path for ZIM
            # The tiles are located at tiles/{z}/{x}/{y}.pbf relative to ZIM root
            tilejson["tiles"] = ["./tiles/{z}/{x}/{y}.pbf"]

            # Set attribution
            tilejson["attribution"] = (
                '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> '
                '<a href="https://www.openmaptiles.org/" target="_blank">'
                "&copy; OpenMapTiles</a> "
                'Data from <a href="https://www.openstreetmap.org/copyright" '
                'target="_blank">OpenStreetMap</a>'
            )

            # Set bounds as list of floats
            if "bounds" in metadata:
                tilejson["bounds"] = [
                    float(n) for n in metadata.pop("bounds").split(",")
                ]

            # Set center as [lon, lat, zoom]
            if "center" in metadata:
                center = [float(n) for n in metadata.pop("center").split(",")]
                center[2] = 1  # Set default zoom level
                tilejson["center"] = center

            # Set description
            if "description" in metadata:
                tilejson["description"] = metadata.pop("description")

            # Set zoom levels
            if "maxzoom" in metadata:
                tilejson["maxzoom"] = int(metadata.pop("maxzoom"))
            if "minzoom" in metadata:
                tilejson["minzoom"] = int(metadata.pop("minzoom"))

            # Set name
            if "name" in metadata:
                tilejson["name"] = metadata.pop("name")

            # Set version
            if "version" in metadata:
                tilejson["version"] = metadata.pop("version")

            # Write TileJSON to ZIM
            tilejson_content = json.dumps(tilejson, ensure_ascii=False, indent=2)
            creator.add_item_for(
                path="planet",
                content=tilejson_content.encode("utf-8"),
                mimetype="application/json",
            )
            logger.info("  TileJSON file written to ZIM")
        finally:
            conn.close()

    def _parse_geonames(
        self, tile_filter: TileFilter | None = None
    ) -> dict[str, list[SearchPlace]]:
        """Parse geonames TSV file and return places grouped by name.

        Reads the geonames TSV file and builds a dictionary mapping place names to
        lists of places (filtered by ADM feature codes and optionally by geographic
        region if tile_filter is provided).

        Args:
            tile_filter: Optional TileFilter for geographic filtering. If provided,
                only places inside the filter regions are included.

        Returns:
            Dictionary mapping place names to lists of SearchPlace objects.
            Returns empty dict if data file is not available.
        """
        geonames_txt_path = context.assets_folder / f"{GEONAMES_REGION}.txt"

        if not geonames_txt_path.exists():
            logger.info("  Geonames data not available, skipping")
            return {}

        logger.info(f"  Processing geonames {GEONAMES_REGION} entries")

        # ADM feature codes to zoom level mapping
        adm_zoom_map = {
            "ADM1": 6,
            "ADM2": 8,
            "ADM3": 10,
            "ADM4": 12,
        }

        # Build dictionary: name -> list of places
        places_dict: dict[str, list[SearchPlace]] = {}

        try:
            with open(geonames_txt_path, encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.rstrip("\n")
                    if not line_stripped or line_stripped.startswith("#"):
                        continue

                    parts = line_stripped.split("\t")
                    if len(parts) < 9:  # noqa: PLR2004
                        continue

                    try:
                        geoname_id = parts[0]
                        name = parts[1]
                        # Remove leading/trailing slashes
                        name = name.strip("/")
                        # Replace multiple slashes with a single slash
                        name = re.sub(r"/+", "/", name)
                        feature_code = (
                            parts[7] if len(parts) > 7 else ""  # noqa: PLR2004
                        )
                        country_code = (
                            parts[8] if len(parts) > 8 else ""  # noqa: PLR2004
                        )

                        # Only consider ADM entries
                        if feature_code not in adm_zoom_map:
                            continue

                        latitude = float(parts[4])
                        longitude = float(parts[5])
                        zoom = adm_zoom_map[feature_code]

                        # Filter by geographic region if tile filter is specified
                        if tile_filter and not tile_filter.contains_point(
                            longitude, latitude
                        ):
                            continue

                        place = SearchPlace(
                            geoname_id=geoname_id,
                            latitude=latitude,
                            longitude=longitude,
                            zoom=zoom,
                            label=name,
                            feature_code=feature_code,
                            country_code=country_code,
                        )

                        if name not in places_dict:
                            places_dict[name] = []
                        places_dict[name].append(place)

                    except ValueError, IndexError:
                        logger.debug("  Skipped malformed geonames line")
                        continue

            logger.info(
                f"  Loaded {len(places_dict)} unique place names for a total of "
                f"{sum([len(places) for places in places_dict.values()])} places"
            )
            return places_dict

        except Exception as e:
            logger.error(f"  Error processing geonames: {e}")
            raise

    @staticmethod
    def _parse_hierarchy() -> dict[str, str]:
        """Parse geonames hierarchy TSV and return child_id -> parent_id mapping.

        Only includes entries where type == "ADM" to maintain administrative hierarchy.
        Format of hierarchy.txt: parentId\tchildId\ttype

        Returns:
            Dictionary mapping child_id to parent_id.
        """
        hierarchy_txt_path = context.assets_folder / "hierarchy.txt"

        if not hierarchy_txt_path.exists():
            logger.info("  Hierarchy data not available, skipping hierarchical labels")
            return {}

        logger.info("  Parsing hierarchy file")

        child_to_parent: dict[str, str] = {}

        try:
            with open(hierarchy_txt_path, encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.rstrip("\n")
                    if not line_stripped or line_stripped.startswith("#"):
                        continue

                    parts = line_stripped.split("\t")
                    if len(parts) < 3:  # noqa: PLR2004
                        continue

                    # Only keep ADM type entries
                    parent_id = parts[0]
                    child_id = parts[1]
                    rel_type = parts[2]

                    if rel_type == "ADM":
                        child_to_parent[child_id] = parent_id

            logger.debug(f"  Loaded {len(child_to_parent)} ADM hierarchy entries")
            return child_to_parent

        except Exception as e:
            logger.error(f"  Error parsing hierarchy: {e}")
            return {}

    @staticmethod
    def _compute_discriminating_labels(
        places_dict: dict[str, list[SearchPlace]],
        id_to_place: dict[str, SearchPlace],
        child_to_parent: dict[str, str],
        iso_to_country: dict[str, str] | None = None,
    ) -> None:
        """Update place.label with full hierarchy for ambiguous entries.

        For each group of places with the same name, includes the full ancestor
        hierarchy to disambiguate them. Updates place.label in-place.

        For places with unique names: no change
        For places with duplicate names: "place_name, ADM3, ADM2, ADM1, Country" (all
        ancestors + country)

        Args:
            places_dict: Dictionary mapping name to list of SearchPlace objects
            id_to_place: Dictionary mapping geoname_id to SearchPlace
            child_to_parent: Dictionary mapping child_id to parent_id from hierarchy
            iso_to_country: Optional mapping of ISO code to country name
        """
        if iso_to_country is None:
            iso_to_country = {}

        for _name, places in places_dict.items():
            if len(places) <= 1:
                continue  # No disambiguation needed

            # For each place, build full ancestor chain up to ADM1
            for place in places:
                ancestor_labels: list[str] = []
                current_id = place.geoname_id

                # Traverse up the hierarchy until ADM1 or end of chain
                while True:
                    parent_id = child_to_parent.get(current_id)
                    if parent_id is None:
                        break

                    parent_place = id_to_place.get(parent_id)
                    if parent_place is None:
                        break

                    ancestor_labels.append(parent_place.label)

                    # Stop after collecting ADM1
                    if parent_place.feature_code == "ADM1":
                        break

                    current_id = parent_id

                # Build the label: place_name, followed by all ancestors, and
                # country name
                label_parts = [place.label, *ancestor_labels]

                # Add country name if we have the country code and it's not already
                # in ancestors
                if place.country_code and place.country_code in iso_to_country:
                    country_name = iso_to_country[place.country_code]
                    # Only add if not already present and if there are ancestors
                    # (to distinguish)
                    if country_name not in ancestor_labels and ancestor_labels:
                        label_parts.append(country_name)

                if len(label_parts) > 1:
                    place.label = ", ".join(label_parts)

    def _write_places(
        self, creator: Creator, places_dict: dict[str, list[SearchPlace]]
    ) -> None:
        """Create indexed ZIM items for places from any source.

        Takes a dictionary of places grouped by name and creates:
        - Redirect HTML for unique place names
        - Disambiguation HTML for duplicate names
        - CSS file for styling (styles.css)

        Args:
            creator: ZIM creator object
            places_dict: Dictionary mapping place names to lists of SearchPlace objects
        """
        if not places_dict:
            logger.info("  No places to write, skipping")
            return

        # Add CSS file to ZIM
        assets = resources.files("maps2zim") / "assets"
        styles_path = Path(str(assets / "styles.css"))
        creator.add_item_for(
            path="content/styles.css",
            fpath=styles_path,
            mimetype="text/css",
        )

        # Setup progress tracking
        total_places = len(places_dict)
        self.stats_items_total += total_places
        last_log_time = time.time()
        redirect_count = 0
        disamb_count = 0

        for i, (name, places) in enumerate(places_dict.items(), start=1):
            self.stats_items_done += 1
            run_pending()

            # Log progress if more than 1 minute since last log
            current_time = time.time()
            if current_time - last_log_time > LOG_EVERY_SECONDS:
                logger.info(
                    f"  Writing places {i}/{total_places} "
                    f"({i / total_places * 100:.1f}%)"
                )
                self._report_progress()
                last_log_time = current_time

            path = f"search/{name}"
            root_prefix = "../" * path.count("/")
            if len(places) == 1:
                # Single place: create redirect
                place = places[0]
                redirect_html = self._create_redirect_html(place, root_prefix)
                creator.add_item_for(
                    path=path,
                    content=redirect_html.encode("utf-8"),
                    mimetype="text/html",
                    title=name,
                )
                redirect_count += 1
            else:
                # Multiple places: create disambiguation page
                disamb_html = self._create_disambiguation_html(
                    name, places, root_prefix
                )
                creator.add_item_for(
                    path=path,
                    content=disamb_html.encode("utf-8"),
                    mimetype="text/html",
                    title=name,
                )
                disamb_count += 1

        logger.info(
            f"  Added {redirect_count} redirects and {disamb_count} "
            f"disambiguation pages"
        )
        self._report_progress()

    @staticmethod
    def _create_redirect_html(place: SearchPlace, root_prefix: str) -> str:
        """Create a redirect HTML that redirects to the map viewer at the place."""
        map_url = (
            f"{root_prefix}index.html#lat={place.latitude}&lon={place.longitude}"
            f"&zoom={place.zoom}"
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <title>{place.label}</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="1;URL='{map_url}'" />
    <link rel="stylesheet" href="{root_prefix}content/styles.css">
</head>
<body>
    <div class="container">
        <div class="icon">🗺️</div>
        <h1>Opening Map</h1>
        <div class="subtitle">Navigating to your location...</div>
        <div class="location">{place.label}</div>
        <div class="spinner"></div>
        <div class="fallback">
            If you're not redirected, <a href="{map_url}">click here to open the map</a>
        </div>
    </div>
</body>
</html>"""

    @staticmethod
    def _create_disambiguation_html(
        name: str, places: list[SearchPlace], root_prefix: str
    ) -> str:
        """Create a disambiguation HTML with links to each place."""
        places_html = "\n".join(
            f'<a href="{root_prefix}index.html#lat={place.latitude}'
            f'&lon={place.longitude}&zoom={place.zoom}" class="place-item"> '
            f'<div class="place-label">{place.label}</div> '
            f'<div class="place-coords">Lat: {place.latitude:.2f}, '
            f"Lon: {place.longitude:.2f}</div> "
            "</a>"
            for place in places
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <title>{name} - Disambiguation</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="{root_prefix}content/styles.css">
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="icon">🌍</div>
            <h1>{name}</h1>
            <div class="subtitle">Disambiguation</div>
            <div class="description">
                This place name refers to <span class="count">{len(places)}</span>
                different locations.
            </div>
        </div>
        <div class="places-list">
{places_html}
        </div>
    </div>
</body>
</html>"""

    @staticmethod
    def _uses_geofabrik_polys(include_poly_urls: str | None) -> bool:
        """Check if any of the poly URLs is from Geofabrik.

        Args:
            include_poly_urls: Comma-separated URLs of .poly files

        Returns:
            True if at least one URL has 'geofabrik.de' in hostname
        """
        if not include_poly_urls:
            return False
        for url in include_poly_urls.split(","):
            hostname = urlparse(url.strip()).hostname or ""
            if "geofabrik.de" in hostname:
                return True
        return False

    @staticmethod
    def _create_about_html(
        title: str,
        description: str,
        long_description: str | None,
        zim_creator: str,
        publisher: str,
        *,
        include_geofabrik: bool,
    ) -> str:
        """Create an about.html page for the ZIM.

        Args:
            title: ZIM title
            description: ZIM description (short)
            long_description: ZIM long description (optional)
            zim_creator: Creator name
            publisher: Publisher name
            include_geofabrik: Whether to include Geofabrik in credits

        Returns:
            HTML string for about.html page
        """
        # HTML-escape all user inputs to prevent XSS
        title_escaped = html.escape(title)
        description_escaped = html.escape(description)
        long_desc_escaped = html.escape(long_description) if long_description else ""
        creator_escaped = html.escape(zim_creator)
        publisher_escaped = html.escape(publisher)

        # Build creator/publisher section
        if zim_creator == publisher:
            meta_rows = (
                '<div class="meta-item"><span class="meta-label">'
                "Created &amp; published by</span>"
                f'<span class="meta-value">{creator_escaped}</span></div>'
            )
        else:
            meta_rows = (
                '<div class="meta-item"><span class="meta-label">'
                "Created by</span>"
                f'<span class="meta-value">{creator_escaped}</span></div>'
                '<div class="meta-item"><span class="meta-label">'
                "Published by</span>"
                f'<span class="meta-value">{publisher_escaped}</span></div>'
            )

        long_desc_html = (
            f'<p class="description">{long_desc_escaped}</p>'
            if long_description
            else ""
        )

        # Build credits
        credits_list: list[tuple[str, str, str, str]] = [
            (
                "🗺️",
                "OpenStreetMap",
                "https://www.openstreetmap.org",
                "The map data in this ZIM is made available by the "
                "OpenStreetMap project and its community of contributors, "
                "licensed under the Open Database License (ODbL).",
            ),
            (
                "🌐",
                "OpenFreeMap",
                "https://openfreemap.org",
                "Pre-processed vector tiles, map styles, fonts, and "
                "sprites used in this ZIM are provided by OpenFreeMap.",
            ),
            (
                "🌍",
                "Natural Earth",
                "https://www.naturalearthdata.com",
                "Background raster map imagery is derived from Natural Earth data.",
            ),
            (
                "📍",
                "GeoNames",
                "https://www.geonames.org",
                "Place names and geographic coordinates for the search "
                "index are sourced from the GeoNames geographical database.",
            ),
        ]
        if include_geofabrik:
            credits_list.append(
                (
                    "📁",
                    "Geofabrik",
                    "https://www.geofabrik.de",
                    "Region definition files (.poly) used to filter this "
                    "ZIM's content to specific geographic areas are "
                    "provided by Geofabrik GmbH.",
                )
            )
        credits_list.append(
            (
                "📦",
                "Kiwix / openZIM",
                "https://www.kiwix.org",
                "This offline package was created using the openZIM "
                "scraper tools and the Kiwix ZIM format.",
            )
        )

        credits_html = "\n".join(
            f"""<div class="credit-item">
                <div class="credit-logo">{logo}</div>
                <div class="credit-content">
                    <div class="credit-name"><a href="{url}" """
            f"""target="_blank">{name}</a></div>
                    <div class="credit-desc">{desc}</div>
                </div>
            </div>"""
            for logo, name, url, desc in credits_list
        )

        page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>About - {title_escaped}</title>
    <link rel="stylesheet" href="../content/styles.css">
</head>
<body>
    <div class="container" style="max-width:700px">
        <div class="header">
            <div class="icon">🗺️</div>
            <h1>{title_escaped}</h1>
            <p class="subtitle">{description_escaped}</p>
        </div>

        <div class="section">
            {long_desc_html}
            {meta_rows}
        </div>

        <div class="section">
            <div class="section-title">Credits &amp; Attribution</div>
            {credits_html}
        </div>
    </div>
</body>
</html>"""
        return page_html

    def _write_about_html(self, creator: Creator) -> None:
        """Generate and add about.html to the ZIM."""
        title = self.formatted_config.title
        description = self.formatted_config.description
        long_description = self.formatted_config.long_description
        zim_creator = self.formatted_config.creator
        publisher = self.formatted_config.publisher

        # Check if Geofabrik should be credited
        include_geofabrik = self._uses_geofabrik_polys(context.include_poly_urls)

        # Generate HTML
        about_html = self._create_about_html(
            title=title,
            description=description,
            long_description=long_description,
            zim_creator=zim_creator,
            publisher=publisher,
            include_geofabrik=include_geofabrik,
        )

        # Add to ZIM
        creator.add_item_for(
            path="content/about.html",
            content=about_html.encode("utf-8"),
            mimetype="text/html",
            is_front=True,
            title=f"About - {title}",
        )
