from __future__ import annotations

import pytest
import errno
from types import SimpleNamespace


def test_platform_api_defaults_to_separate_8789_port():
    from urban_design.server_config import resolve_server_config

    config = resolve_server_config(environ={})

    assert config.host == "127.0.0.1"
    assert config.port == 8789
    assert config.database_path == ".urban_design_runtime/state.sqlite3"


@pytest.mark.parametrize("reserved_port", [8787, 8788])
def test_platform_api_refuses_hermes_and_qgis_bridge_ports(reserved_port: int):
    from urban_design.server_config import ServerConfigurationError, resolve_server_config

    with pytest.raises(ServerConfigurationError, match="reserved"):
        resolve_server_config(environ={"URBAN_DESIGN_API_PORT": str(reserved_port)})


def test_platform_api_accepts_explicit_nonreserved_port_and_database():
    from urban_design.server_config import resolve_server_config

    config = resolve_server_config(
        environ={
            "URBAN_DESIGN_API_PORT": "8791",
            "URBAN_DESIGN_API_DATABASE": "/private/tmp/week4-test.sqlite3",
        }
    )

    assert config.port == 8791
    assert config.database_path == "/private/tmp/week4-test.sqlite3"


def test_platform_api_fails_closed_when_selected_port_is_occupied(monkeypatch):
    from urban_design.server_config import ServerConfigurationError, ensure_port_available

    class OccupiedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def setsockopt(self, *_args):
            return None

        def bind(self, _address):
            raise OSError(errno.EADDRINUSE, "address already in use")

    import urban_design.server_config as server_config

    monkeypatch.setattr(server_config.socket, "socket", lambda *_args: OccupiedSocket())
    monkeypatch.setattr(
        server_config.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="COMMAND PID\nserver 123\n"),
    )
    with pytest.raises(ServerConfigurationError, match="port 8790 is occupied.*server 123"):
        ensure_port_available("127.0.0.1", 8790)


def test_port_preflight_allows_recently_closed_socket_reuse(monkeypatch):
    from urban_design.server_config import ensure_port_available
    import urban_design.server_config as server_config

    class AvailableSocket:
        options = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def setsockopt(self, level, option, value):
            self.options.append((level, option, value))

        def bind(self, _address):
            return None

    socket_instance = AvailableSocket()
    monkeypatch.setattr(server_config.socket, "socket", lambda *_args: socket_instance)

    ensure_port_available("127.0.0.1", 8789)

    assert socket_instance.options == [(server_config.socket.SOL_SOCKET, server_config.socket.SO_REUSEADDR, 1)]
