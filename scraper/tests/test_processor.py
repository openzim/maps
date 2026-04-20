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


def test_compute_discriminating_labels_same_country():
    """Test the case with two cities in same country.

    Two French Rumilly places with different administrative hierarchies:
    - Rumilly → Haute-Savoie → Auvergne-Rhône-Alpes
    - Rumilly → Pas-de-Calais → Hauts-de-France

    Expected labels:
    - Rumilly, Auvergne-Rhône-Alpes
    - Rumilly, Hauts-de-France
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
    assert rumilly1.label == "Rumilly, Auvergne-Rhône-Alpes"
    assert rumilly2.label == "Rumilly, Hauts-de-France"


def test_compute_discriminating_labels_different_countries():
    """Test places with the same name in different countries use ADM1 to discriminate.

    Two "Neustadt" places with full ADM1/ADM2/ADM3 hierarchies in different countries:
    - Neustadt → Alsace-Bossue (ADM3) → Bas-Rhin (ADM2) → Grand Est (ADM1) [FR]
    - Neustadt → Heidelberg (ADM3) → Rhein-Neckar-Kreis (ADM2) →
      Baden-Württemberg (ADM1) [DE]

    Expected labels: "Neustadt, Grand Est" and "Neustadt, Baden-Württemberg".
    """
    grand_est = SearchPlace(
        geoname_id="grand_est",
        latitude=48.5,
        longitude=7.0,
        zoom=6,
        label="Grand Est",
        feature_code="ADM1",
        country_code="FR",
    )
    bas_rhin = SearchPlace(
        geoname_id="bas_rhin",
        latitude=48.5,
        longitude=7.5,
        zoom=8,
        label="Bas-Rhin",
        feature_code="ADM2",
        country_code="FR",
    )
    alsace_bossue = SearchPlace(
        geoname_id="alsace_bossue",
        latitude=48.8,
        longitude=7.1,
        zoom=10,
        label="Alsace-Bossue",
        feature_code="ADM3",
        country_code="FR",
    )
    place_fr = SearchPlace(
        geoname_id="pfr",
        latitude=48.85,
        longitude=7.1,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="FR",
    )

    baden_wuerttemberg = SearchPlace(
        geoname_id="baden_wuerttemberg",
        latitude=48.5,
        longitude=9.0,
        zoom=6,
        label="Baden-Württemberg",
        feature_code="ADM1",
        country_code="DE",
    )
    rhein_neckar = SearchPlace(
        geoname_id="rhein_neckar",
        latitude=49.4,
        longitude=8.7,
        zoom=8,
        label="Rhein-Neckar-Kreis",
        feature_code="ADM2",
        country_code="DE",
    )
    heidelberg = SearchPlace(
        geoname_id="heidelberg_adm3",
        latitude=49.4,
        longitude=8.7,
        zoom=10,
        label="Heidelberg",
        feature_code="ADM3",
        country_code="DE",
    )
    place_de = SearchPlace(
        geoname_id="pde",
        latitude=49.38,
        longitude=8.72,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="DE",
    )

    places_dict = {"Neustadt": [place_fr, place_de]}
    id_to_place = {
        "grand_est": grand_est,
        "bas_rhin": bas_rhin,
        "alsace_bossue": alsace_bossue,
        "pfr": place_fr,
        "baden_wuerttemberg": baden_wuerttemberg,
        "rhein_neckar": rhein_neckar,
        "heidelberg_adm3": heidelberg,
        "pde": place_de,
    }
    child_to_parent = {
        "pfr": "alsace_bossue",
        "alsace_bossue": "bas_rhin",
        "bas_rhin": "grand_est",
        "pde": "heidelberg_adm3",
        "heidelberg_adm3": "rhein_neckar",
        "rhein_neckar": "baden_wuerttemberg",
    }
    iso_to_country = {"FR": "France", "DE": "Germany"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    assert place_fr.label == "Neustadt, France"
    assert place_de.label == "Neustadt, Germany"


def test_compute_discriminating_labels_different_countries_no_hierarchy():
    """Test places with the same name in different countries fall back to country name.

    Two "Neustadt" places with no hierarchy — only country codes available.
    Expected labels: "Neustadt, France" and "Neustadt, Germany".
    """
    place_fr = SearchPlace(
        geoname_id="pfr",
        latitude=48.85,
        longitude=7.1,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="FR",
    )
    place_de = SearchPlace(
        geoname_id="pde",
        latitude=49.38,
        longitude=8.72,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="DE",
    )

    places_dict = {"Neustadt": [place_fr, place_de]}
    id_to_place = {"pfr": place_fr, "pde": place_de}
    child_to_parent: dict[str, str] = {}
    iso_to_country = {"FR": "France", "DE": "Germany"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    assert place_fr.label == "Neustadt, France"
    assert place_de.label == "Neustadt, Germany"


def test_compute_discriminating_labels_missing_country_info():
    """Test fallback to hierarchy when iso_to_country is missing for one country.

    Three "Neustadt" places:
    - Neustadt [FR]: no hierarchy, FR known → "Neustadt, France"
    - Neustadt [DE] in Rhein-Neckar-Kreis → Baden-Württemberg: DE missing from
      iso_to_country, ADM1 shared with next city → falls back to ADM2 →
      "Neustadt, Rhein-Neckar-Kreis"
    - Neustadt [DE] in Stuttgart → Baden-Württemberg: same ADM1, different ADM2 →
      "Neustadt, Stuttgart"
    """
    place_fr = SearchPlace(
        geoname_id="pfr",
        latitude=48.85,
        longitude=7.1,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="FR",
    )
    place_de1 = SearchPlace(
        geoname_id="pde1",
        latitude=49.38,
        longitude=8.72,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="DE",
    )
    place_de2 = SearchPlace(
        geoname_id="pde2",
        latitude=48.77,
        longitude=9.18,
        zoom=12,
        label="Neustadt",
        feature_code="ADM4",
        country_code="DE",
    )
    baden_wuerttemberg = SearchPlace(
        geoname_id="bw",
        latitude=48.5,
        longitude=9.0,
        zoom=6,
        label="Baden-Württemberg",
        feature_code="ADM1",
        country_code="DE",
    )
    rhein_neckar = SearchPlace(
        geoname_id="rhein_neckar",
        latitude=49.4,
        longitude=8.7,
        zoom=8,
        label="Rhein-Neckar-Kreis",
        feature_code="ADM2",
        country_code="DE",
    )
    stuttgart = SearchPlace(
        geoname_id="stuttgart_adm2",
        latitude=48.77,
        longitude=9.18,
        zoom=8,
        label="Stuttgart",
        feature_code="ADM2",
        country_code="DE",
    )

    places_dict = {"Neustadt": [place_fr, place_de1, place_de2]}
    id_to_place = {
        "pfr": place_fr,
        "pde1": place_de1,
        "pde2": place_de2,
        "bw": baden_wuerttemberg,
        "rhein_neckar": rhein_neckar,
        "stuttgart_adm2": stuttgart,
    }
    child_to_parent = {
        "pde1": "rhein_neckar",
        "rhein_neckar": "bw",
        "pde2": "stuttgart_adm2",
        "stuttgart_adm2": "bw",
    }
    iso_to_country = {"FR": "France"}  # DE deliberately missing

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    assert place_fr.label == "Neustadt, France"
    assert place_de1.label == "Neustadt, Rhein-Neckar-Kreis"
    assert place_de2.label == "Neustadt, Stuttgart"


def test_compute_discriminating_labels_ancestry_relationship():
    """Test ADM-level tagging when one place is an ancestor of another.

    "Rumilly" exists as both an ADM3 district and an ADM4 city inside that district.
    Because they are in an ancestor/descendant relationship, hierarchy disambiguation
    is useless — both share the same ancestry. They are tagged with their ADM level:
    - "Rumilly (district)"
    - "Rumilly (city)"
    """
    rumilly_adm3 = SearchPlace(
        geoname_id="rumilly_adm3",
        latitude=45.87,
        longitude=5.94,
        zoom=10,
        label="Rumilly",
        feature_code="ADM3",
        country_code="FR",
    )
    rumilly_adm4 = SearchPlace(
        geoname_id="rumilly_adm4",
        latitude=45.87,
        longitude=5.94,
        zoom=12,
        label="Rumilly",
        feature_code="ADM4",
        country_code="FR",
    )

    places_dict = {"Rumilly": [rumilly_adm3, rumilly_adm4]}
    id_to_place = {
        "rumilly_adm3": rumilly_adm3,
        "rumilly_adm4": rumilly_adm4,
    }
    # ADM4 is a child of ADM3
    child_to_parent = {"rumilly_adm4": "rumilly_adm3"}
    iso_to_country = {"FR": "France"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    assert rumilly_adm3.label == "Rumilly (district)"
    assert rumilly_adm4.label == "Rumilly (city)"


def test_compute_discriminating_labels_ancestry_relationship_adm1_adm3():
    """Test ADM-level tagging when ADM1 and ADM3 share the same name in one chain.

    "Alsace" exists as both an ADM1 region and an ADM3 district inside that region
    (with an ADM2 in between). They are tagged with their ADM level:
    - "Alsace (region)"
    - "Alsace (district)"
    """
    alsace_adm1 = SearchPlace(
        geoname_id="alsace_adm1",
        latitude=48.3,
        longitude=7.4,
        zoom=6,
        label="Alsace",
        feature_code="ADM1",
        country_code="FR",
    )
    bas_rhin = SearchPlace(
        geoname_id="bas_rhin",
        latitude=48.5,
        longitude=7.5,
        zoom=8,
        label="Bas-Rhin",
        feature_code="ADM2",
        country_code="FR",
    )
    alsace_adm3 = SearchPlace(
        geoname_id="alsace_adm3",
        latitude=48.3,
        longitude=7.4,
        zoom=10,
        label="Alsace",
        feature_code="ADM3",
        country_code="FR",
    )

    places_dict = {"Alsace": [alsace_adm1, alsace_adm3]}
    id_to_place = {
        "alsace_adm1": alsace_adm1,
        "bas_rhin": bas_rhin,
        "alsace_adm3": alsace_adm3,
    }
    # ADM3 → ADM2 → ADM1
    child_to_parent = {
        "alsace_adm3": "bas_rhin",
        "bas_rhin": "alsace_adm1",
    }
    iso_to_country = {"FR": "France"}

    Processor._compute_discriminating_labels(  # pyright: ignore[reportPrivateUsage]
        places_dict, id_to_place, child_to_parent, iso_to_country
    )

    assert alsace_adm1.label == "Alsace (region)"
    assert alsace_adm3.label == "Alsace (district)"


def test_parse_geonames_with_tile_filter():
    """Test that _parse_geonames filters places by geographic region."""
    # Create a minimal geonames TSV with two ADM2 places
    geonames_content = """# geonames data
