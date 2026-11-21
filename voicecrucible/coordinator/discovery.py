"""Answers discovery queries on the LAN, so workers find the coordinator even after its IP changes (DHCP).

Only private / local addresses get an answer. The answer contains no secret: ID, API port, fingerprint.
"""

from __future__ import annotations

import ipaddress
import socket
import threading

from voicecrucible.core import log, protocol

_log = log.get(__name__)


def is_local_address(host: str) -> bool:
    """True for loopback, private (LAN) and link-local addresses."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class DiscoveryResponder:
    """UDP listener that answers valid discovery queries with the coordinator's beacon."""

    def __init__(self, port: int, coordinator_id: str, api_port: int, cert_fingerprint: str):
        self._beacon = protocol.make_beacon(coordinator_id, api_port, cert_fingerprint)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("", port))
        self._sock.settimeout(1.0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="discovery", daemon=True)

    def start(self) -> None:
        """Start answering in a background thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop answering and close the socket."""
        self._stop.set()
        self._thread.join(timeout=3)
        self._sock.close()

    def _run(self) -> None:
        """Answer loop."""
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(2048)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                if self._stop.is_set():
                    return
                continue
            if is_local_address(addr[0]) and protocol.is_query(data):
                try:
                    self._sock.sendto(self._beacon, addr)
                except OSError as e:
                    _log.debug("discovery answer to %s failed: %s", addr[0], e)
