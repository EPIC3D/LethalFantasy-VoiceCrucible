"""Find coordinators on the LAN: broadcast a query and collect the answers (no listening port needed)."""

from __future__ import annotations

import socket
import time

from voicecrucible.core import protocol


def find_coordinators(port: int, timeout: float = 3.0) -> list[dict]:
    """Coordinators that answered within `timeout`: dicts with id, host, port, fp."""
    found: dict[str, dict] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.3)
        query = protocol.make_query()
        deadline = time.monotonic() + timeout
        next_send = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_send:  # repeat the query: UDP may drop packets
                for target in ("255.255.255.255", "127.0.0.1"):
                    try:
                        sock.sendto(query, (target, port))
                    except OSError:
                        pass
                next_send = time.monotonic() + 1.0
            try:
                data, addr = sock.recvfrom(2048)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                continue
            beacon = protocol.parse_beacon(data)
            if beacon is not None and beacon["id"] not in found:
                found[beacon["id"]] = {**beacon, "host": addr[0]}
    finally:
        sock.close()
    return list(found.values())
