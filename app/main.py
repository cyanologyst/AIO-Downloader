from __future__ import annotations

import logging
from pathlib import Path

from app.config import SettingsStore
from app.web.app import create_app


def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    configure_logging()
    store = SettingsStore()
    settings = store.get()
    app = create_app(store)
    app.run(host=settings.web_host, port=settings.web_port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
