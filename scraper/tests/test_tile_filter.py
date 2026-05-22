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


def test_tile_filter_no_filter():
    """Test that a filter with no poly URLs includes all tiles."""
    tile_filter = TileFilter("")

    assert tile_filter.tile_intersects(0, 0, 0) is True
    assert tile_filter.tile_intersects(10, 500, 500) is True
    assert tile_filter.bounding_box is None


def test_tile_filter_bounding_box():
    """Test tile filtering based on bounding box derived from poly."""
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

        tile_filter = TileFilter("")
        polygon = parse_poly_file(poly_path)
        min_lon, min_lat, max_lon, max_lat = polygon.bounds
        tile_filter.bounding_box = (min_lon, min_lat, max_lon, max_lat)
        tile_filter.polygon_count = 1

        # Bounding box is (0, 0, 1, 1) — tiles overlapping this region should pass
        # Tile at zoom 10, ~(0,0) should intersect
        assert tile_filter.tile_intersects(10, 512, 511) is True
        # Tile far away (top-left of world) should not intersect
        assert tile_filter.tile_intersects(10, 0, 0) is False


def test_tile_filter_contains_point():
    """Test point-in-bounding-box filtering."""
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

        tile_filter = TileFilter("")
        polygon = parse_poly_file(poly_path)
        min_lon, min_lat, max_lon, max_lat = polygon.bounds
        tile_filter.bounding_box = (min_lon, min_lat, max_lon, max_lat)
        tile_filter.polygon_count = 1

        # Points inside the bounding box
        assert tile_filter.contains_point(0.5, 0.5) is True
        assert tile_filter.contains_point(0.25, 0.75) is True
        assert tile_filter.contains_point(0.1, 0.1) is True

        # Points outside the bounding box
        assert tile_filter.contains_point(-0.5, 0.5) is False
        assert tile_filter.contains_point(1.5, 0.5) is False
        assert tile_filter.contains_point(0.5, -0.5) is False
        assert tile_filter.contains_point(2.0, 2.0) is False

        # Test with no bounding box (should always return True)
        tile_filter_no_bounds = TileFilter("")
        assert tile_filter_no_bounds.contains_point(0.5, 0.5) is True
        assert tile_filter_no_bounds.contains_point(-180.0, -90.0) is True
        assert tile_filter_no_bounds.contains_point(180.0, 90.0) is True


# --- Antimeridian tests ---
# Region: lon [178, 180] + [-180, -177], lat [-20, -17] (~ Fiji)
# min_lon (178) > max_lon (-177) signals antimeridian crossing.
_ANTI_BBOX = (178.0, -20.0, -177.0, -17.0)


def test_parse_poly_file_antimeridian_rotation():
    """Sub-polygons touching lon=-180 are rotated +360° so bounds stay compact."""
    poly_content = """fiji_area
fiji_east
    178.0  -17.0
    180.0  -17.0
    180.0  -20.0
    178.0  -20.0
    178.0  -17.0
END
fiji_west
    -180.0  -17.0
    -177.0  -17.0
    -177.0  -20.0
    -180.0  -20.0
    -180.0  -17.0
END
END
"""
    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "fiji.poly"
        poly_path.write_text(poly_content)
        geometry = parse_poly_file(poly_path)

        min_lon, min_lat, max_lon, max_lat = geometry.bounds
        # Western polygon rotated: -177 + 360 = 183; -180 + 360 = 180
        assert min_lon == 178.0
        assert max_lon == 183.0
        assert min_lat == -20.0
        assert max_lat == -17.0


def test_parse_poly_file_australia_oceania():
    """australia-oceania pattern: western polygon rotated, compact bounds result."""
    poly_content = """australia-oceania
1
   -107.863281   11.780702
   -104.171875   -28.082042
   -180.000000   -45.652740
   -180.000000   4.082818
   -107.863281   11.780702
END
0
   89.512500   -11.143360
   70.189171   -10.433483
   62.057814   -56.558737
   180.000000   -57.164820
   180.000000   26.277810
   141.547997   22.628320
   130.145100   3.640314
   129.953200   -0.535293
   131.061600   -3.784815
   130.266900   -10.043780
   118.255700   -13.011650
   102.800900   -8.390453
   89.512500   -11.143360
END
END
"""
    with TemporaryDirectory() as tmpdir:
        poly_path = Path(tmpdir) / "au.poly"
        poly_path.write_text(poly_content)
        geometry = parse_poly_file(poly_path)

        min_lon, min_lat, max_lon, max_lat = geometry.bounds
        assert min_lon == 62.057814
        # Western polygon rotated: -104.171875 + 360 = 255.828125
        assert max_lon == 255.828125
        assert max_lon > 180, "rotated western polygon pushes max_lon above 180"

        # Simulate what TileFilter.__init__ does: normalize back to [-180, 180]
        if max_lon > 180:
            max_lon -= 360.0
        assert min_lon > max_lon, "min_lon > max_lon signals antimeridian crossing"

        # Verify filtering with the normalised bbox
        tf = TileFilter("")
        tf.bounding_box = (min_lon, min_lat, max_lon, max_lat)
        tf.polygon_count = 2
        assert tf.contains_point(150.0, -30.0) is True  # Oceania
        assert tf.contains_point(-130.0, -20.0) is True  # Pacific west side
        assert tf.contains_point(30.0, -20.0) is False  # prime-meridian gap


def test_tile_filter_antimeridian_tile_intersects():
    """tile_intersects handles bounding boxes that cross the antimeridian."""
    tf = TileFilter("")
    tf.bounding_box = _ANTI_BBOX
    tf.polygon_count = 1

    # Tile near lon=179 (east of antimeridian, correct latitude)
    # zoom=8, x=255 → lon [178.59, 180]; y=141 → lat near -18
    assert tf.tile_intersects(8, 255, 141) is True

    # Tile near lon=-178 (west of antimeridian, correct latitude)
    # zoom=8, x=1 → lon [-178.59, -177.19]
    assert tf.tile_intersects(8, 1, 141) is True

    # Tile at prime meridian (lon ~0), correct latitude — outside region
    # zoom=8, x=128 → lon [0, 1.4]
    assert tf.tile_intersects(8, 128, 141) is False

    # Tile at correct longitude but wrong latitude (north pole area)
    assert tf.tile_intersects(8, 255, 0) is False

    # Whole-world tile (zoom 0) must always intersect
    assert tf.tile_intersects(0, 0, 0) is True


def test_tile_filter_antimeridian_contains_point():
    """contains_point handles bounding boxes that cross the antimeridian."""
    tf = TileFilter("")
    tf.bounding_box = _ANTI_BBOX
    tf.polygon_count = 1

    # Points inside the east side of the antimeridian
    assert tf.contains_point(179.0, -18.0) is True
    assert tf.contains_point(178.0, -17.0) is True

    # Points inside the west side of the antimeridian
    assert tf.contains_point(-178.0, -18.0) is True
    assert tf.contains_point(-177.0, -19.0) is True

    # Points outside (prime meridian area, correct latitude)
    assert tf.contains_point(0.0, -18.0) is False
    assert tf.contains_point(90.0, -18.0) is False
    assert tf.contains_point(-90.0, -18.0) is False

    # Points with correct longitude but wrong latitude
    assert tf.contains_point(179.0, 0.0) is False
    assert tf.contains_point(-178.0, 80.0) is False
