import pathlib
from typing import IO

import requests
import requests.structures
from zimscraperlib.download import stream_file as stream_file_orig

from maps2zim.context import Context

context = Context.get()


def stream_file(
    url: str,
    fpath: pathlib.Path | None = None,
    byte_stream: IO[bytes] | None = None,
    block_size: int | None = 1024,
    proxies: dict[str, str] | None = None,
    max_retries: int | None = 5,
    headers: dict[str, str] | None = None,
    *,
    only_first_block: bool | None = False,
) -> tuple[int, requests.structures.CaseInsensitiveDict[str]]:
    """Customized version of zimscraperlib stream_file

    We customize the User-Agent header, the session and the timeout
    """
    if headers is None:
        headers = {}
    headers["User-Agent"] = context.wm_user_agent
    return stream_file_orig(
        url=url,
        fpath=fpath,
        byte_stream=byte_stream,
        block_size=block_size,
        proxies=proxies,
        max_retries=max_retries,
        headers=headers,
        session=context.web_session,
        only_first_block=only_first_block,
        timeout=context.http_timeout_normal_seconds,
    )
