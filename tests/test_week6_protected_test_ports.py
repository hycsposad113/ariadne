"""Regression: occupancy tests may never bind a protected service port."""
import socket
import pytest
import test_m2a02_plugin_launcher as launcher_tests

@pytest.mark.parametrize('name', [
    'test_launcher_fails_safely_when_8788_is_already_listening',
    'test_bridge_cli_fails_safely_when_default_port_is_occupied',
])
def test_occupancy_regressions_never_bind_protected_ports(name, monkeypatch, capsys, tmp_path):
    bind = socket.socket.bind
    attempted = []
    def guarded_bind(sock, address):
        attempted.append(address[1])
        assert 8940 <= address[1] <= 8949, f'Forbidden test bind: {address[1]}'
        return bind(sock, address)
    monkeypatch.setattr(socket.socket, 'bind', guarded_bind)
    test = getattr(launcher_tests, name)
    if name.startswith('test_bridge'):
        test(capsys, monkeypatch)
    else:
        test(tmp_path)
    assert attempted
