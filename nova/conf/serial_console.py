# Copyright 2015 OpenStack Foundation
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

DEFAULT_PORT_RANGE = '10000:20000'

serial_opt_group = cfg.OptGroup("serial_console",
        title="The serial console feature",
        help="""
The serial console feature allows you to connect to a guest in case a
graphical console like VNC, RDP or SPICE is not available. This is only
currently supported for the libvirt, Ironic and hyper-v drivers.""")

ALL_OPTS = [
    cfg.BoolOpt('enabled',
        default=False,
        help="""
Enable the serial console feature.

In order to use this feature, the service ``nova-serialproxy`` needs to run.
This service is typically executed on the controller node.
"""),
    cfg.StrOpt('port_range',
        default=DEFAULT_PORT_RANGE,
        regex=r'^\d+:\d+$',
        help=r"""
A range of TCP ports a guest can use for its backend.

Each instance which gets created will use one port out of this range. If the
range is not big enough to provide another port for an new instance, this
instance won't get launched.

Possible values:

* Each string which passes the regex ``^\d+:\d+$`` For example
  ``10000:20000``. Be sure that the first port number is lower than the second
  port number and that both are in range from 0 to 65535.
"""),
    # TODO(macsz) check if WS protocol is still being used
    cfg.URIOpt('base_url',
        default='ws://127.0.0.1:6083/',
        help="""
The URL an end user would use to connect to the ``nova-serialproxy`` service.

The ``nova-serialproxy`` service is called with this token enriched URL
and establishes the connection to the proper instance.

Related options:

* The IP address must be identical to the address to which the
  ``nova-serialproxy`` service is listening (see option ``serialproxy_host``
  in this section).
* The port must be the same as in the option ``serialproxy_port`` of this
  section.
* If you choose to use a secured websocket connection, then start this option
  with ``wss://`` instead of the unsecured ``ws://``. The options ``cert``
  and ``key`` in the ``[DEFAULT]`` section have to be set for that.
"""),
    cfg.StrOpt('proxyclient_address',
        default='127.0.0.1',
        help="""
The IP address to which proxy clients (like ``nova-serialproxy``) should
connect to get the serial console of an instance.

This is typically the IP address of the host of a ``nova-compute`` service.
"""),
]

CLI_OPTS = [
    cfg.StrOpt('serialproxy_host',
        default='0.0.0.0',
        help="""
The IP address which is used by the ``nova-serialproxy`` service to listen
for incoming requests.

The ``nova-serialproxy`` service listens on this IP address for incoming
connection requests to instances which expose serial console.

Related options:

* Ensure that this is the same IP address which is defined in the option
  ``base_url`` of this section or use ``0.0.0.0`` to listen on all addresses.
"""),
    cfg.PortOpt('serialproxy_port',
        default=6083,
        help="""
The port number which is used by the ``nova-serialproxy`` service to listen
for incoming requests.

The ``nova-serialproxy`` service listens on this port number for incoming
connection requests to instances which expose serial console.

Related options:

* Ensure that this is the same port number which is defined in the option
  ``base_url`` of this section.
""")
]

ALL_OPTS.extend(CLI_OPTS)


def register_opts(conf):
    conf.register_group(serial_opt_group)
    conf.register_opts(ALL_OPTS, group=serial_opt_group)


def register_cli_opts(conf):
    conf.register_group(serial_opt_group)
    conf.register_cli_opts(CLI_OPTS, serial_opt_group)


def list_opts():
    return {serial_opt_group: ALL_OPTS}
