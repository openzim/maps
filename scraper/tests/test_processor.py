"""Tests for processor module, particularly geonames and hierarchy handling."""

from pathlib import Path
from tempfile import TemporaryDirectory

from shapely.geometry import Polygon

from maps2zim.context import Context
from maps2zim.processor import Processor, SearchPlace
from maps2zim.tile_filter import TileFilter


def test_compute_discriminating_labels_single_place():
    """Test that single places don't get label changes."""
    place = SearchPlace(
        geoname_id="1",
        latitude=45.0,
        longitude=6.0,
        zoom=12,
        label="Rumilly",
        feature_code="ADM4",
        country_code="FR",
    )

    places_dict = {"Rumilly": [place]}
    id_to_place = {"1": place}
    child_to_parent: dict[str, str] = {}
    iso_to_country = {"FR": "France"}

    # Should not change
    original_label = place.label
    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )
    assert place.label == original_label


def test_compute_discriminating_labels_rumilly_french_example():
    """Test the Rumilly example with realistic French data.

    Two French Rumilly places with different administrative hierarchies:
    - Rumilly in Haute-Savoie → Auvergne-Rhône-Alpes
    - Rumilly in Pas-de-Calais → Hauts-de-France

    Expected labels (with full hierarchy including country):
    - Rumilly, Haute-Savoie, Auvergne-Rhône-Alpes, France
    - Rumilly, Pas-de-Calais, Hauts-de-France, France
    """
    # ADM1 (regional level)
    auvergne = SearchPlace(
        geoname_id="auvergne",
        latitude=45.5,
        longitude=3,
        zoom=6,
        label="Auvergne-Rhône-Alpes",
        feature_code="ADM1",
        country_code="FR",
    )
    hauts_de_france = SearchPlace(
        geoname_id="hauts_de_france",
        latitude=50,
        longitude=3,
        zoom=6,
        label="Hauts-de-France",
        feature_code="ADM1",
        country_code="FR",
    )

    # ADM2 (departmental level)
    haute_savoie = SearchPlace(
        geoname_id="haute_savoie",
        latitude=45.8,
        longitude=6.5,
        zoom=8,
        label="Haute-Savoie",
        feature_code="ADM2",
        country_code="FR",
    )
    pas_de_calais = SearchPlace(
        geoname_id="pas_de_calais",
        latitude=50.5,
        longitude=2,
        zoom=8,
        label="Pas-de-Calais",
        feature_code="ADM2",
        country_code="FR",
    )

    # The two Rumilly places
    rumilly1 = SearchPlace(
        geoname_id="rumilly1",
        latitude=45.8,
        longitude=6,
        zoom=12,
        label="Rumilly",
        feature_code="ADM4",
        country_code="FR",
    )
    rumilly2 = SearchPlace(
        geoname_id="rumilly2",
        latitude=50.1,
        longitude=2.3,
        zoom=12,
        label="Rumilly",
        feature_code="ADM4",
        country_code="FR",
    )

    places_dict = {"Rumilly": [rumilly1, rumilly2]}

    id_to_place = {
        "auvergne": auvergne,
        "hauts_de_france": hauts_de_france,
        "haute_savoie": haute_savoie,
        "pas_de_calais": pas_de_calais,
        "rumilly1": rumilly1,
        "rumilly2": rumilly2,
    }

    # Build hierarchy
    child_to_parent = {
        "rumilly1": "haute_savoie",
        "haute_savoie": "auvergne",
        "rumilly2": "pas_de_calais",
        "pas_de_calais": "hauts_de_france",
    }

    iso_to_country = {"FR": "France"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    # Verify labels include full hierarchy with country
    assert rumilly1.label == "Rumilly, Haute-Savoie, Auvergne-Rhône-Alpes, France"
    assert rumilly2.label == "Rumilly, Pas-de-Calais, Hauts-de-France, France"


def test_compute_discriminating_labels_different_countries():
    """Test places with same name in different countries."""
    # Countries
    france = SearchPlace(
        geoname_id="france",
        latitude=46,
        longitude=2,
        zoom=6,
        label="France",
        feature_code="ADM1",
        country_code="FR",
    )
    germany = SearchPlace(
        geoname_id="germany",
        latitude=51,
        longitude=10,
        zoom=6,
        label="Germany",
        feature_code="ADM1",
        country_code="DE",
    )

    place_fr = SearchPlace(
        geoname_id="pfr",
        latitude=45,
        longitude=2,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="FR",
    )
    place_de = SearchPlace(
        geoname_id="pde",
        latitude=51,
        longitude=10,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="DE",
    )

    places_dict = {"Neustadt": [place_fr, place_de]}
    id_to_place = {
        "france": france,
        "germany": germany,
        "pfr": place_fr,
        "pde": place_de,
    }
    child_to_parent = {
        "pfr": "france",
        "pde": "germany",
    }
    iso_to_country = {"FR": "France", "DE": "Germany"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    # Labels include hierarchy (France and Germany are already in the chain, so no
    # duplication)
    assert place_fr.label == "Neustadt, France"
    assert place_de.label == "Neustadt, Germany"


def test_compute_discriminating_labels_multiple_levels():
    """Test with deep hierarchy (multiple administrative levels)."""
    auvergne = SearchPlace(
        geoname_id="auvergne",
        latitude=45.5,
        longitude=3,
        zoom=6,
        label="Auvergne-Rhône-Alpes",
        feature_code="ADM1",
        country_code="FR",
    )
    haute_savoie = SearchPlace(
        geoname_id="haute_savoie",
        latitude=45.8,
        longitude=6.5,
        zoom=8,
        label="Haute-Savoie",
        feature_code="ADM2",
        country_code="FR",
    )
    arrondissement = SearchPlace(
        geoname_id="arrondissement",
        latitude=45.8,
        longitude=6.3,
        zoom=10,
        label="Arrondissement d'Annecy",
        feature_code="ADM3",
        country_code="FR",
    )
    cantons = [
        SearchPlace(
            geoname_id="canton1",
            latitude=45.75,
            longitude=6.1,
            zoom=12,
            label="Canton de Rumilly",
            feature_code="ADM4",
            country_code="FR",
        ),
        SearchPlace(
            geoname_id="canton2",
            latitude=45.85,
            longitude=6.5,
            zoom=12,
            label="Canton d'Annecy",
            feature_code="ADM4",
            country_code="FR",
        ),
    ]

    places_dict = {"Rumilly": cantons}
    id_to_place = {
        "auvergne": auvergne,
        "haute_savoie": haute_savoie,
        "arrondissement": arrondissement,
        "canton1": cantons[0],
        "canton2": cantons[1],
    }
    child_to_parent = {
        "canton1": "arrondissement",
        "canton2": "arrondissement",
        "arrondissement": "haute_savoie",
        "haute_savoie": "auvergne",
    }
    iso_to_country = {"FR": "France"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    # Full hierarchy including country
    assert (
        cantons[0].label == "Canton de Rumilly, Arrondissement d'Annecy, Haute-Savoie,"
        " Auvergne-Rhône-Alpes, France"
    )
    assert (
        cantons[1].label == "Canton d'Annecy, Arrondissement d'Annecy, Haute-Savoie, "
        "Auvergne-Rhône-Alpes, France"
    )


def test_compute_discriminating_labels_no_hierarchy():
    """Test with empty hierarchy (no parent links found)."""
    place1 = SearchPlace(
        geoname_id="p1",
        latitude=45,
        longitude=5,
        zoom=12,
        label="Paris",
        feature_code="ADM4",
        country_code="FR",
    )
    place2 = SearchPlace(
        geoname_id="p2",
        latitude=48,
        longitude=0,
        zoom=12,
        label="Paris",
        feature_code="ADM4",
        country_code="FR",
    )

    places_dict = {"Paris": [place1, place2]}
    id_to_place = {
        "p1": place1,
        "p2": place2,
    }
    child_to_parent: dict[str, str] = {}  # No hierarchy
    iso_to_country = {"FR": "France"}

    # Should not crash, labels stay as-is since no ancestors found to disambiguate
    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    # Without hierarchy, no disambiguation possible, labels remain unchanged
    assert place1.label == "Paris"
    assert place2.label == "Paris"


def test_compute_discriminating_labels_no_country_info():
    """Test with empty country info (no country name lookup)."""
    france = SearchPlace(
        geoname_id="france",
        latitude=46,
        longitude=2,
        zoom=6,
        label="France",
        feature_code="ADM1",
        country_code="FR",
    )
    germany = SearchPlace(
        geoname_id="germany",
        latitude=51,
        longitude=10,
        zoom=6,
        label="Germany",
        feature_code="ADM1",
        country_code="DE",
    )
    place_fr = SearchPlace(
        geoname_id="p1",
        latitude=45,
        longitude=5,
        zoom=12,
        label="Lyon",
        feature_code="ADM4",
        country_code="FR",
    )
    place_de = SearchPlace(
        geoname_id="p2",
        latitude=51,
        longitude=10,
        zoom=12,
        label="Lyon",
        feature_code="ADM4",
        country_code="DE",
    )

    places_dict = {"Lyon": [place_fr, place_de]}
    id_to_place = {
        "france": france,
        "germany": germany,
        "p1": place_fr,
        "p2": place_de,
    }
    child_to_parent = {
        "p1": "france",
        "p2": "germany",
    }
    iso_to_country: dict[str, str] = {}  # No country info

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    # With hierarchy but no country info lookup, just the hierarchy (countries are
    # already ancestors)
    assert place_fr.label == "Lyon, France"
    assert place_de.label == "Lyon, Germany"


def test_parse_geonames_with_tile_filter():
    """Test that _parse_geonames filters places by geographic region."""
    # Create a minimal geonames TSV with two ADM2 places
    geonames_content = """# geonames data
1234567\tLyon\t\t\t45.76\t4.84\t\tADM2\tFR\t
2345678\tBerlin\t\t\t52.52\t13.41\t\tADM2\tDE\t
"""

    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write geonames file
        geonames_path = tmpdir_path / "FR.txt"
        geonames_path.write_text(geonames_content, encoding="utf-8")

        # Setup context with temp assets folder
        context = Context.get()
        old_assets_folder = context.assets_folder
        context.assets_folder = tmpdir_path

        try:
            # Create a filter with a small polygon around Lyon (lon: 4.84, lat: 45.76)
            # This polygon is roughly 2 degrees square centered on Lyon
            lyon_polygon = Polygon(
                [
                    (3.0, 44.0),  # southwest
                    (6.0, 44.0),  # southeast
                    (6.0, 47.0),  # northeast
                    (3.0, 47.0),  # northwest
                    (3.0, 44.0),  # close
                ]
            )

            tile_filter = TileFilter("")  # Create empty filter
            tile_filter.unified_geometry = lyon_polygon
            tile_filter.polygon_count = 1

            # Create processor and parse geonames with filter
            processor = Processor()
            places_dict = (
                processor._parse_geonames(  # pyright: ignore[reportPrivateUsage]
                    tile_filter=tile_filter
                )
            )

            # Verify that only Lyon is in the result
            # (Berlin is outside the polygon, so should be filtered out)
            assert len(places_dict) == 1
            assert "Lyon" in places_dict
            assert "Berlin" not in places_dict

            # Verify Lyon has correct properties
            lyon_places = places_dict["Lyon"]
            assert len(lyon_places) == 1
            assert lyon_places[0].geoname_id == "1234567"
            assert lyon_places[0].latitude == 45.76
            assert lyon_places[0].longitude == 4.84
            assert lyon_places[0].feature_code == "ADM2"

        finally:
            # Restore original assets folder
            context.assets_folder = old_assets_folder


def test_parse_geonames_without_tile_filter():
    """Test that _parse_geonames works normally without tile filter."""
    # Create a minimal geonames TSV with two ADM2 places
    geonames_content = """# geonames data
1234567\tLyon\t\t\t45.76\t4.84\t\tADM2\tFR\t
2345678\tBerlin\t\t\t52.52\t13.41\t\tADM2\tDE\t
"""

    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write geonames file
        geonames_path = tmpdir_path / "FR.txt"
        geonames_path.write_text(geonames_content, encoding="utf-8")

        # Setup context with temp assets folder
        context = Context.get()
        old_assets_folder = context.assets_folder
        context.assets_folder = tmpdir_path

        try:
            # Parse geonames WITHOUT filter
            processor = Processor()
            places_dict = (
                processor._parse_geonames(  # pyright: ignore[reportPrivateUsage]
                    tile_filter=None
                )
            )

            # Both places should be included
            assert len(places_dict) == 2
            assert "Lyon" in places_dict
            assert "Berlin" in places_dict

        finally:
            # Restore original assets folder
            context.assets_folder = old_assets_folder
