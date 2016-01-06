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

"""Serial consoles module."""

import socket

from oslo_log import log as logging
import six.moves

import nova.conf
from nova import exception
from nova.i18n import _LW
from nova import utils

LOG = logging.getLogger(__name__)

ALLOCATED_PORTS = set()  # in-memory set of already allocated ports
SERIAL_LOCK = 'serial-lock'

CONF = nova.conf.CONF

# TODO(sahid): Add a method to initialize ALOCATED_PORTS with the
# already binded TPC port(s). (cf from danpb: list all running guests and
# query the XML in libvirt driver to find out the TCP port(s) it uses).


@utils.synchronized(SERIAL_LOCK)
def acquire_port(host):
    """Returns a free TCP port on host.

    Find and returns a free TCP port on 'host' in the range
    of 'CONF.serial_console.port_range'.
    """

    start, stop = _get_port_range()

    for port in six.moves.range(start, stop):
        if (host, port) in ALLOCATED_PORTS:
            continue
        try:
            _verify_port(host, port)
            ALLOCATED_PORTS.add((host, port))
            return port
        except exception.SocketPortInUseException as e:
            LOG.warning(e.format_message())

    raise exception.SocketPortRangeExhaustedException(host=host)


@utils.synchronized(SERIAL_LOCK)
def release_port(host, port):
    """Release TCP port to be used next time."""
    ALLOCATED_PORTS.discard((host, port))


def _get_port_range():
    config_range = CONF.serial_console.port_range
    try:
        start, stop = map(int, config_range.split(':'))
        if start >= stop:
            raise ValueError
    except ValueError:
        default_port_range = nova.conf.serial_console.DEFAULT_PORT_RANGE
        LOG.warning(_LW("serial_console.port_range should be <num>:<num>. "
                        "Given value %(port_range)s could not be parsed. "
                        "Taking the default port range %(default)s."),
                    {'port_range': config_range,
                     'default': default_port_range})
        start, stop = map(int, default_port_range.split(':'))
    return start, stop


def _verify_port(host, port):
    s = socket.socket()
    try:
        s.bind((host, port))
    except socket.error as e:
        raise exception.SocketPortInUseException(
            host=host, port=port, error=e)
    finally:
        s.close()
