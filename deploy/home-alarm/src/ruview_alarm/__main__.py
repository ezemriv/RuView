"""Process entry point for the RuView home alarm service."""

import asyncio
import logging
import time

from pydantic import ValidationError

from ruview_alarm.config import Settings
from ruview_alarm.service import run_alarm


def _configure_logging() -> None:
    """Configure process logging with UTC timestamps."""
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main() -> int:
    """Load configuration and run, emitting only secret-safe fatal summaries."""
    _configure_logging()
    logger = logging.getLogger("ruview_alarm")
    try:
        settings = Settings()
        asyncio.run(run_alarm(settings))
    except ValidationError:
        logger.error("Alarm configuration or persisted state is invalid")
        return 1
    except OSError:
        logger.error("Alarm state or health storage failed")
        return 1
    except Exception:
        logger.error("Alarm service terminated unexpectedly")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
