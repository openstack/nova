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

rdp_group = cfg.OptGroup(
    'rdp',
    title='RDP options',
    help="""
Options under this group enable and configure Remote Desktop Protocol (
RDP) related features.

This group is only relevant to Hyper-V users.
"""
)

RDP_OPTS = [
    cfg.BoolOpt('enabled',
        default=False,
        help="""
Enable Remote Desktop Protocol (RDP) related features.

Hyper-V, unlike the majority of the hypervisors employed on Nova compute
nodes, uses RDP instead of VNC and SPICE as a desktop sharing protocol to
provide instance console access. This option enables RDP for graphical
console access for virtual machines created by Hyper-V.

**Note:** RDP should only be enabled on compute nodes that support the Hyper-V
virtualization platform.

Related options:

* ``compute_driver``: Must be hyperv.

"""),

    cfg.URIOpt('html5_proxy_base_url',
        schemes=['http', 'https'],
        default='http://127.0.0.1:6083/',
        help="""
The URL an end user would use to connect to the RDP HTML5 console proxy.
The console proxy service is called with this token-embedded URL and
establishes the connection to the proper instance.

An RDP HTML5 console proxy service will need to be configured to listen on the
address configured here. Typically the console proxy service would be run on a
controller node. The localhost address used as default would only work in a
single node environment i.e. devstack.

An RDP HTML5 proxy allows a user to access via the web the text or graphical
console of any Windows server or workstation using RDP. RDP HTML5 console
proxy services include FreeRDP, wsgate.
See https://github.com/FreeRDP/FreeRDP-WebConnect

Possible values:

* <scheme>://<ip-address>:<port-number>/

  The scheme must be identical to the scheme configured for the RDP HTML5
  console proxy service. It is ``http`` or ``https``.

  The IP address must be identical to the address on which the RDP HTML5
  console proxy service is listening.

  The port must be identical to the port on which the RDP HTML5 console proxy
  service is listening.

Related options:

* ``rdp.enabled``: Must be set to ``True`` for ``html5_proxy_base_url`` to be
  effective.
"""),
]


def register_opts(conf):
    conf.register_group(rdp_group)
    conf.register_opts(RDP_OPTS, rdp_group)


def list_opts():
    return {rdp_group: RDP_OPTS}
