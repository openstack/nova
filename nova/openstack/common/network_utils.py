# Copyright 2012 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Network-related utilities and helper functions.
"""

import socket

from six.moves.urllib import parse

from nova.openstack.common.gettextutils import _LW
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def parse_host_port(address, default_port=None):
    """Interpret a string as a host:port pair.

    An IPv6 address MUST be escaped if accompanied by a port,
    because otherwise ambiguity ensues: 2001:db8:85a3::8a2e:370:7334
    means both [2001:db8:85a3::8a2e:370:7334] and
    [2001:db8:85a3::8a2e:370]:7334.

    >>> parse_host_port('server01:80')
    ('server01', 80)
    >>> parse_host_port('server01')
    ('server01', None)
    >>> parse_host_port('server01', default_port=1234)
    ('server01', 1234)
    >>> parse_host_port('[::1]:80')
    ('::1', 80)
    >>> parse_host_port('[::1]')
    ('::1', None)
    >>> parse_host_port('[::1]', default_port=1234)
    ('::1', 1234)
    >>> parse_host_port('2001:db8:85a3::8a2e:370:7334', default_port=1234)
    ('2001:db8:85a3::8a2e:370:7334', 1234)

    """
    if address[0] == '[':
        # Escaped ipv6
        _host, _port = address[1:].split(']')
        host = _host
        if ':' in _port:
            port = _port.split(':')[1]
        else:
            port = default_port
    else:
        if address.count(':') == 1:
            host, port = address.split(':')
        else:
            # 0 means ipv4, >1 means ipv6.
            # We prohibit unescaped ipv6 addresses with port.
            host = address
            port = default_port

    return (host, None if port is None else int(port))


class ModifiedSplitResult(parse.SplitResult):
    """Split results class for urlsplit."""

    # NOTE(dims): The functions below are needed for Python 2.6.x.
    # We can remove these when we drop support for 2.6.x.
    @property
    def hostname(self):
        netloc = self.netloc.split('@', 1)[-1]
        host, port = parse_host_port(netloc)
        return host

    @property
    def port(self):
        netloc = self.netloc.split('@', 1)[-1]
        host, port = parse_host_port(netloc)
        return port


def urlsplit(url, scheme='', allow_fragments=True):
    """Parse a URL using urlparse.urlsplit(), splitting query and fragments.
    This function papers over Python issue9374 when needed.

    The parameters are the same as urlparse.urlsplit.
    """
    scheme, netloc, path, query, fragment = parse.urlsplit(
        url, scheme, allow_fragments)
    if allow_fragments and '#' in path:
        path, fragment = path.split('#', 1)
    if '?' in path:
        path, query = path.split('?', 1)
    return ModifiedSplitResult(scheme, netloc,
                               path, query, fragment)


def set_tcp_keepalive(sock, tcp_keepalive=True,
                      tcp_keepidle=None,
                      tcp_keepalive_interval=None,
                      tcp_keepalive_count=None):
    """Set values for tcp keepalive parameters

    This function configures tcp keepalive parameters if users wish to do
    so.

    :param:tcp_keepalive: Boolean, turn on or off tcp_keepalive. If users are
    not sure, this should be True, and default values will be used
    :param:tcp_keepidle: time to wait before starting to send keepalive probes
    :param:tcp_keepalive_interval: time between successive probes, once the
    initial wait time is over
    :param:tcp_keepalive_count: number of probes to send before the connection
    is killed

    """

    # NOTE(praneshp): Despite keepalive being a tcp concept, the level is
    # still SOL_SOCKET. This is a quirk.
    if isinstance(tcp_keepalive, bool):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, tcp_keepalive)
    else:
        raise TypeError("tcp_keepalive must be a boolean")

    if not tcp_keepalive:
        return

    # These options aren't available in the OS X version of eventlet,
    # Idle + Count * Interval effectively gives you the total timeout.
    if tcp_keepidle is not None:
        if hasattr(socket, 'TCP_KEEPIDLE'):
            sock.setsockopt(socket.IPPROTO_TCP,
                            socket.TCP_KEEPIDLE,
                            tcp_keepidle)
        else:
            LOG.warning(_LW('tcp_keepidle not available on your system'))
    if tcp_keepalive_interval is not None:
        if hasattr(socket, 'TCP_KEEPINTVL'):
            sock.setsockopt(socket.IPPROTO_TCP,
                            socket.TCP_KEEPINTVL,
                            tcp_keepalive_interval)
        else:
            LOG.warning(_LW('tcp_keepintvl not available on your system'))
    if tcp_keepalive_count is not None:
        if hasattr(socket, 'TCP_KEEPCNT'):
            sock.setsockopt(socket.IPPROTO_TCP,
                            socket.TCP_KEEPCNT,
                            tcp_keepalive_count)
        else:
            LOG.warning(_LW('tcp_keepknt not available on your system'))