1234567\tLyon\t\t\t45.76\t4.84\t\tADM2\tFR\t
2345678\tBerlin\t\t\t52.52\t13.41\t\tADM2\tDE\t
"""

    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Setup context with temp dl folder
        context = Context.get()
        old_dl_folder = context.dl_folder
        context.dl_folder = tmpdir_path

        # Write geonames file
        geonames_path = tmpdir_path / f"{context.geonames_region}.txt"
        geonames_path.write_text(geonames_content, encoding="utf-8")

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
            min_lon, min_lat, max_lon, max_lat = lyon_polygon.bounds
            tile_filter.bounding_box = (min_lon, min_lat, max_lon, max_lat)
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
            # Restore original dl folder
            context.dl_folder = old_dl_folder


def test_parse_geonames_without_tile_filter():
    """Test that _parse_geonames works normally without tile filter."""
    # Create a minimal geonames TSV with two ADM2 places
    geonames_content = """# geonames data
1234567\tLyon\t\t\t45.76\t4.84\t\tADM2\tFR\t
2345678\tBerlin\t\t\t52.52\t13.41\t\tADM2\tDE\t
"""

    with TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Setup context with temp dl folder
        context = Context.get()
        old_dl_folder = context.dl_folder
        context.dl_folder = tmpdir_path

        # Write geonames file
        geonames_path = tmpdir_path / f"{context.geonames_region}.txt"
        geonames_path.write_text(geonames_content, encoding="utf-8")

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
            # Restore original dl folder
            context.dl_folder = old_dl_folder


def test_uses_geofabrik_polys_true_for_geofabrik_url():
    """Test that _uses_geofabrik_polys detects a Geofabrik URL."""
    assert (
        Processor._uses_geofabrik_polys(  # pyright: ignore[reportPrivateUsage]
            "https://download.geofabrik.de/europe/france.poly"
        )
        is True
    )


def test_uses_geofabrik_polys_true_for_mixed_urls():
    """Test that _uses_geofabrik_polys detects Geofabrik in mixed URLs."""
    assert (
        Processor._uses_geofabrik_polys(  # pyright: ignore[reportPrivateUsage]
            "https://example.com/a.poly,https://download.geofabrik.de/europe/france.poly"
        )
        is True
    )


def test_uses_geofabrik_polys_false_for_non_geofabrik():
    """Test that _uses_geofabrik_polys returns False for non-Geofabrik URLs."""
    assert (
        Processor._uses_geofabrik_polys(  # pyright: ignore[reportPrivateUsage]
            "https://example.com/region.poly"
        )
        is False
    )


def test_uses_geofabrik_polys_false_for_none():
    """Test that _uses_geofabrik_polys returns False when no URLs are set."""
    assert (
        Processor._uses_geofabrik_polys(None)  # pyright: ignore[reportPrivateUsage]
        is False
    )


def test_create_about_html_contains_title_and_description():
    """Test that _create_about_html produces HTML with title and description."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="My Map",
        description="Short desc",
        long_description=None,
        zim_creator="openZIM",
        publisher="openZIM",
        include_geofabrik=False,
    )
    assert "My Map" in html
    assert "Short desc" in html
    assert "<!DOCTYPE html>" in html


