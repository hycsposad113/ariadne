"""Port selection must fail safely for isolated browser integration runs."""

import pytest

from urban_design.e2e_ports import RESERVED_LOOPBACK_PORTS, resolve_e2e_ports, select_loopback_port


class _SocketProbe:
    next_ephemeral = 41000
    occupied: set[int] = set()

    def __init__(self, *_args):
        self.port = None

    def bind(self, address):
        port = int(address[1])
        if port == 0:
            port = self.next_ephemeral
            type(self).next_ephemeral += 1
        if port in self.occupied:
            raise OSError("address already in use")
        self.port = port

    def getsockname(self):
        return ("127.0.0.1", self.port)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.fixture(autouse=True)
def fake_loopback_sockets(monkeypatch):
    import urban_design.e2e_ports as e2e_ports

    _SocketProbe.next_ephemeral = 41000
    _SocketProbe.occupied = set()
    monkeypatch.setattr(e2e_ports.socket, "socket", _SocketProbe)


def test_e2e_ports_are_distinct_and_bindable():
    api_port, web_port = resolve_e2e_ports()
    assert api_port != web_port
    assert api_port == 41000
    assert web_port == 41020  # The first 19 candidates are gathered before exclusion is applied.


def test_explicit_occupied_port_is_refused_without_reusing_owner():
    port = 42000
    _SocketProbe.occupied.add(port)
    with pytest.raises(RuntimeError, match="occupied; refusing to reuse or stop its owner"):
        select_loopback_port(port)
    assert port in _SocketProbe.occupied


def test_duplicate_explicit_e2e_ports_are_refused():
    port = 43000
    with pytest.raises(RuntimeError, match="duplicates another E2E service"):
        resolve_e2e_ports(port, port)


@pytest.mark.parametrize(("port", "owner"), RESERVED_LOOPBACK_PORTS.items())
def test_reserved_service_ports_are_refused_even_when_free(port, owner):
    with pytest.raises(RuntimeError, match=f"port {port} is reserved for {owner}"):
        select_loopback_port(port)


def test_ephemeral_selection_skips_reserved_service_ports():
    _SocketProbe.next_ephemeral = 8787
    api_port, web_port = resolve_e2e_ports()
    assert api_port == 8790
    assert web_port == 8807
    assert api_port not in RESERVED_LOOPBACK_PORTS
    assert web_port not in RESERVED_LOOPBACK_PORTS
