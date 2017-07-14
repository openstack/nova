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

    cfg.StrOpt(
        'keymap',
        deprecated_group='DEFAULT',
        deprecated_name='vnc_keymap',
        deprecated_for_removal=True,
        deprecated_since='18.0.0',
        deprecated_reason="""
Configuring this option forces QEMU to do keymap conversions. These conversions
are lossy and can result in significant issues for users of non en-US
keyboards. You should instead use a VNC client that supports Extended Key Event
messages, such as noVNC 1.0.0. Refer to bug #1682020 for more information.""",
        help="""
Keymap for VNC.

The keyboard mapping (keymap) determines which keyboard layout a VNC
session should use by default.

Possible values:

* A keyboard layout which is supported by the underlying hypervisor on
  this node. This is usually an 'IETF language tag' (for example
  'en-us').  If you use QEMU as hypervisor, you should find the  list
  of supported keyboard layouts at ``/usr/share/qemu/keymaps``.
"""),

    cfg.HostAddressOpt(
        'server_listen',
        default='127.0.0.1',
        deprecated_opts=[
            cfg.DeprecatedOpt('vncserver_listen', group='DEFAULT'),
            cfg.DeprecatedOpt('vncserver_listen', group='vnc'),
        ],
        help="""
The IP address or hostname on which an instance should listen to for
incoming VNC connection requests on this node.
"""),

    cfg.HostAddressOpt(
        'server_proxyclient_address',
        default='127.0.0.1',
        deprecated_opts=[
            cfg.DeprecatedOpt('vncserver_proxyclient_address',
                              group='DEFAULT'),
            cfg.DeprecatedOpt('vncserver_proxyclient_address', group='vnc'),
        ],
        help="""
Private, internal IP address or hostname of VNC console proxy.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients.

This option sets the private address to which proxy clients, such as
``nova-xvpvncproxy``, should connect to.
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

Related options:

* novncproxy_host
* novncproxy_port
"""),

    cfg.HostAddressOpt(
        'xvpvncproxy_host',
        default='0.0.0.0',
        deprecated_group='DEFAULT',
        help="""
IP address or hostname that the XVP VNC console proxy should bind to.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. Xen provides
the Xenserver VNC Proxy, or XVP, as an alternative to the
websocket-based noVNC proxy used by Libvirt. In contrast to noVNC,
XVP clients are Java-based.

This option sets the private address to which the XVP VNC console proxy
service should bind to.

Related options:

* xvpvncproxy_port
* xvpvncproxy_base_url
"""),

    cfg.PortOpt(
        'xvpvncproxy_port',
        default=6081,
        deprecated_group='DEFAULT',
        help="""
Port that the XVP VNC console proxy should bind to.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. Xen provides
the Xenserver VNC Proxy, or XVP, as an alternative to the
websocket-based noVNC proxy used by Libvirt. In contrast to noVNC,
XVP clients are Java-based.

This option sets the private port to which the XVP VNC console proxy
service should bind to.

Related options:

* xvpvncproxy_host
* xvpvncproxy_base_url
"""),

    cfg.URIOpt(
        'xvpvncproxy_base_url',
        default='http://127.0.0.1:6081/console',
        deprecated_group='DEFAULT',
        help="""
Public URL address of XVP VNC console proxy.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. Xen provides
the Xenserver VNC Proxy, or XVP, as an alternative to the
websocket-based noVNC proxy used by Libvirt. In contrast to noVNC,
XVP clients are Java-based.

This option sets the public base URL to which client systems will
connect. XVP clients can use this address to connect to the XVP
instance and, by extension, the VNC sessions.

Related options:

* xvpvncproxy_host
* xvpvncproxy_port
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
        item_type=types.String(
            choices=['none', 'vencrypt']
        ),
        default=['none'],
        help="""
The authentication schemes to use with the compute node.

Control what RFB authentication schemes are permitted for connections between
the proxy and the compute host. If multiple schemes are enabled, the first
matching scheme will be used, thus the strongest schemes should be listed
first.

Possible values:

* ``none``: allow connection without authentication
* ``vencrypt``: use VeNCrypt authentication scheme

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

Realted options:

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