def test_create_about_html_single_creator_publisher():
    """Test creator/publisher when they are the same."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="T",
        description="D",
        long_description=None,
        zim_creator="openZIM",
        publisher="openZIM",
        include_geofabrik=False,
    )
    assert "Created &amp; published by" in html
    # Should NOT have separate lines for creator and publisher
    assert "Created by</span>" not in html
    assert "Published by</span>" not in html


def test_create_about_html_different_creator_publisher():
    """Test creator/publisher when they are different."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="T",
        description="D",
        long_description=None,
        zim_creator="Alice",
        publisher="Bob",
        include_geofabrik=False,
    )
    # Should have both "Created by" and "Published by" as separate labels
    assert "Created by</span>" in html
    assert "Published by</span>" in html
    assert "Alice" in html
    assert "Bob" in html


def test_create_about_html_includes_geofabrik_when_flag_set():
    """Test that Geofabrik appears in credits when flag is True."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="T",
        description="D",
        long_description=None,
        zim_creator="openZIM",
        publisher="openZIM",
        include_geofabrik=True,
    )
    assert "Geofabrik" in html


def test_create_about_html_excludes_geofabrik_when_flag_not_set():
    """Test that Geofabrik does not appear when flag is False."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="T",
        description="D",
        long_description=None,
        zim_creator="openZIM",
        publisher="openZIM",
        include_geofabrik=False,
    )
    assert "Geofabrik" not in html


def test_create_about_html_includes_long_description():
    """Test that long_description is included in HTML."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="T",
        description="D",
        long_description="Long text here",
        zim_creator="openZIM",
        publisher="openZIM",
        include_geofabrik=False,
    )
    assert "Long text here" in html


def test_create_about_html_escapes_html_special_chars():
    """Test that HTML special characters are properly escaped."""
    html = Processor._create_about_html(  # pyright: ignore[reportPrivateUsage]
        title="Test & <Title>",
        description="Desc < > & desc",
        long_description=None,
        zim_creator="Creator & Co.",
        publisher="Publisher",
        include_geofabrik=False,
    )
    # Should have HTML entities instead of raw chars
    assert "Test &amp; &lt;Title&gt;" in html
    assert "Desc &lt; &gt; &amp; desc" in html
    assert "Creator &amp; Co." in html
