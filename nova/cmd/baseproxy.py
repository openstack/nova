#
#    Copyright (C) 2014 Red Hat, Inc
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
#

"""Base proxy module used to create compatible consoles
for OpenStack Nova."""

import os
import sys

from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

import nova.conf
from nova.conf import novnc
from nova.conf import remote_debug
from nova.console import websocketproxy
from nova import objects
from nova import version


CONF = nova.conf.CONF
remote_debug.register_cli_opts(CONF)
novnc.register_cli_opts(CONF)

gmr_opts.set_defaults(CONF)
objects.register_all()


def exit_with_error(msg, errno=-1):
    sys.stderr.write(msg + '\n')
    sys.exit(errno)


def proxy(host, port, security_proxy=None):
    """:param host: local address to listen on
    :param port: local port to listen on
    :param security_proxy: instance of
        nova.console.securityproxy.base.SecurityProxy

    Setup a proxy listening on @host:@port. If the
    @security_proxy parameter is not None, this instance
    is used to negotiate security layer with the proxy target
    """

    if CONF.ssl_only and not os.path.exists(CONF.cert):
        exit_with_error("SSL only and %s not found" % CONF.cert)

    # Check to see if tty html/js/css files are present
    if CONF.web and not os.path.exists(CONF.web):
        exit_with_error("Can not find html/js files at %s." % CONF.web)

    logging.setup(CONF, "nova")

    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    # Create and start the NovaWebSockets proxy
    websocketproxy.NovaWebSocketProxy(
        listen_host=host,
        listen_port=port,
        source_is_ipv6=CONF.source_is_ipv6,
        cert=CONF.cert,
        key=CONF.key,
        ssl_only=CONF.ssl_only,
        ssl_ciphers=CONF.console.ssl_ciphers,
        ssl_minimum_version=CONF.console.ssl_minimum_version,
        daemon=CONF.daemon,
        record=CONF.record,
        traffic=not CONF.daemon,
        web=CONF.web,
        file_only=True,
        RequestHandlerClass=websocketproxy.NovaProxyRequestHandler,
        security_proxy=security_proxy,
    ).start_server()
