import copy
import logging
import re

from uvicorn.config import LOGGING_CONFIG


class RedactTicket(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(r"([?&]ticket=)[^&\s\"']+", r"\1[REDACTED]", record.getMessage())
        record.args = ()
        return True


def logging_config() -> dict:
    config = copy.deepcopy(LOGGING_CONFIG)
    config["filters"] = {"redact_ticket": {"()": "app.logging_config.RedactTicket"}}
    # Uvicorn logs WS handshake URLs through uvicorn.error, even without access logs.
    config["handlers"]["default"]["filters"] = ["redact_ticket"]
    return config
