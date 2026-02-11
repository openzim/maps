import datetime
import json
import logging
import sqlite3
import time
from io import BytesIO
from pathlib import Path

from schedule import every, run_pending
from zimscraperlib.image import convert_image, resize_image
from zimscraperlib.image.conversion import convert_svg2png
from zimscraperlib.image.probing import format_for
from zimscraperlib.zim import Creator, metadata
from zimscraperlib.zim.filesystem import (
    validate_file_creatable,
    validate_folder_writable,
)
from zimscraperlib.zim.indexing import IndexData

from maps2zim.constants import (
    NAME,
    VERSION,
)
from maps2zim.context import Context
from maps2zim.download import stream_file
from maps2zim.errors import NoIllustrationFoundError
from maps2zim.ui import ConfigModel
from maps2zim.zimconfig import ZimConfig

context = Context.get()
logger = context.logger


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
                secondary_color=self.zim_config.secondary_color
            ).model_dump_json(by_alias=True),
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

        context.current_thread_workitem = "download mbtiles"
        self._fetch_mbtiles()

        # Count items for progress reporting
        dedupl_count, tile_count = self._count_mbtiles_items()
        self.stats_items_total += dedupl_count + tile_count

        context.current_thread_workitem = "dedupl files"
        self._write_dedupl_files(creator)

        context.current_thread_workitem = "tile files"
        self._write_title_files(creator)
        

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

    def _add_indexing_item_to_zim(
        self,
        creator: Creator,
        title: str,
        content: str,
        fname: str,
        zimui_redirect: str,
    ):
        """Add a 'fake' item to the ZIM, with proper indexing data

        This is mandatory for suggestions and fulltext search to work properly, since
        we do not really have pages to search for.

        This item is a very basic HTML which automatically redirect to proper Vue.JS URL
        """

        redirect_url = f"../index.html#/{zimui_redirect}"
        html_content = (
            f"<html><head><title>{title}</title>"
            f'<meta http-equiv="refresh" content="0;URL=\'{redirect_url}\'" />'
            f"</head><body></body></html>"
        )

        logger.debug(f"Adding {fname} to ZIM index")
        creator.add_item_for(
            title=title,
            path="index/" + fname,
            content=html_content.encode("utf-8"),
            mimetype="text/html",
            index_data=IndexData(title=title, content=content),
        )

    def _count_mbtiles_items(self) -> tuple[int, int]:
        """Count total dedupl and tile items in mbtiles database.

        Returns:
            Tuple of (dedupl_count, tile_count)
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            dedupl_count = c.execute("select count(*) from tiles_data").fetchone()[0]
            tile_count = c.execute("select count(*) from tiles_shallow").fetchone()[0]
            return dedupl_count, tile_count
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
                # Extract timestamp from path: areas/{area}/{YYYYMMDD_HHMMSS_XX}/tiles.mbtiles
                parts = line.split("/")
                if len(parts) >= 4:
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
        stream_file(
            mbtiles_url,
            fpath=mbtiles_path,
        )
        logger.info(f"  mbtiles file saved to {mbtiles_path}")

    def _write_dedupl_files(self, creator: Creator):
        """Extract unique tile data from mbtiles and add to ZIM.

        Each unique tile is stored once in the dedupl folder structure.
        The path structure organizes IDs to keep max 1000 items per directory.
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            total = c.execute("select count(*) from tiles_data").fetchone()[0]
            logger.info(f"  Adding {total} unique tile data entries to ZIM")

            last_log_time = time.time()
            c.execute("select tile_data_id, tile_data from tiles_data")
            for i, row in enumerate(c, start=1):
                dedupl_id = row[0]
                tile_data = row[1]

                # Calculate dedupl path using the same logic as openfreemap
                dedupl_path = self._dedupl_helper_path(dedupl_id)

                # Add to ZIM
                creator.add_item_for(
                    path=f"dedupl/{dedupl_path}",
                    content=tile_data,
                    mimetype="application/x-protobuf",
                )

                # Update progress
                self.stats_items_done += 1
                run_pending()

                # Log progress if more than 1 minute since last log
                current_time = time.time()
                if current_time - last_log_time > 60:
                    logger.info(
                        f"  Added {i}/{total} dedupl files "
                        f"({i / total * 100:.1f}%)"
                    )
                    last_log_time = current_time
        finally:
            conn.close()

    def _write_title_files(self, creator: Creator):
        """Create redirects from tile paths to dedupl files.

        Uses redirects instead of hardlinks to avoid duplication in ZIM.
        Each tile path points to the corresponding deduplicated tile data.
        """
        mbtiles_path = context.assets_folder / f"{context.area}.mbtiles"
        conn = sqlite3.connect(mbtiles_path)
        c = conn.cursor()

        try:
            total = c.execute("select count(*) from tiles_shallow").fetchone()[0]
            logger.info(f"  Creating {total} tile redirects in ZIM")

            last_log_time = time.time()
            c.execute(
                "select zoom_level, tile_column, tile_row, tile_data_id from tiles_shallow"
            )
            for i, row in enumerate(c, start=1):
                z = row[0]
                x = row[1]
                y = self._flip_y(z, row[2])
                dedupl_id = row[3]

                # Calculate paths
                tile_path = f"tiles/{z}/{x}/{y}.pbf"
                dedupl_path = f"dedupl/{self._dedupl_helper_path(dedupl_id)}"

                # Create redirect from tile to dedupl
                creator.add_redirect(tile_path, dedupl_path)

                # Update progress
                self.stats_items_done += 1
                run_pending()

                # Log progress if more than 1 minute since last log
                current_time = time.time()
                if current_time - last_log_time > 60:
                    logger.info(
                        f"  Created {i}/{total} tile redirects "
                        f"({i / total * 100:.1f}%)"
                    )
                    last_log_time = current_time
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