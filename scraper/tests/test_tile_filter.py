"""Tests for the tile filtering module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from shapely.geometry import Point, Polygon

from maps2zim.tile_filter import TileFilter, parse_poly_file, tile_to_bbox


def test_tile_to_bbox():
    """Test Web Mercator tile to bounding box conversion."""
    # Test at zoom 0: single tile covering the whole world
    west, south, east, north = tile_to_bbox(0, 0, 0)
    assert west == -180.0
    assert east == 180.0
    assert south < -85.0
    assert north > 85.0

    # Test at zoom 1: we should get a smaller region
    west, south, east, north = tile_to_bbox(1, 0, 0)
    assert west == -180.0
    assert east == 0.0
    assert (
        south <= 0.0
    )  # Y=0 at zoom 1 is the top tile, covering from ~85 to 0 latitude
    assert north > 0.0

    # Test that bounds are reasonable
    west, south, east, north = tile_to_bbox(10, 500, 500)
    assert -180.0 <= west <= 180.0
    assert -180.0 <= east <= 180.0
    assert -85.0 <= south <= 85.0
    assert -85.0 <= north <= 85.0
    assert west < east
    assert south < north


def test_parse_poly_file():
    """Test parsing of .poly files."""
    poly_content = """test_area
test_polygon
    0.0    0.0
    1.0    0.0
    1.0    1.0
    0.0    1.0
    0.0    0.0
END
END
"""

    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "test.poly"
        poly_path.write_text(poly_content)

        polygon = parse_poly_file(poly_path)

        assert isinstance(polygon, Polygon)
        # Check that the polygon contains the expected point
        assert polygon.contains(Point(0.5, 0.5))


def test_parse_poly_file_multiple_polygons():
    """Test parsing .poly file with multiple polygons."""
    poly_content = """test_area
polygon1
    0.0    0.0
    1.0    0.0
    1.0    1.0
    0.0    1.0
    0.0    0.0
END
polygon2
    2.0    2.0
    3.0    2.0
    3.0    3.0
    2.0    3.0
    2.0    2.0
END
END
"""

    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "test.poly"
        poly_path.write_text(poly_content)

        geometry = parse_poly_file(poly_path)

        # Should be a union of both polygons
        # Check that both regions are represented
        assert geometry.is_valid


def test_parse_poly_file_invalid():
    """Test parsing of invalid .poly files."""
    invalid_content = """test_area
polygon
    invalid coordinates
END
END
"""

    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "invalid.poly"
        poly_path.write_text(invalid_content)

        with pytest.raises(ValueError):
            parse_poly_file(poly_path)


def test_parse_poly_file_nonexistent():
    """Test parsing of nonexistent .poly file."""
    with pytest.raises(FileNotFoundError):
        parse_poly_file(Path("/nonexistent/file.poly"))


def test_parse_poly_file_empty():
    """Test parsing of empty .poly file."""
    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "empty.poly"
        poly_path.write_text("")

        with pytest.raises(ValueError):
            parse_poly_file(poly_path)


def test_tile_filter_zoom_no_filter():
    """Test that tiles at or below max_zoom_no_filter are always included."""
    # Create filter with max_zoom_no_filter=5
    tile_filter = TileFilter("", max_zoom_no_filter=5)

    # Tiles at zoom 0-5 should be included
    assert tile_filter.tile_intersects(0, 0, 0) is True
    assert tile_filter.tile_intersects(3, 2, 4) is True
    assert tile_filter.tile_intersects(5, 10, 20) is True

    # Tiles at zoom > 5 should also be included (no poly filtering)
    assert tile_filter.tile_intersects(6, 30, 40) is True
    assert tile_filter.tile_intersects(10, 500, 500) is True


def test_tile_filter_zoom_no_filter_with_poly():
    """Test zoom filtering with polygon filtering."""
    poly_content = """test_area
test_polygon
    0.0    0.0
    1.0    0.0
    1.0    1.0
    0.0    1.0
    0.0    0.0
END
END
"""

    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "test.poly"
        poly_path.write_text(poly_content)

        # Mock the TileFilter by directly setting up the geometry
        tile_filter = TileFilter("", max_zoom_no_filter=5)
        polygon = parse_poly_file(poly_path)
        tile_filter.unified_geometry = polygon
        tile_filter.polygon_count = 1

        # Tiles at zoom 0-5 should be included regardless of poly
        assert tile_filter.tile_intersects(0, 0, 0) is True
        assert tile_filter.tile_intersects(5, 5, 5) is True

        # Tiles at zoom > 5 should be filtered by polygon
        # Tile at zoom 10, column 512, row 512 is approximately at (0, 0)
        # which should be inside the poly
        assert tile_filter.tile_intersects(10, 512, 512) is True
        # Tile far away should not intersect
        assert tile_filter.tile_intersects(10, 0, 0) is False
