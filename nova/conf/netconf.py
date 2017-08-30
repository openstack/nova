# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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

import socket

from oslo_config import cfg
from oslo_utils import netutils


netconf_opts = [
    cfg.StrOpt("my_ip",
        default=netutils.get_my_ipv4(),
        sample_default='<host_ipv4>',
        help="""
The IP address which the host is using to connect to the management network.

Possible values:

* String with valid IP address. Default is IPv4 address of this host.

Related options:

* metadata_host
* my_block_storage_ip
* routing_source_ip
* vpn_ip
"""),
    cfg.StrOpt("my_block_storage_ip",
        default="$my_ip",
        help="""
The IP address which is used to connect to the block storage network.

Possible values:

* String with valid IP address. Default is IP address of this host.

Related options:

* my_ip - if my_block_storage_ip is not set, then my_ip value is used.
"""),
    cfg.StrOpt("host",
        default=socket.gethostname(),
        sample_default='<current_hostname>',
        help="""
Hostname, FQDN or IP address of this host.

Used as:

* the oslo.messaging queue name for nova-compute worker
* we use this value for the binding_host sent to neutron. This means if you use
  a neutron agent, it should have the same value for host.
* cinder host attachment information

Must be valid within AMQP key.

Possible values:

* String with hostname, FQDN or IP address. Default is hostname of this host.
"""),
]


def register_opts(conf):
    conf.register_opts(netconf_opts)


def list_opts():
    return {'DEFAULT': netconf_opts}
