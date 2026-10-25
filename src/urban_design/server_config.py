"""Configuration and fail-closed port checks for the local platform API."""

from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


HERMES_PORT = 8787
QGIS_BRIDGE_PORT = 8788
DEFAULT_PLATFORM_API_PORT = 8789
RESERVED_PORTS = {HERMES_PORT, QGIS_BRIDGE_PORT}


class ServerConfigurationError(ValueError):
    """Raised when API configuration would overlap a protected service."""


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    database_path: str


def resolve_server_config(
    *,
    environ: Mapping[str, str] | None = None,
    host: str | None = None,
    port: int | None = None,
    database_path: str | Path | None = None,
) -> ServerConfig:
    env = os.environ if environ is None else environ
    resolved_host = host or env.get("URBAN_DESIGN_API_HOST", "127.0.0.1")
    raw_port = port if port is not None else env.get("URBAN_DESIGN_API_PORT", str(DEFAULT_PLATFORM_API_PORT))
    try:
        resolved_port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ServerConfigurationError("URBAN_DESIGN_API_PORT must be an integer") from exc
    if not 1 <= resolved_port <= 65535:
        raise ServerConfigurationError("URBAN_DESIGN_API_PORT must be within 1..65535")
    if resolved_port in RESERVED_PORTS:
        owner = "Hermes" if resolved_port == HERMES_PORT else "the QGIS bridge"
        raise ServerConfigurationError(
            f"port {resolved_port} is reserved for {owner}; platform API startup refused"
        )
    resolved_database = database_path or env.get(
        "URBAN_DESIGN_API_DATABASE", ".urban_design_runtime/state.sqlite3"
    )
    return ServerConfig(
        host=resolved_host,
        port=resolved_port,
        database_path=str(resolved_database),
    )


def ensure_port_available(host: str, port: int) -> None:
    """Refuse to start if another listener owns this exact local API port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # Let a recently closed local server pass through TIME_WAIT while
            # a still-listening owner continues to fail with EADDRINUSE.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
    except OSError as exc:
        if exc.errno not in {48, 98, 10048}:  # EADDRINUSE on macOS/Linux/Windows
            raise ServerConfigurationError(f"cannot preflight {host}:{port}: {exc}") from exc
        owner_detail = "owner could not be identified"
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            rows = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
            if rows:
                owner_detail = "; ".join(rows)
        except (OSError, subprocess.SubprocessError):
            pass
        raise ServerConfigurationError(
            f"port {port} is occupied; refusing to choose another port or stop its owner ({owner_detail})"
        ) from exc
