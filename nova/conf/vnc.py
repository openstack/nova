# Copyright (c) 2010 OpenStack Foundation
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

from oslo_config import cfg
from oslo_config import types

vnc_group = cfg.OptGroup(
    'vnc',
    title='VNC options',
    help="""
Virtual Network Computer (VNC) can be used to provide remote desktop
console access to instances for tenants and/or administrators.""")

ALL_OPTS = [
    cfg.BoolOpt(
        'enabled',
        default=True,
        deprecated_group='DEFAULT',
        deprecated_name='vnc_enabled',
        help="""
Enable VNC related features.

Guests will get created with graphical devices to support this. Clients
(for example Horizon) can then establish a VNC connection to the guest.
"""),

    cfg.HostAddressOpt(
        'server_listen',
        default='127.0.0.1',
        help="""
The IP address or hostname on which an instance should listen to for
incoming VNC connection requests on this node.
"""),

    cfg.HostAddressOpt(
        'server_proxyclient_address',
        default='127.0.0.1',
        help="""
Private, internal IP address or hostname of VNC console proxy.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients.

This option sets the private address to which proxy clients, such as
``nova-novncproxy``, should connect to.
"""),

    cfg.URIOpt(
        'novncproxy_base_url',
        default='http://127.0.0.1:6080/vnc_auto.html',
        deprecated_group='DEFAULT',
        help="""
Public address of noVNC VNC console proxy.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. noVNC provides
VNC support through a websocket-based client.

This option sets the public base URL to which client systems will
connect. noVNC clients can use this address to connect to the noVNC
instance and, by extension, the VNC sessions.

If using noVNC >= 1.0.0, you should use ``vnc_lite.html`` instead of
``vnc_auto.html``.

You can also supply extra request arguments which will be passed to
the backend. This might be useful to move console URL to subpath, for example:
``http://127.0.0.1/novnc/vnc_auto.html?path=novnc``

Related options:

* novncproxy_host
* novncproxy_port
"""),

]

CLI_OPTS = [
    cfg.StrOpt(
        'novncproxy_host',
        default='0.0.0.0',
        deprecated_group='DEFAULT',
        help="""
IP address that the noVNC console proxy should bind to.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. noVNC provides
VNC support through a websocket-based client.

This option sets the private address to which the noVNC console proxy
service should bind to.

Related options:

* novncproxy_port
* novncproxy_base_url
"""),

    cfg.PortOpt(
        'novncproxy_port',
        default=6080,
        deprecated_group='DEFAULT',
        help="""
Port that the noVNC console proxy should bind to.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. noVNC provides
VNC support through a websocket-based client.

This option sets the private port to which the noVNC console proxy
service should bind to.

Related options:

* novncproxy_host
* novncproxy_base_url
"""),
    cfg.ListOpt(
        'auth_schemes',
        item_type=types.String(choices=(
            ('none', 'Allow connection without authentication'),
            ('vencrypt', 'Use VeNCrypt authentication scheme'),
        )),
        default=['none'],
        help="""
The authentication schemes to use with the compute node.

Control what RFB authentication schemes are permitted for connections between
the proxy and the compute host. If multiple schemes are enabled, the first
matching scheme will be used, thus the strongest schemes should be listed
first.

Related options:

* ``[vnc]vencrypt_client_key``, ``[vnc]vencrypt_client_cert``: must also be set
"""),
    cfg.StrOpt(
        'vencrypt_client_key',
        help="""The path to the client certificate PEM file (for x509)

The fully qualified path to a PEM file containing the private key which the VNC
proxy server presents to the compute node during VNC authentication.

Related options:

* ``vnc.auth_schemes``: must include ``vencrypt``
* ``vnc.vencrypt_client_cert``: must also be set
"""),
    cfg.StrOpt(
        'vencrypt_client_cert',
        help="""The path to the client key file (for x509)

The fully qualified path to a PEM file containing the x509 certificate which
the VNC proxy server presents to the compute node during VNC authentication.

Related options:

* ``vnc.auth_schemes``: must include ``vencrypt``
* ``vnc.vencrypt_client_key``: must also be set
"""),
    cfg.StrOpt(
        'vencrypt_ca_certs',
        help="""The path to the CA certificate PEM file

The fully qualified path to a PEM file containing one or more x509 certificates
for the certificate authorities used by the compute node VNC server.

Related options:

* ``vnc.auth_schemes``: must include ``vencrypt``
"""),
]

ALL_OPTS.extend(CLI_OPTS)


def register_opts(conf):
    conf.register_group(vnc_group)
    conf.register_opts(ALL_OPTS, group=vnc_group)


def register_cli_opts(conf):
    conf.register_cli_opts(CLI_OPTS, group=vnc_group)


def list_opts():
    return {vnc_group: ALL_OPTS}
