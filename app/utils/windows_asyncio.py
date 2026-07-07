from __future__ import annotations

import socket
import sys
import time
from typing import Any


_INSTALLED = False


def install_socketpair_retry() -> None:
    """Retry Windows' TCP-backed socketpair when localhost is noisy.

    CPython's Windows ``socket.socketpair`` fallback opens a temporary localhost
    listener and rejects the connection if another local process reaches it
    first. Some machines with aggressive network/security tooling can hit this
    repeatedly during asyncio loop creation, causing desktop startup and tests
    to fail with ``ConnectionError("Unexpected peer connection")``.
    """

    global _INSTALLED
    if _INSTALLED or sys.platform != "win32":
        return

    def socketpair_robust(
        family: socket.AddressFamily = socket.AF_INET,
        type: socket.SocketKind = socket.SOCK_STREAM,
        proto: int = 0,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[socket.socket, socket.socket]:
        if args or kwargs:
            raise TypeError("socketpair() accepts family, type, and proto only")
        if family == socket.AF_INET:
            host = "127.0.0.1"
        elif family == socket.AF_INET6:
            host = "::1"
        else:
            raise ValueError("Only AF_INET and AF_INET6 socket address families are supported")
        if type != socket.SOCK_STREAM:
            raise ValueError("Only SOCK_STREAM socket type is supported")
        if proto != 0:
            raise ValueError("Only protocol zero is supported")

        listener = socket.socket(family, type, proto)
        client: socket.socket | None = None
        accepted: list[socket.socket] = []
        try:
            listener.bind((host, 0))
            listener.listen(8)
            listener.settimeout(0.15)
            addr, port = listener.getsockname()[:2]

            client = socket.socket(family, type, proto)
            client.connect((addr, port))

            deadline = time.monotonic() + 3
            last_error: OSError | None = None
            while time.monotonic() < deadline:
                try:
                    server, remote = listener.accept()
                except TimeoutError as exc:
                    last_error = exc
                    continue
                except OSError as exc:
                    last_error = exc
                    continue

                try:
                    # On noisy Windows localhost stacks, the tuple identity
                    # check used by CPython's fallback can reject a perfectly
                    # usable local pair. The client has already connected to
                    # this private listener, so the first accepted local stream
                    # is the event-loop wakeup pair we need.
                    if remote[0] in {host, "localhost", "::1", "127.0.0.1"}:
                        for stray in accepted:
                            stray.close()
                        return server, client
                    server_local = server.getsockname()
                    client_remote = client.getpeername()
                    client_local = client.getsockname()
                    server_remote = server.getpeername()
                    if server_local[:2] == client_remote[:2] and client_local[:2] == server_remote[:2]:
                        for stray in accepted:
                            stray.close()
                        return server, client
                    if remote[:2] == client_local[:2]:
                        for stray in accepted:
                            stray.close()
                        return server, client
                except OSError as exc:
                    last_error = exc

                accepted.append(server)

            raise ConnectionError("Unexpected peer connection") from last_error
        except BaseException:
            if client is not None:
                client.close()
            for stray in accepted:
                stray.close()
            raise
        finally:
            listener.close()

    socket.socketpair = socketpair_robust
    _INSTALLED = True
