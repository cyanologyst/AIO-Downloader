from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

from werkzeug.serving import BaseWSGIServer, make_server

from app.config import SettingsStore
from app.main import configure_logging
from app.utils.runtime import webview_data_dir
from app.web.app import create_app


@dataclass(slots=True)
class DesktopServer:
    server: BaseWSGIServer
    thread: threading.Thread
    url: str

    def shutdown(self) -> None:
        self.server.shutdown()
        if self.thread.is_alive():
            self.thread.join(timeout=2)


class DesktopApi:
    def __init__(self) -> None:
        self._window: Any | None = None
        self._server: DesktopServer | None = None

    def bind(self, window: Any, server: DesktopServer) -> None:
        self._window = window
        self._server = server

    def minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def close(self) -> None:
        if self._server:
            threading.Thread(target=self._server.shutdown, daemon=True).start()
        if self._window:
            self._window.destroy()


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def _start_server(store: SettingsStore) -> DesktopServer:
    settings = store.get()
    host = settings.web_host if settings.web_host not in {"0.0.0.0", "::"} else "127.0.0.1"
    requested_port = settings.web_port
    port = requested_port if _port_available(host, requested_port) else 0
    app = create_app(store)
    server = make_server(host, port, app, threaded=True)
    actual_port = int(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{actual_port}/?desktop=1"
    return DesktopServer(server=server, thread=thread, url=url)


def main() -> None:
    configure_logging()
    store = SettingsStore()
    server = _start_server(store)
    logging.info("Desktop server listening at %s", server.url)

    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywebview. Install it with: python -m pip install pywebview"
        ) from exc

    webview.settings["DRAG_REGION_SELECTOR"] = ".pywebview-drag-region"
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = False

    api = DesktopApi()
    window = webview.create_window(
        "AIO Downloader",
        server.url,
        js_api=api,
        width=1440,
        height=920,
        min_size=(1080, 680),
        frameless=True,
        easy_drag=False,
        shadow=False,
        transparent=False,
        background_color="#06111b",
        text_select=True,
        draggable=True,
    )
    api.bind(window, server)

    def cleanup(*_args: object) -> None:
        time.sleep(0.2)
        server.shutdown()

    if window:
        window.events.closed += cleanup
    storage_path = webview_data_dir()
    storage_path.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage_path.resolve()))


if __name__ == "__main__":
    main()
