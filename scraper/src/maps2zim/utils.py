from typing import Any

from maps2zim.context import Context

context = Context.get()
logger = context.logger


def backoff_hdlr(details: Any):
    """Default backoff handler to log something when backoff occurs"""
    logger.debug(
        "Request error, starting backoff of {wait:0.1f} seconds after {tries} "
        "tries".format(**details)
    )
