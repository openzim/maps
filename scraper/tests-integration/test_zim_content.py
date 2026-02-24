import json
import os
from pathlib import Path

import pytest
from zimscraperlib.zim import Archive

ZIM_FILE_PATH = Path(os.environ["ZIM_FILE_PATH"])


@pytest.fixture(scope="module")
def zim_file_path() -> Path:
    return ZIM_FILE_PATH


@pytest.fixture(scope="module")
def zim_fh() -> Archive:
    return Archive(ZIM_FILE_PATH)


def test_is_file(zim_file_path: Path):
    """Ensure ZIM file exists"""
    assert zim_file_path.exists()
    assert zim_file_path.is_file()


def test_zim_main_page(zim_fh: Archive):
    """Ensure main page is a redirect to index.html"""

    main_entry = zim_fh.main_entry
    assert main_entry.is_redirect
    assert main_entry.get_redirect_entry().path == "index.html"


def test_zim_metadata(zim_fh: Archive):
    """Ensure scraper and zim title are present in metadata"""

    assert "maps2zim " in zim_fh.get_text_metadata("Scraper")
    assert zim_fh.get_text_metadata("Title") == "Maps Test"
    assert zim_fh.get_text_metadata("Description") == "Test ZIM for maps"
    assert zim_fh.get_text_metadata("Language") == "eng"
    assert zim_fh.get_text_metadata("Publisher") == "openZIM"
    assert zim_fh.get_text_metadata("Creator") == "openZIM"


@pytest.mark.parametrize(
    "item_path,expected_mimetype",
    [
        # pytest.param("content/logo.png", "image/png", id="logo"),
        pytest.param("favicon.ico", "image/vnd.microsoft.icon", id="favicon"),
        pytest.param("content/styles.css", "text/css", id="styles.css"),
        pytest.param("content/about.html", "text/html", id="about.html"),
        pytest.param("planet", "application/json", id="planet"),
    ],
)
def test_zim_content_expected_files(
    zim_fh: Archive, item_path: str, expected_mimetype: str
):
    """Ensure proper content at content/logo.png"""

    expected_file = zim_fh.get_item(item_path)
    assert expected_file
    assert expected_file.mimetype == expected_mimetype
    assert len(expected_file.content) > 0


def test_zim_content_config_json(zim_fh: Archive):
    """Ensure proper content at content/config.json"""

    config_json_item = zim_fh.get_item("content/config.json")
    assert config_json_item.mimetype == "application/json"
    config_json = json.loads(bytes(config_json_item.content))
    assert config_json["center"] == [43.74, 7.43]
    assert config_json["zoom"] == 13
    assert config_json["secondaryColor"] == "#FFFFFF"
    assert config_json["zimName"] == "maps_en_test"


def test_zim_content_planet_tilejson(zim_fh: Archive):
    """Ensure proper content at planet TileJSON"""

    planet_json_item = zim_fh.get_item("planet")
    assert planet_json_item.mimetype == "application/json"
    planet_json = json.loads(bytes(planet_json_item.content))
    assert "tilejson" in planet_json
    assert "vector_layers" in planet_json
    assert "tiles" in planet_json
    assert planet_json["tiles"] == ["./tiles/{z}/{x}/{y}.pbf"]
