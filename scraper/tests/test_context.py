import re
from typing import Any

import pytest

from maps2zim.context import Context
from maps2zim.processor import context as processor_context

from . import CONTEXT_DEFAULTS


@pytest.fixture()
def context_defaults():
    return CONTEXT_DEFAULTS


def test_context_logger():
    # ensure we have only one logger object everywhere
    assert Context.logger == Context.get().logger


def test_context_defaults():
    context = Context.get()
    assert context == processor_context  # check both objects are same
    assert re.match(  # check getter logic
        r"maps2zim\/.* \(https:\/\/www\.kiwix\.org\) zimscraperlib\/.*",
        context.wm_user_agent,
    )
    context.current_thread_workitem = "context 123"
    assert context.current_thread_workitem == "context 123"


def test_context_setup_again(context_defaults: dict[str, Any]):
    settings = context_defaults.copy()
    settings["title"] = "A title"
    Context.setup(**settings)
    context = Context.get()
    assert context.title == "A title"
    assert context == processor_context  # check both objects are same
