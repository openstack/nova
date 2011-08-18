# Copyright (c) 2011 Openstack, LLC.
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


import nova.scheduler
from nova.scheduler.filters import abstract_filter


class InstanceTypeFilter(abstract_filter.AbstractHostFilter):
    """HostFilter hard-coded to work with InstanceType records."""
    def instance_type_to_filter(self, instance_type):
        """Use instance_type to filter hosts."""
        return (self._full_name(), instance_type)

    def _satisfies_extra_specs(self, capabilities, instance_type):
        """Check that the capabilities provided by the compute service
        satisfy the extra specs associated with the instance type"""
        if 'extra_specs' not in instance_type:
            return True
        # NOTE(lorinh): For now, we are just checking exact matching on the
        # values. Later on, we want to handle numerical
        # values so we can represent things like number of GPU cards
        try:
            for key, value in instance_type['extra_specs'].iteritems():
                if capabilities[key] != value:
                    return False
        except KeyError:
            return False
        return True

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can create instance_type."""
        instance_type = query
        selected_hosts = []
        for host, services in zone_manager.service_states.iteritems():
            capabilities = services.get('compute', {})
            if not capabilities:
                continue
            host_ram_mb = capabilities['host_memory_free']
            disk_bytes = capabilities['disk_available']
            spec_ram = instance_type['memory_mb']
            spec_disk = instance_type['local_gb']
            extra_specs = instance_type['extra_specs']

            if ((host_ram_mb >= spec_ram) and (disk_bytes >= spec_disk) and
                    self._satisfies_extra_specs(capabilities, instance_type)):
                selected_hosts.append((host, capabilities))
        return selected_hosts


# host entries (currently) are like:
#    {'host_name-description': 'Default install of XenServer',
#    'host_hostname': 'xs-mini',
#    'host_memory_total': 8244539392,
#    'host_memory_overhead': 184225792,
#    'host_memory_free': 3868327936,
#    'host_memory_free_computed': 3840843776,
#    'host_other_config': {},
#    'host_ip_address': '192.168.1.109',
#    'host_cpu_info': {},
#    'disk_available': 32954957824,
#    'disk_total': 50394562560,
#    'disk_used': 17439604736,
#    'host_uuid': 'cedb9b39-9388-41df-8891-c5c9a0c0fe5f',
#    'host_name_label': 'xs-mini'}

# instance_type table has:
# name = Column(String(255), unique=True)
# memory_mb = Column(Integer)
# vcpus = Column(Integer)
# local_gb = Column(Integer)
# flavorid = Column(Integer, unique=True)
# swap = Column(Integer, nullable=False, default=0)
# rxtx_quota = Column(Integer, nullable=False, default=0)
# rxtx_cap = Column(Integer, nullable=False, default=0)
