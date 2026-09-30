"""
Lifecycle bootstrap for the resident method-complexity HTTP service.

The service is started once per physical machine: when ``python app.py``
relaunches itself under Streamlit, the launcher process starts the API
thread before spawning the Streamlit child, so the endpoint is available
before any browser session exists. The Streamlit side probes the chosen
port and reuses the running service instead of binding a second one.
"""

import json
import os
import socket
import threading
from typing import Optional

from method_complexity_service import create_server, API_ROUTE

DEFAULT_PORT = 8765
PORT_SCAN_RANGE = 10

_lock = threading.Lock()
_server = None
_active_port: Optional[int] = None


def starting_port() -> int:
    """Preferred API port (env override for tests / shared hosts)."""
    return int(os.environ.get("METHOD_COMPLEXITY_PORT", str(DEFAULT_PORT)))


def is_service_alive(port: int) -> bool:
    """Return True if a method-complexity service answers on ``port``."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    except OSError:
        return False

    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{API_ROUTE}", timeout=2
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return "records" in payload


def start_service_thread(port: Optional[int] = None) -> Optional[int]:
    """
    Start the API in a daemon thread, or adopt an already-running one.

    Returns the active port number, or ``None`` when no port could be
    bound (the dashboard keeps working without the API).
    """
    global _server, _active_port

    with _lock:
        if _active_port is not None:
            return _active_port

        preferred = port if port is not None else starting_port()
        for candidate in range(preferred, preferred + PORT_SCAN_RANGE):
            if is_service_alive(candidate):
                _active_port = candidate
                return candidate

        last_error = None
        for candidate in range(preferred, preferred + PORT_SCAN_RANGE):
            try:
                server = create_server(candidate)
            except OSError as error:
                last_error = error
                continue
            thread = threading.Thread(
                target=server.serve_forever,
                name="method-complexity-api",
                daemon=True,
            )
            thread.start()
            _server = server
            _active_port = candidate
            return candidate

        if last_error is not None:
            # Surface problems during testing; the dashboard ignores them.
            if os.environ.get("METHOD_COMPLEXITY_STRICT"):
                raise RuntimeError(
                    f"Could not start method-complexity service: {last_error}"
                )
        return None


def active_port() -> Optional[int]:
    """Port the current process is using (or adopted)."""
    return _active_port
