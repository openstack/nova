# Copyright 2016 OpenStack Foundation
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

spice_opt_group = cfg.OptGroup('spice',
        title="SPICE console features",
        help="""
SPICE console feature allows you to connect to a guest virtual machine.
SPICE is a replacement for fairly limited VNC protocol.

Following requirements must be met in order to use SPICE:

* Virtualization driver must be libvirt
* spice.enabled set to True
* vnc.enabled set to False
* update html5proxy_base_url
* update server_proxyclient_address
""")

CLI_OPTS = [
    cfg.HostAddressOpt('html5proxy_host',
        default='0.0.0.0',
        help="""
IP address or a hostname on which the ``nova-spicehtml5proxy`` service
listens for incoming requests.

Related options:

* This option depends on the ``html5proxy_base_url`` option.
  The ``nova-spicehtml5proxy`` service must be listening on a host that is
  accessible from the HTML5 client.
"""),
    cfg.PortOpt('html5proxy_port',
        default=6082,
        help="""
Port on which the ``nova-spicehtml5proxy`` service listens for incoming
requests.

Related options:

* This option depends on the ``html5proxy_base_url`` option.
  The ``nova-spicehtml5proxy`` service must be listening on a port that is
  accessible from the HTML5 client.
""")
]

ALL_OPTS = [
    cfg.BoolOpt('enabled',
        default=False,
        help="""
Enable SPICE related features.

Related options:

* VNC must be explicitly disabled to get access to the SPICE console. Set the
  enabled option to False in the [vnc] section to disable the VNC console.
"""),
    cfg.BoolOpt('agent_enabled',
        default=True,
        help="""
Enable the SPICE guest agent support on the instances.

The Spice agent works with the Spice protocol to offer a better guest console
experience. However, the Spice console can still be used without the Spice
Agent. With the Spice agent installed the following features are enabled:

* Copy & Paste of text and images between the guest and client machine
* Automatic adjustment of resolution when the client screen changes - e.g.
  if you make the Spice console full screen the guest resolution will adjust to
  match it rather than letterboxing.
* Better mouse integration - The mouse can be captured and released without
  needing to click inside the console or press keys to release it. The
  performance of mouse movement is also improved.
"""),
    cfg.StrOpt('image_compression',
        advanced=True,
        choices=[
            ('auto_glz', 'enable image compression mode to choose between glz '
             'and quic algorithm, based on image properties'),
            ('auto_lz', 'enable image compression mode to choose between lz '
             'and quic algorithm, based on image properties'),
            ('quic', 'enable image compression based on the SFALIC algorithm'),
            ('glz', 'enable image compression using lz with history based '
             'global dictionary'),
            ('lz', 'enable image compression with the Lempel-Ziv algorithm'),
            ('off', 'disable image compression')
        ],
        help="""
Configure the SPICE image compression (lossless).
"""),
    cfg.StrOpt('jpeg_compression',
        advanced=True,
        choices=[
            ('auto', 'enable JPEG image compression automatically'),
            ('never', 'disable JPEG image compression'),
            ('always', 'enable JPEG image compression')
        ],
        help="""
Configure the SPICE wan image compression (lossy for slow links).
"""),
    cfg.StrOpt('zlib_compression',
        advanced=True,
        choices=[
            ('auto', 'enable zlib image compression automatically'),
            ('never', 'disable zlib image compression'),
            ('always', 'enable zlib image compression')
        ],
        help="""
Configure the SPICE wan image compression (lossless for slow links).
"""),
    cfg.BoolOpt('playback_compression',
        advanced=True,
        help="""
Enable the SPICE audio stream compression (using celt).
"""),
    cfg.StrOpt('streaming_mode',
        advanced=True,
        choices=[
            ('filter', 'SPICE server adds additional filters to decide if '
             'video streaming should be activated'),
            ('all', 'any fast-refreshing window can be encoded into a video '
             'stream'),
            ('off', 'no video detection and (lossy) compression is performed')
        ],
        help="""
Configure the SPICE video stream detection and (lossy) compression.
"""),
    cfg.URIOpt('html5proxy_base_url',
        default='http://127.0.0.1:6082/spice_auto.html',
        help="""
Location of the SPICE HTML5 console proxy.

End user would use this URL to connect to the `nova-spicehtml5proxy``
service. This service will forward request to the console of an instance.

In order to use SPICE console, the service ``nova-spicehtml5proxy`` should be
running. This service is typically launched on the controller node.

Possible values:

* Must be a valid URL of the form: ``http://host:port/spice_auto.html``
  where host is the node running ``nova-spicehtml5proxy`` and the port is
  typically 6082. Consider not using default value as it is not well defined
  for any real deployment.

Related options:

* This option depends on ``html5proxy_host`` and ``html5proxy_port`` options.
  The access URL returned by the compute node must have the host
  and port where the ``nova-spicehtml5proxy`` service is listening.
"""),
    cfg.URIOpt('spice_direct_proxy_base_url',
        default='http://127.0.0.1:13002/nova',
        help="""
Location of a SPICE protocol native console proxy.

A user can retrieve a virt-viewer style .vv connection configuration file by
accessing this URL with the attached token when a console is created.

Possible values:

* Must be a valid URL of the form: ``http://host:port/nova`` where host is the
  node running the SPICE protocol native proxy and the port is typically 13002.
  Note that the port component is optional if you are using the default port
  for HTTP or HTTPS. Consider not using the default value as it is not well
  defined for any real deployment.
"""),
    cfg.StrOpt('server_listen',
        default='127.0.0.1',
        help="""
The  address where the SPICE server running on the instances should listen.

Typically, the ``nova-spicehtml5proxy`` proxy client runs on the controller
node and connects over the private network to this address on the compute
node(s).

Possible values:

* IP address to listen on.
"""),
    cfg.StrOpt('server_proxyclient_address',
        default='127.0.0.1',
        help="""
The address used by ``nova-spicehtml5proxy`` client to connect to instance
console.

Typically, the ``nova-spicehtml5proxy`` proxy client runs on the
controller node and connects over the private network to this address on the
compute node(s).

Possible values:

* Any valid IP address on the compute node.

Related options:

* This option depends on the ``server_listen`` option.
  The proxy client must be able to access the address specified in
  ``server_listen`` using the value of this option.
"""),
    cfg.BoolOpt('require_secure',
        default=False,
        help="""
Whether to require secure TLS connections to SPICE consoles.

If you're providing direct access to SPICE consoles instead of using the HTML5
proxy, you may wish those connections to be encrypted. If so, set this value to
True.

Note that use of secure consoles requires that you setup TLS certificates on
each hypervisor.

Possible values:

* False: console traffic is not encrypted.
* True: console traffic is required to be protected by TLS.
"""),
]

ALL_OPTS.extend(CLI_OPTS)


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group=spice_opt_group)


def register_cli_opts(conf):
    conf.register_cli_opts(CLI_OPTS, group=spice_opt_group)


def list_opts():
    return {spice_opt_group: ALL_OPTS}
