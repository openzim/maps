import threading
from typing import Any

from zimscraperlib.download import get_session

from maps2zim.context import Context

CONTEXT_DEFAULTS: dict[str, Any] = {
    "web_session": get_session(),
    "tmp_folder": None,
    "_current_thread_workitem": threading.local(),
    "name": None,
    "title": None,
    "description": None,
    "assets_folder": None,
}

# initialize a context since it is a requirement for most modules to load
Context.setup(**CONTEXT_DEFAULTS)

context = Context.get()
