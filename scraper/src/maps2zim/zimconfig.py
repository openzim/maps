from pydantic import BaseModel

from maps2zim.errors import InvalidFormatError

DEFAULT_TAGS: list[str] = [
    "_sw:no",
    "_ftindex:no",
    "_pictures:yes",
    "_videos:no",
    "_details:yes",
]


class ZimConfig(BaseModel):
    """Common configuration for building ZIM files."""

    # File name for the ZIM.
    file_name: str
    # Name for the ZIM.
    name: str
    # Human readable title for the ZIM.
    title: str
    # Publisher for the ZIM.
    publisher: str
    # Creator of the content in the ZIM.
    creator: str
    # Short description for the ZIM.
    description: str
    # Long description for the ZIM.
    long_description: str | None
    # List of tags to apply to the ZIM.
    tags: list[str] | None
    # Secondary (background) color of ZIM UI
    secondary_color: str

    def format(self, placeholders: dict[str, str]) -> ZimConfig:
        """Creates a ZimConfig with placeholders replaced and results checked.

        Raises:
          InvalidFormatError if one of the placeholders is invalid.
          ValueError if formatted value is too long (when restricted).
        """

        def fmt(string: str) -> str:
            try:
                return string.format(**placeholders)
            except KeyError as e:
                valid_placeholders = ", ".join(sorted(placeholders.keys()))
                raise InvalidFormatError(
                    f"Invalid placeholder {e!s} in {string!s}, "
                    f"valid placeholders are: {valid_placeholders}"
                ) from e

        formatted_tags = [fmt(tag) for tag in self.tags] if self.tags else []
        # Build a dict of tag key -> tag value from default tags, then override
        # with user-provided tags (key is the part before the colon).
        merged: dict[str, str] = {}
        for tag in DEFAULT_TAGS + formatted_tags:
            key = tag.split(":")[0] if ":" in tag else tag
            merged[key] = tag
        return ZimConfig(
            secondary_color=self.secondary_color,
            file_name=fmt(self.file_name),
            name=fmt(self.name),
            title=fmt(self.title),
            publisher=self.publisher,
            creator=self.creator,
            description=fmt(self.description),
            long_description=(
                fmt(self.long_description) if self.long_description else None
            ),
            tags=list(merged.values()),
        )
