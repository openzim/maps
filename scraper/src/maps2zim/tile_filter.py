"""Tile filtering based on geographic regions defined in .poly files."""

import math
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union
from zimscraperlib.download import save_large_file

from maps2zim.context import Context

context = Context.get()
logger = context.logger

MIN_COORD_PARTS = 2


def download_poly_file(url: str, dest_folder: Path) -> Path:
    """Download a .poly file from URL.

    Args:
        url: URL to download from
        dest_folder: Folder to save the file to

    Returns:
        Path to the downloaded file
    """
    dest_folder.mkdir(parents=True, exist_ok=True)

    # Extract filename from URL
    filename = url.rsplit("/", maxsplit=1)[-1]
    if not filename.endswith(".poly"):
        filename = f"{filename}.poly"

    filepath = dest_folder / filename

    logger.debug(f"Downloading .poly file from {url}")
    save_large_file(url, fpath=filepath)
    logger.debug(f"Downloaded .poly file to {filepath}")

    return filepath


def parse_poly_file(poly_path: Path) -> Polygon:
    """Parse a .poly file and return a Shapely Polygon.

    .poly files use the format:
        AREA_NAME
        POLYGON_NAME
           lon1    lat1
           lon2    lat2
           ...
        END
        END

    Args:
        poly_path: Path to .poly file

    Returns:
        Shapely Polygon object

    Raises:
        ValueError: If the .poly file format is invalid
    """
    if not poly_path.exists():
        raise FileNotFoundError(f"Poly file not found: {poly_path}")

    with open(poly_path, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        raise ValueError("Empty .poly file")

    polygons: list[Polygon] = []
    i = 0

    # Skip first line (area name)
    i += 1

    while i < len(lines):
        line = lines[i]

        # Check if this is a polygon name line (before coordinates)
        if line == "END":
            break

        # Skip polygon name
        i += 1
        coords: list[tuple[float, float]] = []

        # Read polygon coordinates until END
        while i < len(lines) and lines[i] != "END":
            parts = lines[i].split()
            if len(parts) >= MIN_COORD_PARTS:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    coords.append((lon, lat))
                except ValueError as e:
                    raise ValueError(
                        f"Invalid coordinate in {poly_path} line {i}: {lines[i]}"
                    ) from e
            i += 1

        if coords:
            polygons.append(Polygon(coords))
        else:
            raise ValueError(f"No coordinates found in polygon starting at line {i}")

        # Move past the END marker
        i += 1

    if not polygons:
        raise ValueError("No polygons found in .poly file")

    # Union all polygons into a single geometry
    if len(polygons) == 1:
        return polygons[0]
    return unary_union(polygons)  # type: ignore


def tile_to_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Convert Web Mercator tile coordinates to lat/lon bounding box.

    Args:
        z: Zoom level
        x: Tile column (X coordinate)
        y: Tile row (Y coordinate in Web Mercator, origin at top-left)

    Returns:
        Tuple of (west, south, east, north) in degrees (lat/lon)
    """
    n = 2.0**z

    # Calculate longitude bounds
    lon_min = (x / n) * 360.0 - 180.0
    lon_max = ((x + 1) / n) * 360.0 - 180.0

    # Calculate latitude bounds using Web Mercator formula
    lat_rad_max = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_rad_min = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))

    lat_max = math.degrees(lat_rad_max)
    lat_min = math.degrees(lat_rad_min)

    return (lon_min, lat_min, lon_max, lat_max)


class TileFilter:
    """Filter tiles based on geographic regions from .poly files."""

    def __init__(self, poly_urls: str, max_zoom_no_filter: int | None = None) -> None:
        """Initialize TileFilter from comma-separated .poly file URLs.

        Args:
            poly_urls: Comma-separated URLs of .poly files to download and use
            max_zoom_no_filter: Include all tiles up to this zoom level,
                ignoring poly filtering. None means filter all zooms.

        Raises:
            ValueError: If no valid polygons are found
        """
        self.polygons: list[Polygon] = []
        self.unified_geometry: Polygon | None = None
        self.polygon_count = 0
        self.max_zoom_no_filter = max_zoom_no_filter

        if not poly_urls or not poly_urls.strip():
            return

        # Parse comma-separated URLs
        urls = [url.strip() for url in poly_urls.split(",")]

        # Download and parse each .poly file
        for url in urls:
            try:
                poly_path = download_poly_file(url, context.tmp_folder)
                polygon = parse_poly_file(poly_path)
                self.polygons.append(polygon)
                logger.debug(f"Loaded polygon from {url}")
            except Exception as e:
                logger.error(f"Failed to load .poly file from {url}: {e}")
                raise

        if self.polygons:
            # Union all polygons into a single geometry for efficient
            # intersection checks
            if len(self.polygons) == 1:
                self.unified_geometry = self.polygons[0]
            else:
                self.unified_geometry = unary_union(self.polygons)  # type: ignore
            self.polygon_count = len(self.polygons)

            logger.info(f"Loaded {self.polygon_count} polygon(s) for filtering")

    def tile_intersects(self, z: int, x: int, y: int) -> bool:
        """Check if a tile intersects with any of the loaded polygon regions.

        Args:
            z: Zoom level
            x: Tile column
            y: Tile row

        Returns:
            True if tile should be included, False otherwise
        """
        # Check if this zoom level should be included without filtering
        if self.max_zoom_no_filter is not None and z <= self.max_zoom_no_filter:
            return True

        # If no polygon filtering is active, include the tile
        if self.unified_geometry is None:
            return True

        # Get tile bounding box
        west, south, east, north = tile_to_bbox(z, x, y)

        # Create a box from the tile bounds
        tile_box = Polygon(
            [
                (west, south),
                (east, south),
                (east, north),
                (west, north),
            ]
        )

        # Check if tile intersects with any region
        return tile_box.intersects(self.unified_geometry)
