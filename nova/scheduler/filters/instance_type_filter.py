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

import logging

from nova.scheduler.filters import abstract_filter


LOG = logging.getLogger('nova.scheduler.filter.instance_type_filter')


class InstanceTypeFilter(abstract_filter.AbstractHostFilter):
    """HostFilter hard-coded to work with InstanceType records."""
    def instance_type_to_filter(self, instance_type):
        """Use instance_type to filter hosts."""
        return instance_type

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
        except KeyError, e:
            return False
        return True

    def _basic_ram_filter(self, host_name, host_info, instance_type):
        """Only return hosts with sufficient available RAM."""
        requested_ram = instance_type['memory_mb']
        free_ram_mb = host_info.free_ram_mb
        return free_ram_mb >= requested_ram

    def filter_hosts(self, host_list, query, options):
        """Return a list of hosts that can create instance_type."""
        instance_type = query
        selected_hosts = []
        for hostname, host_info in host_list:
            if not self._basic_ram_filter(hostname, host_info,
                                          instance_type):
                continue
            capabilities = host_info.compute
            if capabilities:
                if not capabilities.get("enabled", True):
                    continue
                if not self._satisfies_extra_specs(capabilities,
                                                   instance_type):
                    continue

            selected_hosts.append((hostname, host_info))
        return selected_hosts
