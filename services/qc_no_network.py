"""No-network guard for offline QCs.

Incident 2026-11-01: an offline QC run made one live Odds API request (HTTP 401). An offline QC
must be unable to reach the network -- not merely intended not to. `install()` replaces the
socket layer's outbound entry points so any non-loopback connection or DNS lookup raises
`NetworkBlocked` (loudly, so the QC fails instead of silently spending a paid call).

Coverage:
  * in-process: socket.connect / connect_ex / create_connection / getaddrinfo (urllib, requests,
    http.client and every other client sit on these);
  * child Python processes: `child_env()` returns an environment whose PYTHONPATH puts
    `services/qc_offline_site` first, whose sitecustomize re-installs this guard when
    BK_QC_OFFLINE=1 -- so a QC that shells out to another script is covered too.

Loopback (127.0.0.0/8, ::1, localhost) stays allowed: local test servers are not the network.
A QC that genuinely needs the network declares `REQUIRES_NETWORK = True` and checks
`offline_mode()` so it reports NOT RUN instead of calling out.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

ENV_FLAG = 'BK_QC_OFFLINE'
SITE_DIR = Path(__file__).resolve().parent / 'qc_offline_site'
_LOOPBACK_NAMES = {'localhost', 'localhost.localdomain', 'ip6-localhost'}
_installed = False


class NetworkBlocked(RuntimeError):
    """Raised when an offline QC attempts a non-loopback network operation."""


def offline_mode() -> bool:
    return os.environ.get(ENV_FLAG) == '1'


def _is_loopback(host) -> bool:
    if host is None:
        return False
    h = host.decode() if isinstance(host, bytes) else str(host)
    h = h.strip('[]').lower()
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h.split('%', 1)[0]).is_loopback
    except ValueError:
        return False


def _host_of(address):
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return None  # AF_UNIX path etc. -- not a network address


def install() -> None:
    """Block all non-loopback outbound network access in this process. Idempotent."""
    global _installed
    if _installed:
        return
    os.environ[ENV_FLAG] = '1'
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _check(address):
        if isinstance(address, (str, bytes)):
            return  # unix-domain socket path
        host = _host_of(address)
        if not _is_loopback(host):
            raise NetworkBlocked(f'offline QC attempted a network connection to {address!r}')

    def connect(self, address):
        _check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *a, **k):
        if not _is_loopback(host):
            raise NetworkBlocked(f'offline QC attempted a DNS lookup for {host!r}')
        return real_getaddrinfo(host, *a, **k)

    def create_connection(address, *a, **k):
        _check(address)
        return _real_create_connection(address, *a, **k)

    _real_create_connection = socket.create_connection
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    socket.create_connection = create_connection
    _installed = True


def child_env(base=None) -> dict:
    """Environment for a child process that inherits the guard."""
    env = dict(os.environ if base is None else base)
    env[ENV_FLAG] = '1'
    prev = env.get('PYTHONPATH')
    env['PYTHONPATH'] = str(SITE_DIR) + (os.pathsep + prev if prev else '')
    return env
