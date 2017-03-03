# Copyright (c) 2016 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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


IPV6_OPTS = [
    cfg.StrOpt('ipv6_backend',
        default='rfc2462',
        choices=('rfc2462', 'account_identifier'),
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Abstracts out IPv6 address generation to pluggable backends.

nova-network can be put into dual-stack mode, so that it uses
both IPv4 and IPv6 addresses. In dual-stack mode, by default, instances
acquire IPv6 global unicast addresses with the help of stateless address
auto-configuration mechanism.

Related options:

* use_neutron: this option only works with nova-network.
* use_ipv6: this option only works if ipv6 is enabled for nova-network.
"""),
]


def register_opts(conf):
    conf.register_opts(IPV6_OPTS)


def list_opts():
    return {'DEFAULT': IPV6_OPTS}
