"""Safe loopback port selection for isolated local browser tests."""

from __future__ import annotations

import socket


RESERVED_LOOPBACK_PORTS = {
    5173: "the existing developer web server",
    8787: "Hermes Web UI",
    8788: "the QGIS StudyArea bridge",
    8789: "the Urban Design platform API",
}


def select_loopback_port(requested: int | None, *, excluded: set[int] | None = None) -> int:
    """Return a bindable loopback port and refuse to reuse an occupied one."""
    excluded = excluded or set()
    if requested is not None:
        if requested < 1 or requested > 65535:
            raise ValueError(f"port must be in 1..65535: {requested}")
        if requested in RESERVED_LOOPBACK_PORTS:
            owner = RESERVED_LOOPBACK_PORTS[requested]
            raise RuntimeError(f"requested port {requested} is reserved for {owner}; refusing to launch")
        candidates = [requested]
    else:
        candidates = []
        for _ in range(20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                candidates.append(int(probe.getsockname()[1]))
    for port in candidates:
        if port in RESERVED_LOOPBACK_PORTS:
            continue
        if port in excluded:
            if requested is not None:
                raise RuntimeError(f"requested port {port} duplicates another E2E service; refusing to launch")
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                if requested is not None:
                    raise RuntimeError(f"requested port {port} is occupied; refusing to reuse or stop its owner") from exc
                continue
        return port
    raise RuntimeError("could not find an unused loopback port for the isolated browser E2E")


def resolve_e2e_ports(api_port: int | None = None, web_port: int | None = None) -> tuple[int, int]:
    api = select_loopback_port(api_port)
    web = select_loopback_port(web_port, excluded={api})
    return api, web
