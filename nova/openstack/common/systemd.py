# Copyright 2012-2014 Red Hat, Inc.
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
Helper module for systemd service readiness notification.
"""

import logging
import os
import socket
import sys


LOG = logging.getLogger(__name__)


def _abstractify(socket_name):
    if socket_name.startswith('@'):
        # abstract namespace socket
        socket_name = '\0%s' % socket_name[1:]
    return socket_name


def _sd_notify(unset_env, msg):
    notify_socket = os.getenv('NOTIFY_SOCKET')
    if notify_socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.connect(_abstractify(notify_socket))
            sock.sendall(msg)
            if unset_env:
                del os.environ['NOTIFY_SOCKET']
        except EnvironmentError:
            LOG.debug("Systemd notification failed", exc_info=True)
        finally:
            sock.close()


def notify():
    """Send notification to Systemd that service is ready.

    For details see
    http://www.freedesktop.org/software/systemd/man/sd_notify.html
    """
    _sd_notify(False, 'READY=1')


def notify_once():
    """Send notification once to Systemd that service is ready.

    Systemd sets NOTIFY_SOCKET environment variable with the name of the
    socket listening for notifications from services.
    This method removes the NOTIFY_SOCKET environment variable to ensure
    notification is sent only once.
    """
    _sd_notify(True, 'READY=1')


def onready(notify_socket, timeout):
    """Wait for systemd style notification on the socket.

    :param notify_socket: local socket address
    :type notify_socket:  string
    :param timeout:       socket timeout
    :type timeout:        float
    :returns:             0 service ready
                          1 service not ready
                          2 timeout occurred
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    sock.bind(_abstractify(notify_socket))
    try:
        msg = sock.recv(512)
    except socket.timeout:
        return 2
    finally:
        sock.close()
    if 'READY=1' in msg:
        return 0
    else:
        return 1


if __name__ == '__main__':
    # simple CLI for testing
    if len(sys.argv) == 1:
        notify()
    elif len(sys.argv) >= 2:
        timeout = float(sys.argv[1])
        notify_socket = os.getenv('NOTIFY_SOCKET')
        if notify_socket:
            retval = onready(notify_socket, timeout)
            sys.exit(retval)
