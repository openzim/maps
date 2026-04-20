import argparse
import threading
from pathlib import Path

from zimscraperlib.constants import (
    MAXIMUM_DESCRIPTION_METADATA_LENGTH,
    MAXIMUM_LONG_DESCRIPTION_METADATA_LENGTH,
    RECOMMENDED_MAX_TITLE_LENGTH,
)
from zimscraperlib.download import get_session

from maps2zim.constants import (
    NAME,
    VERSION,
)
from maps2zim.context import MAPS_TMP, Context


def parse_default_view(value: str) -> tuple[float, float, float | None]:
    """Parse --default-view argument as latitude,longitude,zoom.

    Args:
        value: comma-separated string of 2 or 3 floats

    Returns:
        Tuple of (latitude, longitude, zoom) as floats
        zoom can be None if not set

    Raises:
        argparse.ArgumentTypeError: if format is invalid
    """
    parts = value.split(",")
    if len(parts) not in [2, 3]:
        raise argparse.ArgumentTypeError(
            "--default-view requires 2 or 3 comma-separated values "
            "(latitude,longitude) or (latitude,longitude,zoom), got "
            f"{len(parts)}"
        )
    try:
        lat, lon, zoom = (
            float(parts[0]),
            float(parts[1]),
            float(parts[2]) if len(parts) > 2 else None,  # noqa: PLR2004
        )
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--default-view values must all be floats, got: {value!r}"
        ) from None
    return (lat, lon, zoom)


def prepare_context(raw_args: list[str], tmpdir: str) -> None:
    """Initialize scraper context from command line arguments"""

    parser = argparse.ArgumentParser(
        prog=NAME,
    )

    parser.add_argument(
        "--creator",
        help=f"Name of content creator. Default: {Context.creator!s}",
    )

    parser.add_argument(
        "--publisher",
        help=f"Publisher name. Default: {Context.publisher!s}",
    )

    parser.add_argument(
        "--file-name",
        help="Custom file name format for individual ZIMs. "
        f"Default: {Context.file_name!s}",
    )

    parser.add_argument(
        "--name",
        help="Name of the ZIM.",
        required=True,
    )

    parser.add_argument(
        "--title",
        help=f"Title of the ZIM. Value must not be longer than "
        f"{RECOMMENDED_MAX_TITLE_LENGTH} chars.",
        required=True,
    )

    parser.add_argument(
        "--description",
        help="Description of the ZIM. Value must not be longer than "
        f"{MAXIMUM_DESCRIPTION_METADATA_LENGTH} chars.",
        required=True,
    )

    parser.add_argument(
        "--long-description",
        help="Long description of the ZIM. Value must not be longer than "
        f"{MAXIMUM_LONG_DESCRIPTION_METADATA_LENGTH} chars.",
    )

    # Due to https://github.com/python/cpython/issues/60603 defaulting an array in
    # argparse doesn't work so we expose the underlying semicolon delimited string.
    parser.add_argument(
        "--tags",
        help="A semicolon (;) delimited list of tags to add to the ZIM.",
        type=lambda x: [tag.strip() for tag in x.split(";")],
    )

    parser.add_argument(
        "--secondary-color",
        help="Secondary (background) color of ZIM UI. Default: "
        f"{Context.secondary_color!s}",
    )

    parser.add_argument(
        "--version",
        help="Display scraper version and exit",
        action="version",
        version=VERSION,
    )

    parser.add_argument(
        "--overwrite",
        help="Do not fail if ZIM already exists, overwrite it",
        action="store_true",
        dest="overwrite_existing_zim",
    )

    parser.add_argument(
        "--output",
        help="Output folder for ZIMs. Default: /output",
        type=Path,
        dest="output_folder",
    )

    parser.add_argument(
        "--tmp",
        help="Temporary folder for cache, intermediate files, ...",
        type=Path,
        dest="tmp_folder",
    )

    parser.add_argument(
        "--dl",
        help="Folder folder to fetch / store downloaded files (can be reused across "
        "runs)",
        type=Path,
        dest="dl_folder",
    )

    parser.add_argument("--debug", help="Enable verbose output", action="store_true")

    parser.add_argument(
        "--zimui-dist",
        type=Path,
        help=(
            "Dev option to customize directory containing Vite build output from the "
            "ZIM UI Vue.JS application"
        ),
    )

    parser.add_argument(
        "--stats-filename",
        type=Path,
        help="Path to store the progress JSON file to.",
    )

    parser.add_argument(
        "--illustration-url",
        help="URL to illustration to use for ZIM illustration and favicon",
    )

    parser.add_argument(
        "--contact-info",
        help="Contact information to pass in User-Agent headers",
    )

    parser.add_argument(
        "--area",
        help=f"Area to download, either planet or monaco. Default: {Context.area!s}",
    )

    parser.add_argument(
        "--include-poly",
        help="Comma-separated URL(s) of .poly file(s) defining regions to include. "
        "Files will be downloaded and only tiles intersecting these regions will be "
        "included in the ZIM.",
        dest="include_poly_urls",
    )

    parser.add_argument(
        "--default-view",
        type=parse_default_view,
        help="Default map view as latitude,longitude,zoom (e.g. 43.731,7.416,12). "
        "Sets the initial center and zoom level of the map when UI loads. zoom value "
        "is optional, you can pass only latitude,longitude (map will be zoomed out as "
        "much as possible).",
        dest="default_view",
    )

    parser.add_argument(
        "--geonames-region",
        help="Geonames region to download (e.g. 'allCountries', 'FR', 'US'). "
        "Default: allCountries",
        dest="geonames_region",
    )

    parser.add_argument(
        "--zim-workers",
        type=int,
        help="Number of worker threads for the ZIM creator. Default: libzim default",
        dest="zim_workers",
    )

    parser.add_argument(
        "--max-zoom",
        type=int,
        choices=range(0, 19),
        metavar="{0..18}",
        help="Maximum zoom level of tiles to include in the ZIM. "
        "Tiles with zoom level higher than this value will be excluded. "
        "Must be between 0 and 18 (inclusive). "
        "Default: no limit (all zoom levels included).",
        dest="max_zoom",
    )

    args = parser.parse_args(raw_args)

    # Ignore unset values so they do not override the default specified in Context
    args_dict = {key: value for key, value in args._get_kwargs() if value}

    # initialize some context properties that are "dynamic" (i.e. not constant
    # values like an int, a string, ...)
    if not args_dict.get("tmp_folder", None):
        if MAPS_TMP:
            args_dict["tmp_folder"] = Path(MAPS_TMP)
        else:
            args_dict["tmp_folder"] = Path(tmpdir)

    if not args_dict.get("dl_folder", None):
        args_dict["dl_folder"] = args_dict["tmp_folder"] / "dl"

    args_dict["_current_thread_workitem"] = threading.local()
    args_dict["web_session"] = get_session()

    Context.setup(**args_dict)
