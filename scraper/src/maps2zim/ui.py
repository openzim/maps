from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Model to transform Python snake_case into JSON camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ConfigModel(CamelModel):
    secondary_color: str
