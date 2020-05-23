# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 OpenStack Foundation
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

"""Utility methods for working with WSGI servers."""

import os.path
import socket
import ssl

import eventlet
import eventlet.wsgi
import greenlet
from oslo_log import log as logging
from oslo_service import service
from oslo_utils import excutils

import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class Server(service.ServiceBase):
    """Server class to manage a WSGI server, serving a WSGI application."""

    default_pool_size = CONF.wsgi.default_pool_size

    def __init__(self, name, app, host='0.0.0.0', port=0, pool_size=None,
                       protocol=eventlet.wsgi.HttpProtocol, backlog=128,
                       use_ssl=False, max_url_len=None):
        """Initialize, but do not start, a WSGI server.

        :param name: Pretty name for logging.
        :param app: The WSGI application to serve.
        :param host: IP address to serve the application.
        :param port: Port number to server the application.
        :param pool_size: Maximum number of eventlets to spawn concurrently.
        :param backlog: Maximum number of queued connections.
        :param max_url_len: Maximum length of permitted URLs.
        :returns: None
        :raises: nova.exception.InvalidInput
        """
        # Allow operators to customize http requests max header line size.
        eventlet.wsgi.MAX_HEADER_LINE = CONF.wsgi.max_header_line
        self.name = name
        self.app = app
        self._server = None
        self._protocol = protocol
        self.pool_size = pool_size or self.default_pool_size
        self._pool = eventlet.GreenPool(self.pool_size)
        self._logger = logging.getLogger("nova.%s.wsgi.server" % self.name)
        self._use_ssl = use_ssl
        self._max_url_len = max_url_len
        self.client_socket_timeout = CONF.wsgi.client_socket_timeout or None

        if backlog < 1:
            raise exception.InvalidInput(
                    reason=_('The backlog must be more than 0'))

        bind_addr = (host, port)
        # TODO(dims): eventlet's green dns/socket module does not actually
        # support IPv6 in getaddrinfo(). We need to get around this in the
        # future or monitor upstream for a fix
        try:
            info = socket.getaddrinfo(bind_addr[0],
                                      bind_addr[1],
                                      socket.AF_UNSPEC,
                                      socket.SOCK_STREAM)[0]
            family = info[0]
            bind_addr = info[-1]
        except Exception:
            family = socket.AF_INET

        try:
            self._socket = eventlet.listen(bind_addr, family, backlog=backlog)
        except EnvironmentError:
            LOG.error("Could not bind to %(host)s:%(port)s",
                      {'host': host, 'port': port})
            raise

        (self.host, self.port) = self._socket.getsockname()[0:2]
        LOG.info("%(name)s listening on %(host)s:%(port)s",
                 {'name': self.name, 'host': self.host, 'port': self.port})

    def start(self):
        """Start serving a WSGI application.

        :returns: None
        """
        # The server socket object will be closed after server exits,
        # but the underlying file descriptor will remain open, and will
        # give bad file descriptor error. So duplicating the socket object,
        # to keep file descriptor usable.

        dup_socket = self._socket.dup()
        dup_socket.setsockopt(socket.SOL_SOCKET,
                              socket.SO_REUSEADDR, 1)
        # sockets can hang around forever without keepalive
        dup_socket.setsockopt(socket.SOL_SOCKET,
                              socket.SO_KEEPALIVE, 1)

        # This option isn't available in the OS X version of eventlet
        if hasattr(socket, 'TCP_KEEPIDLE'):
            dup_socket.setsockopt(socket.IPPROTO_TCP,
                                  socket.TCP_KEEPIDLE,
                                  CONF.wsgi.tcp_keepidle)

        if self._use_ssl:
            try:
                ca_file = CONF.wsgi.ssl_ca_file
                cert_file = CONF.wsgi.ssl_cert_file
                key_file = CONF.wsgi.ssl_key_file

                if cert_file and not os.path.exists(cert_file):
                    raise RuntimeError(
                          _("Unable to find cert_file : %s") % cert_file)

                if ca_file and not os.path.exists(ca_file):
                    raise RuntimeError(
                          _("Unable to find ca_file : %s") % ca_file)

                if key_file and not os.path.exists(key_file):
                    raise RuntimeError(
                          _("Unable to find key_file : %s") % key_file)

                if self._use_ssl and (not cert_file or not key_file):
                    raise RuntimeError(
                          _("When running server in SSL mode, you must "
                            "specify both a cert_file and key_file "
                            "option value in your configuration file"))
                ssl_kwargs = {
                    'server_side': True,
                    'certfile': cert_file,
                    'keyfile': key_file,
                    'cert_reqs': ssl.CERT_NONE,
                }

                if CONF.wsgi.ssl_ca_file:
                    ssl_kwargs['ca_certs'] = ca_file
                    ssl_kwargs['cert_reqs'] = ssl.CERT_REQUIRED

                dup_socket = eventlet.wrap_ssl(dup_socket,
                                               **ssl_kwargs)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(
                        "Failed to start %(name)s on %(host)s:%(port)s with "
                        "SSL support",
                        {'name': self.name, 'host': self.host,
                         'port': self.port})

        wsgi_kwargs = {
            'func': eventlet.wsgi.server,
            'sock': dup_socket,
            'site': self.app,
            'protocol': self._protocol,
            'custom_pool': self._pool,
            'log': self._logger,
            'log_format': CONF.wsgi.wsgi_log_format,
            'debug': False,
            'keepalive': CONF.wsgi.keep_alive,
            'socket_timeout': self.client_socket_timeout
            }

        if self._max_url_len:
            wsgi_kwargs['url_length_limit'] = self._max_url_len

        self._server = utils.spawn(**wsgi_kwargs)

    def reset(self):
        """Reset server greenpool size to default.

        :returns: None

        """
        self._pool.resize(self.pool_size)

    def stop(self):
        """Stop this server.

        This is not a very nice action, as currently the method by which a
        server is stopped is by killing its eventlet.

        :returns: None

        """
        LOG.info("Stopping WSGI server.")

        if self._server is not None:
            # Resize pool to stop new requests from being processed
            self._pool.resize(0)
            self._server.kill()

    def wait(self):
        """Block, until the server has stopped.

        Waits on the server's eventlet to finish, then returns.

        :returns: None

        """
        try:
            if self._server is not None:
                self._pool.waitall()
                self._server.wait()
        except greenlet.GreenletExit:
            LOG.info("WSGI server has stopped.")
