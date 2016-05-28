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


enabled = cfg.BoolOpt('enabled',
                      default=False,
                      help="""
Enables RDP related features

Hyper-V, unlike the majority of the hypervisors employed on
Nova compute nodes, uses RDP instead of VNC and SPICE as a
desktop sharing protocol to provide instance console access.
This option enables RDP for graphical console access
for virtual machines created by Hyper-V.

* Possible values:

    True or False(default).

* Services that use this:

    ``nova-compute``

* Related options:

    None
""")


html5_proxy_base_url = cfg.StrOpt('html5_proxy_base_url',
        default='http://127.0.0.1:6083/',
        help="""
Location of RDP html5 console proxy

In order to use the web based console access, FreeRDP HTML5
proxy should be configured and installed.

* Possible values:

    Must be a valid URL of the form:``http://host:port/"
    where host and port should be configured in the node
    running FreeRDP HTML5 proxy.

* Services that use this:

    ``nova-compute``

* Related options:

    [rdp]enabled = True
""")

ALL_OPTS = [enabled,
            html5_proxy_base_url]


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group="rdp")


def list_opts():
    return {"rdp": ALL_OPTS}
