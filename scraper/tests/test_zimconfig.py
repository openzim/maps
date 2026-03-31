import pytest

from maps2zim.errors import InvalidFormatError
from maps2zim.zimconfig import DEFAULT_TAGS, ZimConfig


def make_config(tags: list[str] | None = None) -> ZimConfig:
    return ZimConfig(
        file_name="test_{region}",
        name="test_{region}",
        title="Test {region}",
        publisher="Publisher",
        creator="Creator",
        description="Desc {region}",
        long_description=None,
        tags=tags,
        secondary_color="#FFFFFF",
    )


PLACEHOLDERS = {"region": "world"}


def test_format_includes_default_tags_when_no_tags():
    config = make_config(tags=None)
    result = config.format(PLACEHOLDERS)
    assert result.tags == DEFAULT_TAGS


def test_format_default_tags_overridden_by_user_tag():
    config = make_config(tags=["_videos:yes"])
    result = config.format(PLACEHOLDERS)
    assert result.tags is not None
    # _videos:no from defaults should be replaced by _videos:yes
    assert "_videos:yes" in result.tags
    assert "_videos:no" not in result.tags


def test_format_all_default_tags_present_with_override():
    config = make_config(tags=["_videos:yes"])
    result = config.format(PLACEHOLDERS)
    assert result.tags is not None
    for default_tag in DEFAULT_TAGS:
        key = default_tag.split(":")[0]
        assert any(t.startswith(key + ":") for t in result.tags)


def test_format_extra_user_tag_added():
    config = make_config(tags=["custom_tag"])
    result = config.format(PLACEHOLDERS)
    assert result.tags is not None
    assert "custom_tag" in result.tags
    # All defaults still present
    for default_tag in DEFAULT_TAGS:
        assert default_tag in result.tags


def test_format_multiple_overrides():
    config = make_config(tags=["_videos:yes", "_pictures:no"])
    result = config.format(PLACEHOLDERS)
    assert result.tags is not None
    assert "_videos:yes" in result.tags
    assert "_videos:no" not in result.tags
    assert "_pictures:no" in result.tags
    assert "_pictures:yes" not in result.tags


def test_format_tags_with_placeholder():
    config = make_config(tags=["region_{region}"])
    result = config.format(PLACEHOLDERS)
    assert result.tags is not None
    assert "region_world" in result.tags


def test_format_invalid_placeholder_raises():
    config = make_config(tags=["_{bad_key}:yes"])
    with pytest.raises(InvalidFormatError):
        config.format(PLACEHOLDERS)
