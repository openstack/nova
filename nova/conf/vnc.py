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

vnc_group = cfg.OptGroup(
    'vnc',
    title='VNC options',
    help="""
Virtual Network Computer (VNC) can be used to provide remote desktop
console access to instances for tenants and/or administrators.""")

enabled = cfg.BoolOpt(
    'enabled',
    default=True,
    deprecated_group='DEFAULT',
    deprecated_name='vnc_enabled',
    help="""Enable VNC related features.

Guests will get created with graphical devices to support this. Clients
(for example Horizon) can then establish a VNC connection to the guest.

Possible values:

* True: Enables the feature
* False: Disables the feature

Services which consume this:

* ``nova-compute``

Related options:

* None
""")

keymap = cfg.StrOpt(
    'keymap',
    default='en-us',
    deprecated_group='DEFAULT',
    deprecated_name='vnc_keymap',
    help="""Keymap for VNC.

The keyboard mapping (keymap) determines which keyboard layout a VNC
session should use by default.

Possible values:

* A keyboard layout which is supported by the underlying hypervisor on
  this node. This is usually an 'IETF language tag' (for example
  'en-us').  If you use QEMU as hypervisor, you should find the  list
  of supported keyboard layouts at ``/usr/share/qemu/keymaps``.

Services which consume this:

* ``nova-compute``

Related options:

* None
""")

# TODO(sfinucan): This should be an IPOpt
vncserver_listen = cfg.StrOpt(
    'vncserver_listen',
    default='127.0.0.1',
    deprecated_group='DEFAULT',
    help="""
The IP address on which an instance should listen to for incoming VNC
connection requests on this node.

Possible values:

* An IP address

Services which consume this:

* ``nova-compute``

Related options:

* None
""")

# TODO(sfinucan): This should be an IPOpt
vncserver_proxyclient_address = cfg.StrOpt(
    'vncserver_proxyclient_address',
    default='127.0.0.1',
    deprecated_group='DEFAULT',
    help="""
Private, internal address of VNC console proxy.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients.

This option sets the private address to which proxy clients, such as
``nova-xvpvncproxy``, should connect to.

Possible values:

* An IP address

Services which consume this:

* ``nova-compute``

Related options:

* None
""")

# TODO(sfinucan): This should be an IPOpt
novncproxy_host = cfg.StrOpt(
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

Possible values:

* An IP address

Services which consume this:

* ``nova-compute``

Related options:

* novncproxy_port
* novncproxy_base_url
""")

# TODO(sfinucan): This should be a PortOpt
novncproxy_port = cfg.IntOpt(
    'novncproxy_port',
    default=6080,
    min=1,
    max=65535,
    deprecated_group='DEFAULT',
    help="""
Port that the noVNC console proxy should bind to.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. noVNC provides
VNC support through a websocket-based client.

This option sets the private port to which the noVNC console proxy
service should bind to.

Possible values:

* A port number

Services which consume this:

* ``nova-compute``

Related options:

* novncproxy_host
* novncproxy_base_url
""")

novncproxy_base_url = cfg.StrOpt(
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

Possible values:

* A URL

Services which consume this:

* ``nova-compute``

Related options:

* novncproxy_host
* novncproxy_port
""")

# TODO(sfinucan): This should be an IPOpt
xvpvncproxy_host = cfg.StrOpt(
    'xvpvncproxy_host',
    default='0.0.0.0',
    deprecated_group='DEFAULT',
    help="""
IP address that the XVP VNC console proxy should bind to.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. Xen provides
the Xenserver VNC Proxy, or XVP, as an alternative to the
websocket-based noVNC proxy used by Libvirt. In contrast to noVNC,
XVP clients are Java-based.

This option sets the private address to which the XVP VNC console proxy
service should bind to.

Possible values:

* An IP address

Services which consume this:

* ``nova-compute``

Related options:

* xvpvncproxy_port
* xvpvncproxy_base_url
""")

# TODO(sfinucan): This should be a PortOpt
xvpvncproxy_port = cfg.IntOpt(
    'xvpvncproxy_port',
    default=6081,
    min=1,
    max=65535,
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

Possible values:

* A port number

Services which consume this:

* ``nova-compute``

Related options:

* xvpvncproxy_host
* xvpvncproxy_base_url
""")

xvpvncproxy_base_url = cfg.StrOpt(
    'xvpvncproxy_base_url',
    default='http://127.0.0.1:6081/console',
    deprecated_group='DEFAULT',
    help="""
Public address of XVP VNC console proxy.

The VNC proxy is an OpenStack component that enables compute service
users to access their instances through VNC clients. Xen provides
the Xenserver VNC Proxy, or XVP, as an alternative to the
websocket-based noVNC proxy used by Libvirt. In contrast to noVNC,
XVP clients are Java-based.

This option sets the public base URL to which client systems will
connect. XVP clients can use this address to connect to the XVP
instance and, by extension, the VNC sessions.

Possible values:

* A URL

Services which consume this:

* ``nova-compute``

Related options:

* xvpvncproxy_host
* xvpvncproxy_port
""")

ALL_OPTS = [
    enabled,
    keymap,
    vncserver_listen,
    vncserver_proxyclient_address,
    novncproxy_host,
    novncproxy_port,
    novncproxy_base_url,
    xvpvncproxy_host,
    xvpvncproxy_port,
    xvpvncproxy_base_url]

CLI_OPTS = [
    novncproxy_host,
    novncproxy_port]


def register_opts(conf):
    conf.register_group(vnc_group)
    conf.register_opts(ALL_OPTS, group=vnc_group)


def register_cli_opts(conf):
    conf.register_cli_opts(CLI_OPTS, group=vnc_group)


def list_opts():
    return {vnc_group: ALL_OPTS}
