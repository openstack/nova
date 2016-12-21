# Copyright 2016 Huawei Technology corp.
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


floating_ip_opts = [
    cfg.StrOpt('default_floating_pool',
        default='nova',
        help="""
Default pool for floating IPs.

This option specifies the default floating IP pool for allocating floating IPs.

While allocating a floating ip, users can optionally pass in the name of the
pool they want to allocate from, otherwise it will be pulled from the
default pool.

If this option is not set, then 'nova' is used as default floating pool.

Possible values:

* Any string representing a floating IP pool name
"""),
    cfg.BoolOpt('auto_assign_floating_ip',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Autoassigning floating IP to VM

When set to True, floating IP is auto allocated and associated
to the VM upon creation.

Related options:

* use_neutron: this options only works with nova-network.
"""),
   cfg.StrOpt('floating_ip_dns_manager',
        default='nova.network.noop_dns_driver.NoopDNSDriver',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Full class name for the DNS Manager for floating IPs.

This option specifies the class of the driver that provides functionality
to manage DNS entries associated with floating IPs.

When a user adds a DNS entry for a specified domain to a floating IP,
nova will add a DNS entry using the specified floating DNS driver.
When a floating IP is deallocated, its DNS entry will automatically be deleted.

Possible values:

* Full Python path to the class to be used

Related options:

* use_neutron: this options only works with nova-network.
"""),
    cfg.StrOpt('instance_dns_manager',
        default='nova.network.noop_dns_driver.NoopDNSDriver',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Full class name for the DNS Manager for instance IPs.

This option specifies the class of the driver that provides functionality
to manage DNS entries for instances.

On instance creation, nova will add DNS entries for the instance name and
id, using the specified instance DNS driver and domain. On instance deletion,
nova will remove the DNS entries.

Possible values:

* Full Python path to the class to be used

Related options:

* use_neutron: this options only works with nova-network.
"""),
    cfg.StrOpt('instance_dns_domain',
        default='',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
If specified, Nova checks if the availability_zone of every instance matches
what the database says the availability_zone should be for the specified
dns_domain.

Related options:

* use_neutron: this options only works with nova-network.
""")
]


def register_opts(conf):
    conf.register_opts(floating_ip_opts)


def list_opts():
    return {'DEFAULT': floating_ip_opts}
