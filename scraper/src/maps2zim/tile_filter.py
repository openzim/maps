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
    if filepath.exists():
        return filepath

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
    """Filter tiles based on the bounding box of geographic regions from .poly files."""

    def __init__(self, poly_urls: str) -> None:
        """Initialize TileFilter from comma-separated .poly file URLs.

        Computes the bounding box of all polygons and uses it for filtering.

        Args:
            poly_urls: Comma-separated URLs of .poly files to download and use

        Raises:
            ValueError: If no valid polygons are found
        """
        self.polygon_count = 0
        # (min_lon, min_lat, max_lon, max_lat) or None if no filtering
        self.bounding_box: tuple[float, float, float, float] | None = None

        if not poly_urls or not poly_urls.strip():
            return

        # Parse comma-separated URLs
        urls = [url.strip() for url in poly_urls.split(",")]
        polygons: list[Polygon] = []

        # Download and parse each .poly file
        for url in urls:
            try:
                poly_path = download_poly_file(url, context.tmp_folder)
                polygon = parse_poly_file(poly_path)
                polygons.append(polygon)
                logger.debug(f"Loaded polygon from {url}")
            except Exception as e:
                logger.error(f"Failed to load .poly file from {url}: {e}")
                raise

        if polygons:
            if len(polygons) == 1:
                unified = polygons[0]
            else:
                unified = unary_union(polygons)  # type: ignore
            self.polygon_count = len(polygons)

            min_lon, min_lat, max_lon, max_lat = unified.bounds
            self.bounding_box = (min_lon, min_lat, max_lon, max_lat)

            logger.info(
                f"Loaded {self.polygon_count} polygon(s) for filtering, "
                f"bounding box: {self.bounding_box}"
            )

    def tile_intersects(self, z: int, x: int, y: int) -> bool:
        """Check if a tile intersects with the bounding box of the loaded regions.

        Args:
            z: Zoom level
            x: Tile column
            y: Tile row

        Returns:
            True if tile should be included, False otherwise
        """
        if self.bounding_box is None:
            return True

        west, south, east, north = tile_to_bbox(z, x, y)
        min_lon, min_lat, max_lon, max_lat = self.bounding_box

        # Check if tile bbox overlaps with region bounding box
        return not (
            east < min_lon or west > max_lon or north < min_lat or south > max_lat
        )

    def contains_point(self, lon: float, lat: float) -> bool:
        """Check if a geographic point is within the bounding box of loaded regions.

        Args:
            lon: Longitude in degrees
            lat: Latitude in degrees

        Returns:
            True if point is inside the bounding box, or if no filtering is active.
        """
        if self.bounding_box is None:
            return True
        min_lon, min_lat, max_lon, max_lat = self.bounding_box
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
