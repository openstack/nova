# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

import paramiko

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

CONNECTION_TIMEOUT = 60


class ConnectionFailed(exception.NovaException):
        msg_fmt = _('Connection failed')


class Connection(object):

    def __init__(self, host, username, password, port=22, keyfile=None):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.keyfile = keyfile


def ssh_connect(connection):
    """Method to connect to remote system using ssh protocol.

    :param connection: a Connection object.
    :returns: paramiko.SSHClient -- an active ssh connection.
    :raises: ConnectionFailed
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(connection.host,
                    username=connection.username,
                    password=connection.password,
                    port=connection.port,
                    key_filename=connection.keyfile,
                    timeout=CONNECTION_TIMEOUT)

        LOG.debug("SSH connection with %s established successfully." %
                  connection.host)

        # send TCP keepalive packets every 20 seconds
        ssh.get_transport().set_keepalive(20)

        return ssh
    except Exception:
        LOG.exception(_('Connection error'))
        raise ConnectionFailed()
