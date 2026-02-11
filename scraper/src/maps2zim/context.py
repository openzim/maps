import dataclasses
import logging
import os
import threading
from pathlib import Path
from typing import Any

import requests
from zimscraperlib.constants import NAME as SCRAPERLIB_NAME
from zimscraperlib.constants import VERSION as SCRAPERLIB_VERSION
from zimscraperlib.logging import DEFAULT_FORMAT_WITH_THREADS, getLogger

from maps2zim.constants import (
    NAME,
    VERSION,
)

MAPS_TMP = os.getenv("MAPS_TMP")


@dataclasses.dataclass(kw_only=True)
class Context:
    """Class holding every contextual / configuration bits which can be moved

    Used to easily pass information around in the scraper. One singleton instance is
    always available.
    """

    # singleton instance
    _instance: Context | None = None

    # debug flag
    debug: bool = False

    # web session to use everywhere
    web_session: requests.Session

    # info passed in User-Agent header of web requests
    contact_info: str = "https://www.kiwix.org"

    # temporary folder to store temporary assets (e.g. cached API response)
    tmp_folder: Path

    # folder to fetch / store downloaded assets (can be reused across runs)
    assets_folder: Path

    # folder where the ZIM will be built
    output_folder: Path = Path(os.getenv("MAPS_OUTPUT", "output"))

    # folder where Vue.JS UI has been built
    zimui_dist: Path = Path(os.getenv("MAPS_ZIMUI_DIST", "../zimui/dist"))

    # Path to store the progress JSON file to
    stats_filename: Path | None = None

    # URL to illustration to use for ZIM illustration and favicon
    illustration_url: str = (
        "https://upload.wikimedia.org/wikipedia/commons/b/b0/Openstreetmap_logo.svg"
    )

    # Do not fail if ZIM already exists, overwrite it
    overwrite_existing_zim: bool = False

    # current processing info to use for debug message / exception
    _current_thread_workitem: threading.local

    # ZIM language
    language_iso_639_3: str = "eng"

    # normal and long timeouts to use in HTTP calls
    http_timeout_normal_seconds: int = 15
    http_timeout_long_seconds: int = 30

    # ZIM properties
    creator: str = "openZIM"
    publisher: str = "openZIM"
    file_name: str = "{name}_{period}"
    name: str
    title: str
    description: str
    long_description: str | None = None
    tags: list[str] | None = None

    # secondary color of the UI
    secondary_color: str = "#FFFFFF"

    # logger to use everywhere (do not mind about mutability, we want to reuse same
    # logger everywhere)
    logger: logging.Logger = getLogger(  # noqa: RUF009
        NAME, level=logging.DEBUG, log_format=DEFAULT_FORMAT_WITH_THREADS
    )

    # ------------------------------
    # Maps specific arguments
    # ------------------------------

    # By default, download only monaco area ; specify planet to download the whole
    # planet
    area: str = "monaco"

    @classmethod
    def setup(cls, **kwargs: Any):
        new_instance = cls(**kwargs)
        if cls._instance:
            # replace values 'in-place' so that we do not change the Context object
            # which might be already imported in some modules
            for field in dataclasses.fields(new_instance):
                cls._instance.__setattr__(
                    field.name, new_instance.__getattribute__(field.name)
                )
        else:
            cls._instance = new_instance

    @classmethod
    def get(cls) -> Context:
        if not cls._instance:
            raise OSError("Uninitialized context")  # pragma: no cover
        return cls._instance

    @property
    def current_thread_workitem(self) -> str:
        return getattr(self._current_thread_workitem, "value", "startup")

    @current_thread_workitem.setter
    def current_thread_workitem(self, value: str):
        self._current_thread_workitem.value = value
        Context.logger.debug(f"Processing {value}")

    @property
    def wm_user_agent(self) -> str:
        """User-Agent header compliant with Wikimedia requirements"""
        return (
            f"{NAME}/{VERSION} ({self.contact_info}) "
            f"{SCRAPERLIB_NAME}/{SCRAPERLIB_VERSION}"
        )
