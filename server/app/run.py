import os

import uvicorn

from .logging_config import logging_config


def main():
    uvicorn.run(
        "app.main:app",
        host=os.getenv("BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        access_log=False,
        log_config=logging_config(),
        ws_max_size=8192,
        ssl_certfile=os.getenv("TLS_CERTFILE"),
        ssl_keyfile=os.getenv("TLS_KEYFILE"),
    )


if __name__ == "__main__":
    main()
