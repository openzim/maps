import sys
import tempfile

from maps2zim.context import Context
from maps2zim.entrypoint import prepare_context

logger = Context.logger


def main():
    try:
        with tempfile.TemporaryDirectory() as tmpdir:

            prepare_context(sys.argv[1:], tmpdir)

            # import this only once the Context has been initialized, so that it gets an
            # initialized context
            from maps2zim.processor import Processor  # noqa: PLC0415

            Processor().run()

    except SystemExit as exc:
        if exc.code != 0:
            logger.error("Scraper failed, exiting")
        raise
    except Exception as exc:
        logger.exception(exc)
        logger.error(f"Scraper failed with the following error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
